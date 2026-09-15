"""Cursor CLI (`cursor-agent`) backend."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlparse

from evaluator import toolcalls
from evaluator.usage import UsageSummary

from .agentic import AgenticBackend

DEFAULT_MODEL = "sonnet-4.5"
DEFAULT_RUNTIME_HOSTS = [
    "api2.cursor.sh",
    "api2direct.cursor.sh",
    "api5.cursor.sh",
    "authenticate.cursor.sh",
    "authenticator.cursor.sh",
    "authentication.cursor.sh",
    "repo42.cursor.sh",
]
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_USAGE_SOURCE = "cursor_cli_result"


def _strict_token(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _result_usage(event: dict[str, object]) -> UsageSummary | None:
    raw_usage = event.get("usage")
    if not isinstance(raw_usage, dict):
        return None

    input_tokens = _strict_token(raw_usage.get("inputTokens"))
    output_tokens = _strict_token(raw_usage.get("outputTokens"))
    cache_read_tokens = _strict_token(raw_usage.get("cacheReadTokens"))
    cache_write_tokens = _strict_token(raw_usage.get("cacheWriteTokens"))
    if None in (input_tokens, output_tokens, cache_read_tokens, cache_write_tokens):
        return None

    return UsageSummary(
        input_tokens=input_tokens + cache_read_tokens + cache_write_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_tokens,
        cache_write_input_tokens=cache_write_tokens,
        sources=(_USAGE_SOURCE,),
        available=True,
        complete=True,
    )


@dataclass(frozen=True)
class _CursorCall:
    kind: str
    body: dict[str, object]


def _cursor_call(event: dict[str, object]) -> _CursorCall | None:
    raw_call = event.get("tool_call")
    if not isinstance(raw_call, dict):
        return None
    calls = [
        _CursorCall(kind=kind, body=body)
        for kind, body in raw_call.items()
        if isinstance(kind, str) and kind.endswith("ToolCall") and isinstance(body, dict)
    ]
    return calls[0] if len(calls) == 1 else None


def _cursor_command(call: _CursorCall | None) -> str | None:
    if call is None or call.kind != "shellToolCall":
        return None
    args = call.body.get("args")
    command = args.get("command") if isinstance(args, dict) else None
    return command if isinstance(command, str) else None


def _same_cursor_call(started: _CursorCall | None, completed: _CursorCall | None) -> bool:
    if started is None or completed is None:
        return started is completed
    start_command = _cursor_command(started)
    completed_command = _cursor_command(completed)
    return started.kind == completed.kind and (
        start_command is None or completed_command is None or start_command == completed_command
    )


def _tool_call_summary(jsonl_path: str) -> toolcalls.ToolCallSummary:
    """Count Cursor's started/completed pairs once and validate its final result."""

    evidence = toolcalls.EventStreamEvidence()
    commands: list[str | None] = []
    starts: dict[str, _CursorCall | None] = {}
    completed_ids: set[str] = set()
    invalid_calls: dict[str, _CursorCall | None] = {}
    anonymous_witnesses: list[str | None] = []
    lifecycle_warnings: list[str] = []
    result_count = 0
    activity_after_result = False
    for event in toolcalls.iter_events(jsonl_path, evidence):
        event_type = event.get("type")
        if event_type == "result":
            result_count += 1
            continue
        if result_count and event_type in {"assistant", "system", "tool_call"}:
            activity_after_result = True
        if event_type != "tool_call":
            continue
        subtype = event.get("subtype")
        call = _cursor_call(event)
        if call is None:
            lifecycle_warnings.append("Cursor tool call has an invalid tool_call object")
        command = _cursor_command(call)
        raw_call_id = event.get("call_id")
        call_id = raw_call_id if isinstance(raw_call_id, str) and raw_call_id else None
        if not isinstance(subtype, str) or subtype not in {"started", "completed"}:
            if call_id is None and not anonymous_witnesses:
                anonymous_witnesses.append(command)
            elif call_id is not None:
                if call_id not in invalid_calls:
                    invalid_calls[call_id] = call
                elif not _same_cursor_call(invalid_calls[call_id], call):
                    lifecycle_warnings.append("Cursor invalid lifecycle records disagree for one call_id")
            lifecycle_warnings.append("Cursor tool-call stream contains an invalid lifecycle subtype")
            continue
        if call_id is None:
            if not anonymous_witnesses:
                anonymous_witnesses.append(command)
            lifecycle_warnings.append("Cursor tool call has a missing or invalid call_id")
            continue
        if subtype == "started":
            if call_id in starts or call_id in completed_ids:
                lifecycle_warnings.append("Cursor tool-call stream contains a duplicate call_id")
            else:
                starts[call_id] = call
                commands.append(command)
        else:
            if call_id in completed_ids:
                lifecycle_warnings.append("Cursor tool-call stream contains a duplicate completion")
            elif call_id not in starts:
                completed_ids.add(call_id)
                commands.append(command)
                lifecycle_warnings.append("Cursor tool completion is missing its start event")
            else:
                completed_ids.add(call_id)
                if not _same_cursor_call(starts[call_id], call):
                    lifecycle_warnings.append("Cursor tool start and completion disagree")

    for call_id, call in invalid_calls.items():
        if call_id not in starts and call_id not in completed_ids:
            commands.append(_cursor_command(call))
    if not starts and not completed_ids and not invalid_calls:
        commands.extend(anonymous_witnesses)
    open_calls = set(starts) - completed_ids
    if open_calls:
        lifecycle_warnings.append("Cursor tool start is missing its completion event")
    terminal_complete = result_count == 1 and not activity_after_result
    if not terminal_complete:
        lifecycle_warnings.append("Cursor tool-call stream has no unique final result")
    return toolcalls.summarize(
        commands,
        evidence,
        lifecycle_complete=terminal_complete and not lifecycle_warnings,
        warnings=lifecycle_warnings,
    )


