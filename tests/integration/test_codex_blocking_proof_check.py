"""Run native Codex against a local scripted provider; no paid model calls."""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from evaluator.backends.codex import CodexBackend


@pytest.mark.skipif(shutil.which("codex") is None, reason="requires native Codex CLI")
@pytest.mark.parametrize("code_mode", ["true", "false"])
@pytest.mark.parametrize("tool_name", ["check_proof", "run_tlapm"])
def test_native_codex_waits_for_direct_proof_tool(tmp_path, code_mode, tool_name):
    workspace, profile, results = (tmp_path / name for name in ("workspace", "profile", "results"))
    for directory in (workspace, profile, results):
        directory.mkdir()
    (workspace / "Target.tla").write_text("---- MODULE Target ----\n====\n")
    checker = tmp_path / "check_proof_bin"
    checker.write_text(f'#!{sys.executable}\nimport time\ntime.sleep(1)\nprint("PASS scripted checker")\n')
    checker.chmod(0o755)
    (tmp_path / "tlapm").symlink_to(checker)
    arguments = (
        {"file": "Target.tla"} if tool_name == "check_proof" else {"args": ["--toolbox", "1", "2", "Target.tla"]}
    )
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(time.monotonic())
            if len(requests) == 1:
                item = {
                    "type": "function_call",
                    "id": "fc_check",
                    "call_id": "check_call",
                    "name": tool_name,
                    "namespace": "mcp__tlaps_check",
                    "arguments": json.dumps(arguments),
                }
            else:
                item = {
                    "type": "message",
                    "id": "msg_done",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Check complete."}],
                }
            events = [
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {
                    "type": "response.completed",
                    "response": {
                        "id": f"resp_{len(requests)}",
                        "status": "completed",
                        "output": [item],
                        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    },
                },
            ]
            body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    backend = CodexBackend(model="gpt-6.1-sol")
    command = backend.build_command(str(workspace), str(results))
    command += [
        "--skip-git-repo-check",
        "-c",
        f"features.code_mode={code_mode}",
        "-c",
        'model_provider="local_test"',
        "-c",
        f'model_providers.local_test={{name="Local test",base_url="http://127.0.0.1:{server.server_port}/v1",'
        'wire_api="responses",requires_openai_auth=false}',
    ]
    env = {
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "CODEX_HOME": str(profile),
        "TLAPS_VERIFICATION_POLICY": "{}",
    }
    try:
        result = subprocess.run(
            command,
            input=f"Call {tool_name} for Target.tla and report its result.",
            cwd=workspace,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result.returncode == 0, result.stderr
    assert len(requests) == 2
    assert requests[1] - requests[0] >= 1
    events = [json.loads(line) for line in result.stdout.splitlines()]
    completed = [event["item"] for event in events if event["type"] == "item.completed"]
    check = next(item for item in completed if item["type"] == "mcp_tool_call")
    assert check["server"] == "tlaps_check" and check["tool"] == tool_name
    output = check["result"]["content"][0]["text"]
    assert "EXIT-CODE: 0\n" in output
    if tool_name == "run_tlapm":
        assert "TLAPM-SUMMARY: unavailable" in output
        assert "PASS scripted checker" not in output
        log = Path(
            next(
                line.removeprefix("TLAPM-FULL-LOG: ")
                for line in output.splitlines()
                if line.startswith("TLAPM-FULL-LOG: ")
            )
        )
        assert log.read_text() == "PASS scripted checker\n"
    else:
        assert "PASS scripted checker" in output
    assert not any(item["type"] == "command_execution" for item in completed)
    audit = next(event for event in events if event["type"] == "tlaps.codex_child_usage")
    assert audit["tool_calls"]["total"] == audit["tool_calls"]["tlaps"] == 1
