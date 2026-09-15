"""Shared contracts for evaluator backends."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from evaluator.termination import TerminationContext
from evaluator.usage import UsageSummary

BEDROCK_HOSTS = [
    "bedrock-runtime.us-east-1.amazonaws.com",
    "bedrock-runtime.us-east-2.amazonaws.com",
    "bedrock-runtime.us-west-2.amazonaws.com",
    "bedrock-runtime.eu-west-1.amazonaws.com",
    "bedrock-runtime.eu-central-1.amazonaws.com",
    "bedrock-runtime.ap-southeast-1.amazonaws.com",
    "bedrock-runtime.ap-northeast-1.amazonaws.com",
]

# AWS STS endpoints for role assumption (needed when AWS_PROFILE uses role_arn)
STS_HOSTS = [
    "sts.amazonaws.com",
    "sts.us-east-1.amazonaws.com",
    "sts.us-east-2.amazonaws.com",
    "sts.us-west-2.amazonaws.com",
    "sts.eu-west-1.amazonaws.com",
    "sts.eu-central-1.amazonaws.com",
    "sts.ap-southeast-1.amazonaws.com",
    "sts.ap-northeast-1.amazonaws.com",
]

VERTEX_HOSTS = [
    "us-central1-aiplatform.googleapis.com",
    "us-east1-aiplatform.googleapis.com",
    "europe-west1-aiplatform.googleapis.com",
]

KIRO_HOSTS = [
    # API (CodeWhisperer/Q service)
    "q.us-east-1.amazonaws.com",
    "q.eu-central-1.amazonaws.com",
    # OIDC token refresh (IAM Identity Center)
    "oidc.us-east-1.amazonaws.com",
    "oidc.us-east-2.amazonaws.com",
    "oidc.us-west-2.amazonaws.com",
    "oidc.eu-central-1.amazonaws.com",
    "oidc.eu-west-1.amazonaws.com",
    "oidc.ap-southeast-1.amazonaws.com",
]

# All known LLM API hosts. Safe to allow all together since the general internet is still blocked (Google, GitHub etc.)
ALL_API_HOSTS = (
    [
        "api.openai.com",
        "chatgpt.com",  # Codex subscription auth (backend-api endpoint)
        "auth.openai.com",  # OAuth token exchange for ChatGPT login
        "api.anthropic.com",
        "console.anthropic.com",  # Claude Code OAuth token exchange
        "platform.claude.com",  # Claude Code OAuth token refresh (current endpoint)
        "generativelanguage.googleapis.com",
        "api.deepseek.com",
        "api.githubcopilot.com",
        "api.business.githubcopilot.com",
        "api.enterprise.githubcopilot.com",
        # Additional providers (pi backend, litellm)
        "api.groq.com",
        "api.mistral.ai",
        "openrouter.ai",
        "api.x.ai",
        "router.huggingface.co",
        "open.bigmodel.cn",  # Zhipu AI / GLM models
        "api.z.ai",  # Zhipu AI / GLM models
        "login.microsoftonline.com",
    ]
    + BEDROCK_HOSTS
    + STS_HOSTS
    + VERTEX_HOSTS
    + KIRO_HOSTS
)


def _hosts_from_env(*env_vars: str) -> list[str]:
    """Extract deduplicated hostnames from endpoint URLs in the given env vars.

    Used for endpoints with customer/provider-specific hostnames that cannot be
    statically enumerated (Azure OpenAI, OpenAI-compatible base URLs, etc.). The
    ``//`` prefix lets ``urlparse`` extract a host even from a scheme-less value.
    """
    hosts: list[str] = []
    for var in env_vars:
        val = os.environ.get(var, "").strip()
        if not val:
            continue
        parsed = urlparse(val if "://" in val else f"//{val}").hostname
        if parsed and parsed not in hosts:
            hosts.append(parsed)
    return hosts


def detect_firewall_hosts(model: str) -> list[str]:
    """All known LLM API hosts. Blocks general internet, allows any provider."""
    # Azure OpenAI and custom OpenAI-compatible endpoints use non-enumerable
    # hostnames supplied through env, so derive them at run time.
    dynamic_hosts = _hosts_from_env(
        "AZURE_OPENAI_HOST",
        "AZURE_API_BASE",
        "AZURE_OPENAI_ENDPOINT",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
    )
    return ALL_API_HOSTS + dynamic_hosts


def has_aws_env_credentials() -> bool:
    """Whether AWS access-key credentials are available through env vars."""
    return bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))


def has_aws_bedrock_bearer_token() -> bool:
    """Whether Bedrock bearer-token auth is available through env vars."""
    return bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK"))


def has_aws_region() -> bool:
    """Whether an AWS region is available through env vars."""
    return bool(os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))


def needs_aws_shared_credentials() -> bool:
    """Whether a container needs ~/.aws for AWS SDK credential resolution."""
    return not (has_aws_bedrock_bearer_token() or has_aws_env_credentials())


def has_aws_shared_credentials() -> bool:
    """Whether host-side AWS shared credentials/config may be available."""
    return (Path.home() / ".aws").is_dir()


@dataclass(frozen=True)
class BackendCapabilities:
    """Execution features supported by a backend approach.

    ``max_*`` is ``None`` when the capability is unbounded.  A cooperative
    deadline lets the backend emit its final audit at the logical benchmark
    deadline; ``timeout_drain_grace`` is only a bounded flush/cleanup window
    before the host hard-kills it, never additional model time.
    ``workspace_tools`` means the model can inspect the supplied workspace and
    iterate with the checker, which proof-from-scratch requires.
    """

    model_preflight: bool = True
    default_infra_retries: int = 3
    max_infra_retries: int | None = None
    max_continuations: int | None = None
    cooperative_deadline: bool = False
    timeout_drain_grace: float = 0.0
    workspace_tools: bool = True


class SubmissionDisposition:
    """What the common runner should do with a backend submission."""

    GRADE = "GRADE"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class SubmissionPlan:
    """Backend-owned preparation result consumed by the common runner."""

    disposition: str = SubmissionDisposition.GRADE
    copy_solution: bool = True
    error: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class Backend(ABC):
    """A first-class evaluator backend, independent of interaction approach."""

    name: str = ""
    approach: str = "agentic"
    provider: str | None = None
    install_script: str | None = None  # run at container start (e.g. "install-codex.sh")
    dynamic_firewall: bool = False  # resolve allowed DNS suffixes throughout the run
    env_keys: list[str] = []  # host env vars to forward into container
    credential_mounts: list[str] = []  # host credential dirs to copy into agent containers
    # Container path holding this backend's session state; --session-dir mounts
    # a persistent host dir here. None = no session dir (e.g. litellm).
    session_state_dir: str | None = None
    # Repository-relative directory where this backend exposes project skills.
    # None means the backend does not support skill discovery.
    project_skills_dir: str | None = None
    capabilities = BackendCapabilities()
    reasoning_effort: str | None = None
    reasoning_effort_values: tuple[str, ...] = ()
    max_output_tokens: int | None = None
    supports_max_output_tokens: bool = False
    requires_public_pricing: bool = False

    def set_reasoning_effort(self, reasoning_effort: str | None) -> None:
        """Validate and store an optional backend-native reasoning effort."""

        if reasoning_effort is None:
            self.reasoning_effort = None
            return
        if reasoning_effort == "":
            raise ValueError(
                f"backend {self.name!r}: --reasoning-effort cannot be empty; omit the option to use the backend default"
            )
        if not self.reasoning_effort_values:
            raise ValueError(f"backend {self.name!r} does not support --reasoning-effort")
        if reasoning_effort not in self.reasoning_effort_values:
            choices = ", ".join(self.reasoning_effort_values)
            raise ValueError(
                f"backend {self.name!r}: invalid --reasoning-effort {reasoning_effort!r}; choose from: {choices}"
            )
        self.reasoning_effort = reasoning_effort

    def set_max_output_tokens(self, max_output_tokens: int | None) -> None:
        """Validate and store an optional per-request output token limit."""

        if max_output_tokens is None:
            self.max_output_tokens = None
            return
        if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool):
            raise ValueError("--max-output-tokens must be an integer")
        if max_output_tokens <= 0:
            raise ValueError("--max-output-tokens must be > 0")
        if not self.supports_max_output_tokens:
            raise ValueError(f"backend {self.name!r} does not support --max-output-tokens")
        self.max_output_tokens = max_output_tokens

    def get_credential_mounts(self) -> list[str]:
        """Credential directories this backend needs mounted for the current run."""
        return list(self.credential_mounts)

    @abstractmethod
    def build_command(self, workspace: str, result_dir: str) -> list[str]:
        """Build the backend command before the prompt is attached.

        Args:
            workspace: agent's working directory (will be the CLI's cwd).
            result_dir: directory for backend-specific output files.
        """

    @abstractmethod
    def parse_output(self, jsonl_path: str) -> tuple[str, int, int]:
        """Parse the backend's stdout dump into (transcript, input_tokens, output_tokens)."""

    def parse_usage(self, jsonl_path: str, *, input_tokens: int, output_tokens: int) -> UsageSummary:
        """Return structured usage while preserving the legacy parser contract.

        Backends can override this as richer provider telemetry becomes
        available. The default adapter keeps third-party and test backends that
        only implement ``parse_output`` working unchanged.
        """

        return UsageSummary.from_legacy(
            input_tokens,
            output_tokens,
            source=f"{self.name or self.__class__.__name__}_legacy_output",
        )

    def is_infra_retryable(self, ctx: TerminationContext) -> bool:
        """Whether a zero-output ``INFRA_ERROR`` is safe to replay.

        Agentic backends retain the historical behavior: after the common
        runner has proved that no output tokens were produced, an
        infrastructure failure may be retried. Stricter approaches can inspect
        their event contract and require explicit transient-error evidence.
        """

        return True

    def retry_may_duplicate_model_work(self, jsonl_path: str) -> bool:
        """Return whether replacing this launch could duplicate model work.

        This supplements usage telemetry for failed or truncated runs whose
        provider emits token counts only on clean completion. A backend should
        return true for unambiguous native model activity and when lost native
        events make the absence of such activity unsafe to assume. It must
        handle missing or malformed output conservatively. The default keeps
        legacy backends on the existing token/request/cost retry policy.
        """

        return False

    def execution_environment(self, result_dir: str) -> dict[str, str]:
        """Backend-owned environment additions for one isolated execution."""

        return {}

    def attempt_output_files(self) -> tuple[str, ...]:
        """Extra result-dir artifacts that must be isolated across retries."""

        return ()

    def build_run_command(self, workspace: str, result_dir: str, deadline: float | None) -> list[str]:
        """Build one execution command.

        Agentic backends retain their existing command unchanged. Approaches
        with a cooperative logical deadline override this hook and propagate
        the absolute epoch deadline to their child runner.
        """

        return self.build_command(workspace, result_dir)

    def prepare_invocation(self, command: list[str], prompt: str) -> tuple[list[str], str | None]:
        """Attach one prompt to a command and return its stdin payload.

        Most backends read the prompt from stdin. Backends whose supported
        non-interactive mode requires a command-line prompt can override this
        hook without changing the common container, local, or preflight paths.
        """

        return command, prompt

    def build_prompt(
        self,
        mode: Any,
        benchmark_path: str,
        dependencies: list[str],
        benchmark_basename: str,
        tlapm_path: str,
        tlapm_lib: str,
    ) -> str:
        """Build the prompt for this backend's interaction approach."""

        return mode.build_prompt(benchmark_basename, tlapm_path, tlapm_lib)

    def initial_result_metadata(self) -> dict[str, object]:
        """Stable metadata stamped on every result before execution."""

        metadata: dict[str, object] = {"approach": self.approach}
        if self.provider is not None:
            metadata["provider"] = self.provider
        if self.reasoning_effort is not None:
            metadata["reasoning_effort"] = self.reasoning_effort
        if self.max_output_tokens is not None:
            metadata["requested_max_output_tokens"] = self.max_output_tokens
        return metadata

    def prepare_submission(
        self,
        jsonl_path: str,
        destination: str,
        termination_reason: str,
        error: str,
        *,
        allow_materialization: bool,
    ) -> SubmissionPlan:
        """Prepare the workspace submission and decide whether to grade it.

        Agentic backends already edit the workspace, so their default plan is
        immediately gradeable. Other approaches own their materialization and
        early-verdict policy in their sibling backend base class.
        """

        if not allow_materialization:
            return SubmissionPlan(copy_solution=False)
        return SubmissionPlan()

    def resolve_infra_retries(self, configured: int | None) -> int:
        """Resolve and validate a retry count for CLI and direct Python calls."""

        retries = self.capabilities.default_infra_retries if configured is None else configured
        if not isinstance(retries, int) or isinstance(retries, bool):
            raise ValueError("--infra-retries must be an integer")
        if retries < 0:
            raise ValueError("--infra-retries must be >= 0")
        maximum = self.capabilities.max_infra_retries
        if maximum is not None and retries > maximum:
            raise ValueError(f"backend {self.name!r} supports at most {maximum} infrastructure retries")
        return retries

    def validate_options(self, infra_retries: int | None, max_continuations: int) -> int:
        """Validate execution policy and return the resolved retry count."""

        retries = self.resolve_infra_retries(infra_retries)
        if not isinstance(max_continuations, int) or isinstance(max_continuations, bool):
            raise ValueError("--max-continuations must be an integer")
        if max_continuations < 0:
            raise ValueError("--max-continuations must be >= 0")
        maximum = self.capabilities.max_continuations
        if maximum is not None and max_continuations > maximum:
            if maximum == 0:
                raise ValueError(f"backend {self.name!r} does not support --max-continuations")
            raise ValueError(f"backend {self.name!r} supports at most {maximum} continuations")
        return retries

    def check_auth(self) -> str | None:
        """Host-side fast auth check. Returns None if OK, error string otherwise."""
        return None

    def firewall_hosts(self) -> list[str]:
        """API hosts that must be reachable.

        When ``dynamic_firewall`` is enabled, each entry also covers its
        subdomains so newly discovered service endpoints can be admitted.
        """
        return []

    def detect_quota_block(self, jsonl_path: str) -> int | None:
        """If the run hit a hard provider usage/quota cap (the agent did no work),
        return seconds to wait before retrying; else None.

        This is distinct from the percentage usage gate: once a provider hard-caps
        the account, the agent emits no usage events, so the gate's utilization
        reading goes stale and never trips. Backends that can recognise the cap in
        their own output override this so the runner pauses-and-retries instead of
        grading a no-op run as a failure. Default: never blocks.
        """
        return None

    def usage_script(self) -> str | None:
        """Repo-relative path to this backend's usage probe, or None if it has
        none. The probe prints subscription utilization as the JSON shape the
        quota gate consumes (see scripts/usage/). Returning None disables the
        proactive gate for this backend. Overrides replace the runner's old
        name-based script selection so adding a backend needs no runner change.
        """
        return None

    def default_quota(self) -> tuple[float, float]:
        """Default (5h%, 7d%) thresholds for the proactive gate when the user
        passes no --quota-5h/--quota-7d. (0, 0) leaves the gate off; a backend
        with a usage_script overrides this with its subscription's sensible caps.
        """
        return (0.0, 0.0)

    def materialize_solution(self, jsonl_path: str, destination: str) -> bool:
        """Materialize a model response at ``destination`` when needed.

        Agentic backends edit the workspace themselves, so the default is a
        no-op. One-shot backends override this hook because their sole model
        response must be converted into the target module before grading.
        """
        return False

    def parse_run_metadata(self, jsonl_path: str) -> dict[str, object]:
        """Return backend-specific, JSON-serializable result metadata."""
        return {}

    def validate_request_audit(self, audit: dict[str, object], request_count: int) -> bool:
        """Validate approach-specific model-request evidence, failing closed by default."""

        return False


# Compatibility for external backends written against the historical name.
# New in-tree backends inherit Backend through AgenticBackend or OneShotBackend.
AgentBackend = Backend