def _stream_proves_model_activity(jsonl_path: str) -> bool:
    """Detect native response/tool activity when Cursor omits terminal usage."""

    try:
        with open(jsonl_path, encoding="utf-8") as stream:
            for raw in stream:
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "tool_call" and _cursor_call(event) is not None:
                    return True
                if event.get("type") != "assistant":
                    continue
                message = event.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str) and content:
                    return True
                if isinstance(content, list) and any(
                    isinstance(block, dict) and isinstance(block.get("text"), str) and bool(block["text"])
                    for block in content
                ):
                    return True
    except (OSError, UnicodeError):
        return False
    return False


class CursorBackend(AgenticBackend):
    name = "cursor"
    requires_public_pricing = True
    install_script = "install-cursor.sh"
    session_state_dir = None
    project_skills_dir = ".agents/skills"
    # CURSOR_API_KEY / endpoint let users route via an API key instead of the
    # mounted `cursor-agent login` credentials.
    env_keys = [
        "CURSOR_API_KEY",
        "CURSOR_API_ENDPOINT",
    ]

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODEL

    def build_command(self, workspace: str, result_dir: str) -> list[str]:
        # --force: run non-interactively with full tool access (implies workspace
        #   trust), since the Docker container is the isolation boundary.
        # --sandbox disabled: don't nest Cursor's own sandbox inside the container
        #   (avoids the unprivileged-userns/bwrap failure seen with other CLIs).
        return [
            "cursor-agent",
            "--print",
            "--output-format",
            "stream-json",
            "--force",
            "--sandbox",
            "disabled",
            "--workspace",
            workspace,
            "--model",
            self.model,
        ]

    def get_credential_mounts(self) -> list[str]:
        # API-key auth needs no mounted login credentials.
        if os.environ.get("CURSOR_API_KEY"):
            return []
        return ["cursor"]

    def check_auth(self) -> str | None:
        # Fast path: an API key is set.
        if os.environ.get("CURSOR_API_KEY"):
            return None
        # Slow path: ask the CLI whether it's logged in (local read of
        # ~/.config/cursor state; no session pollution).
        try:
            r = subprocess.run(
                ["cursor-agent", "status"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if r.returncode == 0 and "Logged in" in (r.stdout + r.stderr):
                return None
        except FileNotFoundError:
            return "cursor: `cursor-agent` CLI not found on PATH"
        except Exception:
            pass
        return "cursor: no auth detected. Set CURSOR_API_KEY or run `cursor-agent login`."

    @property
    def dynamic_firewall(self) -> bool:
        """Use dynamic DNS only for Cursor's public service endpoints."""
        return "CURSOR_API_ENDPOINT" not in os.environ

    def firewall_hosts(self) -> list[str]:
        """Return the Cursor hosts that must be reachable during a run.

        Default Cursor domains use dynamic DNS suffix matching. A custom
        endpoint keeps the legacy exact-host firewall behavior so private
        enterprise gateways remain supported.
        """
        configured_endpoint = os.environ.get("CURSOR_API_ENDPOINT")
        if configured_endpoint is None:
            return list(DEFAULT_RUNTIME_HOSTS)

        endpoint = configured_endpoint.strip()
        try:
            parsed = urlparse(endpoint)
            port = parsed.port
        except ValueError as exc:
            raise ValueError(f"invalid CURSOR_API_ENDPOINT: {endpoint!r}") from exc

        if (
            parsed.scheme.lower() != "https"
            or not parsed.netloc
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
        ):
            raise ValueError(
                f"CURSOR_API_ENDPOINT must be an absolute HTTPS URL on port 443 with a valid hostname, got {endpoint!r}"
            )

        try:
            hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
            ip_address(hostname)
        except ValueError:
            labels = hostname.split(".")
            if not hostname or len(hostname) > 253 or not all(_DNS_LABEL.fullmatch(label) for label in labels):
                raise ValueError(
                    "CURSOR_API_ENDPOINT must be an absolute HTTPS URL on port 443 "
                    f"with a valid hostname, got {endpoint!r}"
                ) from None
        except UnicodeError as exc:
            raise ValueError(f"invalid CURSOR_API_ENDPOINT hostname: {parsed.hostname!r}") from exc
        else:
            raise ValueError(f"CURSOR_API_ENDPOINT must use a DNS hostname, got {endpoint!r}")

        return [hostname]

    def parse_output(self, jsonl_path: str) -> tuple[str, int, int]:
        lines: list[str] = []
        in_tok = 0
        out_tok = 0

        try:
            with open(jsonl_path) as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue

                    etype = event.get("type", "")

                    if etype == "assistant":
                        message = event.get("message", {})
                        content = message.get("content", [])
                        if isinstance(content, list):
                            for block in content:
                                if not isinstance(block, dict):
                                    continue
                                if block.get("type") == "text":
                                    text = block.get("text", "")
                                    if text:
                                        lines.append(f"[AGENT] {text}")
                                        lines.append("")

                    elif etype == "tool_call":
                        subtype = event.get("subtype", "")
                        call = _cursor_call(event)
                        if call is None:
                            continue
                        kind = call.kind
                        body = call.body
                        args = body.get("args", {}) if isinstance(body, dict) else {}
                        if subtype == "started":
                            lines.append(f"[TOOL] {kind} {self._summarize_args(kind, args)}")
                            lines.append("")
                        elif subtype == "completed":
                            result = body.get("result") if isinstance(body, dict) else None
                            if result is not None:
                                lines.append(f"[TOOL_RESULT] {self._summarize_result(result)}")
                                lines.append("")

                    elif etype == "result":
                        subtype = event.get("subtype", "")
                        result_text = event.get("result", "")
                        if result_text:
                            lines.append(f"[RESULT/{subtype}] {result_text}")
                            lines.append("")
                        usage = _result_usage(event)
                        in_tok = usage.legacy_input_tokens if usage is not None else 0
                        out_tok = usage.legacy_output_tokens if usage is not None else 0

                    elif etype == "error":
                        lines.append(f"[ERROR] {event.get('message', '')}")
                        lines.append("")
        except FileNotFoundError:
            pass

        return "\n".join(lines), in_tok, out_tok

    def parse_usage(self, jsonl_path: str, *, input_tokens: int, output_tokens: int) -> UsageSummary:
        del input_tokens, output_tokens
        terminal_result: dict[str, object] | None = None
        try:
            with open(jsonl_path) as f:
                for raw in f:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict) and event.get("type") == "result":
                        terminal_result = event
        except (OSError, UnicodeError) as exc:
            return UsageSummary(
                sources=(_USAGE_SOURCE,),
                available=False,
                warnings=(f"Cursor JSONL output unavailable: {type(exc).__name__}",),
            )

        usage = _result_usage(terminal_result) if terminal_result is not None else None
        if usage is not None:
            return usage
        return UsageSummary(
            sources=(_USAGE_SOURCE,),
            available=False,
            warnings=("Cursor terminal result usage is unavailable or invalid",),
        )

    def parse_run_metadata(self, jsonl_path: str) -> dict[str, object]:
        return {"tool_calls": _tool_call_summary(jsonl_path).to_dict()}

    def retry_may_duplicate_model_work(self, jsonl_path: str) -> bool:
        # Cursor reports token usage only in its terminal result. A truncated
        # stream can still contain assistant text and completed edits, which
        # must be preserved instead of replayed as a zero-work launch.
        return _stream_proves_model_activity(jsonl_path)

    @staticmethod
    def _summarize_args(kind: str, args: dict) -> str:
        if not isinstance(args, dict):
            return ""
        for key in ("command", "path", "filePath", "query", "pattern"):
            val = args.get(key)
            if isinstance(val, str) and val:
                return val
        try:
            s = json.dumps(args, ensure_ascii=False)
        except (TypeError, ValueError):
            s = str(args)
        return s[:300]

    @staticmethod
    def _summarize_result(result: object) -> str:
        try:
            s = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            s = str(result)
        if len(s) > 3000:
            s = s[:1500] + "\n... (truncated) ...\n" + s[-1500:]
        return s.rstrip()
