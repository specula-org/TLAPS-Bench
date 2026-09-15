"""Tests for ContainerRunner."""

import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from common.container import ContainerConfig, ContainerRunner, _cursor_credential_dir, forward_env
from evaluator.backends.claude_code import ClaudeCodeBackend
from evaluator.backends.codex import CodexBackend
from evaluator.backends.copilot import CopilotBackend
from evaluator.backends.litellm import LiteLLMBackend


class TestBuildDockerArgs:
    def test_basic_args(self):
        runner = ContainerRunner()
        config = ContainerConfig(workspace="/tmp/ws", result_dir="/tmp/res")
        args, cid_file = runner.build_docker_args(config)

        assert args[0] == "docker"
        assert args[1] == "run"
        assert "--rm" in args
        assert "-i" in args
        # No memory/cpu limits by default (uses all host resources)
        assert not any(a.startswith("--memory=") for a in args)
        assert not any(a.startswith("--cpus=") for a in args)

    def test_keep_container_drops_rm_and_names_container(self):
        runner = ContainerRunner()
        config = ContainerConfig(keep_container=True, container_name="tlaps-bench-foo-abc123")
        args, _ = runner.build_docker_args(config)

        # --rm removed so the container survives exit; --name makes it discoverable.
        assert "--rm" not in args
        assert "--name" in args
        assert args[args.index("--name") + 1] == "tlaps-bench-foo-abc123"

    def test_keep_container_without_name_omits_name_flag(self):
        runner = ContainerRunner()
        config = ContainerConfig(keep_container=True)
        args, _ = runner.build_docker_args(config)

        assert "--rm" not in args
        assert "--name" not in args

    def test_name_not_set_by_default(self):
        runner = ContainerRunner()
        config = ContainerConfig()
        args, _ = runner.build_docker_args(config)

        assert "--rm" in args
        assert "--name" not in args

    def test_session_dir_mounts_for_backend_without_credential_mount(self, tmp_path):
        # copilot-style: no credential mount, so the persistent session dir is
        # bind-mounted directly at the backend's session path (and created).
        session_dir = tmp_path / "sessions" / "copilot" / "bench1"
        runner = ContainerRunner()
        config = ContainerConfig(session_dir=str(session_dir), session_container_path="/root/.copilot")
        args, _ = runner.build_docker_args(config)

        mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
        assert f"{session_dir}:/root/.copilot:rw" in mount_args
        assert session_dir.is_dir()

    def test_session_dir_merges_credentials_into_single_persistent_mount(self, tmp_path):
        # claude-style: session path == credential mount path. Credentials must be
        # copied INTO the persistent session dir (not a throwaway tempdir) and the
        # path mounted exactly once, so auth + session state persist together.
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / ".credentials.json").write_text('{"claudeAiOauth": {"accessToken": "secret"}}\n')
        session_dir = tmp_path / "sessions" / "claude_code" / "bench1"

        runner = ContainerRunner()
        config = ContainerConfig(
            credential_mounts=["claude"],
            session_dir=str(session_dir),
            session_container_path="/root/.claude",
        )
        try:
            with patch("common.container.Path.home", return_value=tmp_path):
                args, _ = runner.build_docker_args(config)

            mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
            claude_mounts = [m for m in mount_args if m.endswith(":/root/.claude:rw")]
            assert claude_mounts == [f"{session_dir}:/root/.claude:rw"]
            assert (session_dir / ".credentials.json").exists()
            # persistent, so it is never queued for cleanup
            assert runner._credential_tmps == []
        finally:
            runner.cleanup_credential_tmps()

    def test_no_session_mount_by_default(self):
        runner = ContainerRunner()
        config = ContainerConfig(workspace="/tmp/ws")
        args, _ = runner.build_docker_args(config)

        mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
        assert not any(m.endswith(":/root/.copilot:rw") for m in mount_args)

    def test_workspace_mount(self):
        runner = ContainerRunner()
        config = ContainerConfig(workspace="/tmp/ws")
        args, _ = runner.build_docker_args(config)

        assert "-v" in args
        idx = args.index("-v")
        assert args[idx + 1] == "/tmp/ws:/workspace:rw"

    def test_read_only_file_mounts_follow_writable_workspace(self):
        runner = ContainerRunner()
        config = ContainerConfig(
            workspace="/tmp/ws",
            read_only_files=[
                ("/tmp/ws/Model.tla", "/workspace/Model.tla"),
                ("/tmp/ws/Defs.tla", "/workspace/Defs.tla"),
            ],
        )
        args, _ = runner.build_docker_args(config)

        mount_args = [args[i + 1] for i, arg in enumerate(args) if arg == "-v"]
        assert mount_args[:3] == [
            "/tmp/ws:/workspace:rw",
            "/tmp/ws/Model.tla:/workspace/Model.tla:ro",
            "/tmp/ws/Defs.tla:/workspace/Defs.tla:ro",
        ]

    def test_result_dir_mount(self):
        runner = ContainerRunner()
        config = ContainerConfig(result_dir="/tmp/res")
        args, _ = runner.build_docker_args(config)

        mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
        assert "/tmp/res:/results:rw" in mount_args

    def test_env_forwarding(self):
        runner = ContainerRunner()
        config = ContainerConfig(env={"OPENAI_API_KEY": "sk-test", "FOO": "bar"})
        args, _ = runner.build_docker_args(config)

        env_args = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
        assert "OPENAI_API_KEY=sk-test" in env_args
        assert "FOO=bar" in env_args

    def test_firewall_hosts_set(self):
        runner = ContainerRunner()
        config = ContainerConfig(firewall_hosts=["api.openai.com", "api.anthropic.com"])
        args, _ = runner.build_docker_args(config)

        assert "--cap-add=NET_ADMIN" in args
        assert "--cap-drop=ALL" not in args
        assert "--security-opt=no-new-privileges:true" not in args
        env_args = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
        assert "FIREWALL_HOSTS=api.openai.com,api.anthropic.com" in env_args
        assert "DYNAMIC_FIREWALL=1" not in env_args
        assert not any("ALLOW_ALL_HTTPS" in value for value in env_args)

    def test_dynamic_firewall_uses_only_initialization_capabilities(self):
        runner = ContainerRunner()
        config = ContainerConfig(
            firewall_hosts=["api2.cursor.sh"],
            dynamic_firewall=True,
            cap_net_admin=False,
        )
        args, _ = runner.build_docker_args(config)

        cap_adds = {argument.removeprefix("--cap-add=") for argument in args if argument.startswith("--cap-add=")}
        assert cap_adds == {
            "NET_ADMIN",
            "NET_BIND_SERVICE",
            "NET_RAW",
            "SETPCAP",
            "SETUID",
            "SETGID",
            "CHOWN",
            "FOWNER",
            "DAC_OVERRIDE",
        }
        assert "--cap-drop=ALL" in args
        assert "--security-opt=no-new-privileges:true" in args
        env_args = [args[i + 1] for i, argument in enumerate(args) if argument == "-e"]
        assert "FIREWALL_HOSTS=api2.cursor.sh" in env_args
        assert "DYNAMIC_FIREWALL=1" in env_args

    def test_dynamic_firewall_requires_hosts(self):
        runner = ContainerRunner()
        config = ContainerConfig(dynamic_firewall=True)

        with pytest.raises(ValueError, match="requires at least one firewall host"):
            runner.build_docker_args(config)

    def test_no_firewall_when_empty(self):
        runner = ContainerRunner()
        config = ContainerConfig(firewall_hosts=[])
        args, _ = runner.build_docker_args(config)

        assert "--cap-add=NET_ADMIN" not in args
        env_args = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
        assert "DISABLE_FIREWALL=1" in env_args

    def test_benchmark_dir_mount_ro(self):
        runner = ContainerRunner()
        config = ContainerConfig(benchmark_dir="/tmp/bench")
        args, _ = runner.build_docker_args(config)

        mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
        assert "/tmp/bench:/benchmark:ro" in mount_args

    def test_image_at_end(self):
        runner = ContainerRunner()
        config = ContainerConfig(image="my-image:v1")
        args, _ = runner.build_docker_args(config)

        assert args[-1] == "my-image:v1"

    def test_credentials_not_mounted_by_default(self, tmp_path):
        (tmp_path / ".aws").mkdir()
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".codex").mkdir()

        runner = ContainerRunner()
        config = ContainerConfig()
        with patch("common.container.Path.home", return_value=tmp_path):
            args, _ = runner.build_docker_args(config)

        mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
        assert not any(mount.endswith(":/root/.aws:rw") for mount in mount_args)
        assert not any(mount.endswith(":/root/.claude:rw") for mount in mount_args)
        assert not any(mount.endswith(":/root/.codex:rw") for mount in mount_args)

    def test_claude_mount_copies_only_credentials_file(self, tmp_path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / ".credentials.json").write_text('{"claudeAiOauth": {"accessToken": "secret"}}\n')
        (claude_home / "projects").mkdir()
        (claude_home / "projects" / "old.jsonl").write_text("previous benchmark transcript")

        runner = ContainerRunner()
        config = ContainerConfig(credential_mounts=["claude"])
        try:
            with patch("common.container.Path.home", return_value=tmp_path):
                args, _ = runner.build_docker_args(config)

            mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
            claude_mount = next(m for m in mount_args if m.endswith(":/root/.claude:rw"))
            copied_home = claude_mount.split(":", 1)[0]
            assert os.path.exists(os.path.join(copied_home, ".credentials.json"))
            assert not os.path.exists(os.path.join(copied_home, "projects"))
        finally:
            runner.cleanup_credential_tmps()

    def test_symlinked_minimal_credential_file_is_not_copied(self, tmp_path):
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        secret = tmp_path / "outside-secret"
        secret.write_text("do not copy")
        (claude_home / ".credentials.json").symlink_to(secret)

        runner = ContainerRunner()
        config = ContainerConfig(credential_mounts=["claude"])
        with patch("common.container.Path.home", return_value=tmp_path):
            args, _ = runner.build_docker_args(config)

        mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
        assert not any(mount.endswith(":/root/.claude:rw") for mount in mount_args)

    def test_codex_mount_copies_only_auth_file(self, tmp_path):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text('{"token": "secret"}\n')
        (codex_home / "sessions").mkdir()
        (codex_home / "sessions" / "old.jsonl").write_text("previous benchmark transcript")

        runner = ContainerRunner()
        config = ContainerConfig(credential_mounts=["codex"])
        try:
            with patch("common.container.Path.home", return_value=tmp_path):
                args, _ = runner.build_docker_args(config)

            mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
            codex_mount = next(m for m in mount_args if m.endswith(":/root/.codex:rw"))
            copied_home = codex_mount.split(":", 1)[0]
            assert os.path.exists(os.path.join(copied_home, "auth.json"))
            assert not os.path.exists(os.path.join(copied_home, "sessions"))
        finally:
            runner.cleanup_credential_tmps()

    def test_cursor_mount_uses_macos_credential_dir(self, tmp_path):
        cursor_home = tmp_path / ".cursor"
        cursor_home.mkdir()
        (cursor_home / "auth.json").write_text('{"accessToken": "secret"}\n')

        runner = ContainerRunner()
        config = ContainerConfig(credential_mounts=["cursor"])
        try:
            with (
                patch("common.container.sys.platform", "darwin"),
                patch("common.container.Path.home", return_value=tmp_path),
                patch.dict(os.environ, {}, clear=True),
            ):
                args, _ = runner.build_docker_args(config)

            mount_args = [args[i + 1] for i, arg in enumerate(args) if arg == "-v"]
            cursor_mount = next(m for m in mount_args if m.endswith(":/root/.config/cursor:rw"))
            copied_home = cursor_mount.split(":", 1)[0]
            assert os.path.exists(os.path.join(copied_home, "auth.json"))
        finally:
            runner.cleanup_credential_tmps()

    def test_cursor_mount_uses_linux_xdg_config_home(self, tmp_path):
        xdg_config_home = tmp_path / "xdg"
        cursor_home = xdg_config_home / "cursor"
        cursor_home.mkdir(parents=True)
        (cursor_home / "auth.json").write_text('{"accessToken": "secret"}\n')

        runner = ContainerRunner()
        config = ContainerConfig(credential_mounts=["cursor"])
        try:
            with (
                patch("common.container.sys.platform", "linux"),
                patch("common.container.Path.home", return_value=tmp_path / "unused-home"),
                patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config_home)}, clear=True),
            ):
                args, _ = runner.build_docker_args(config)

            mount_args = [args[i + 1] for i, arg in enumerate(args) if arg == "-v"]
            cursor_mount = next(m for m in mount_args if m.endswith(":/root/.config/cursor:rw"))
            copied_home = cursor_mount.split(":", 1)[0]
            assert os.path.exists(os.path.join(copied_home, "auth.json"))
        finally:
            runner.cleanup_credential_tmps()

    def test_cursor_credential_dir_uses_linux_default_config_home(self, tmp_path):
        with (
            patch("common.container.sys.platform", "linux"),
            patch("common.container.Path.home", return_value=tmp_path),
            patch.dict(os.environ, {}, clear=True),
        ):
            assert _cursor_credential_dir() == tmp_path / ".config" / "cursor"

    def test_codex_mount_copies_only_minimal_bedrock_config(self, tmp_path):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            """
model_provider = "amazon-bedrock"

[model_providers.amazon-bedrock.aws]
region = "us-east-2"
profile = "bench-profile"

[mcp_servers.private]
command = "leaky-local-command"
"""
        )

        runner = ContainerRunner()
        config = ContainerConfig(credential_mounts=["codex"])
        try:
            with patch("common.container.Path.home", return_value=tmp_path):
                args, _ = runner.build_docker_args(config)

            mount_args = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
            codex_mount = next(m for m in mount_args if m.endswith(":/root/.codex:rw"))
            copied_home = codex_mount.split(":", 1)[0]
            with open(os.path.join(copied_home, "config.toml")) as f:
                config_text = f.read()
            assert 'model_provider = "amazon-bedrock"' in config_text
            assert 'region = "us-east-2"' in config_text
            assert 'profile = "bench-profile"' in config_text
            assert "mcp_servers" not in config_text
            assert "leaky-local-command" not in config_text
        finally:
            runner.cleanup_credential_tmps()


class TestBuildCompositeCommand:
    def test_without_install_script(self):
        runner = ContainerRunner()
        result = runner.build_composite_command(["codex", "exec", "--model", "gpt-5.5"])
        assert "/opt/firewall.sh" in result
        assert "capsh --drop=cap_net_admin" in result
        assert "codex exec --model gpt-5.5" in result

    def test_with_install_script(self):
        runner = ContainerRunner()
        result = runner.build_composite_command(
            ["codex", "exec", "--model", "gpt-5.5"],
            install_script="install-codex.sh",
        )
        assert result.startswith("/opt/install-scripts/install-codex.sh")
        assert "/opt/firewall.sh" in result
        assert "capsh --drop=cap_net_admin" in result
        assert "codex exec --model gpt-5.5" in result

    def test_dynamic_firewall_drops_initialization_caps_but_keeps_dac_override(self):
        runner = ContainerRunner()
        result = runner.build_composite_command(
            ["cursor-agent", "--print"],
            dynamic_firewall=True,
        )

        assert "/opt/firewall.sh" in result
        assert (
            "--drop=cap_net_admin,cap_net_bind_service,cap_net_raw,cap_setpcap,"
            "cap_setuid,cap_setgid,cap_chown,cap_fowner"
        ) in result
        assert "--caps=cap_dac_override+eip" in result
        drop_arg = result.split("--drop=", 1)[1].split(" ", 1)[0]
        assert "cap_dac_override" not in drop_arg
        assert result.endswith("-c 'cursor-agent --print'")

    def test_command_quoting(self):
        runner = ContainerRunner()
        result = runner.build_composite_command(["echo", "hello world"])
        assert "hello world" in result  # should be quoted

    def test_agent_start_marker_follows_setup_and_precedes_agent(self):
        runner = ContainerRunner()
        result = runner.build_composite_command(
            ["codex", "exec"],
            install_script="install-codex.sh",
            agent_start_marker="START",
        )

        assert result.index("install-codex.sh") < result.index("/opt/firewall.sh")
        assert result.index("/opt/firewall.sh") < result.index("printf")
        assert result.index("printf") < result.index("capsh")


class TestBackendCredentialMounts:
    def test_backend_credential_mounts_use_only_needed_filesystem_auth(self, tmp_path):
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True),
            patch("evaluator.backends.codex.Path.home", return_value=tmp_path),
        ):
            assert CodexBackend().get_credential_mounts() == []

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("evaluator.backends.codex.Path.home", return_value=tmp_path),
        ):
            assert CodexBackend().get_credential_mounts() == ["codex"]

        with (
            patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "token"}, clear=True),
            patch("evaluator.backends.codex.Path.home", return_value=tmp_path),
        ):
            assert CodexBackend(model="openai.gpt-5.5").get_credential_mounts() == ["codex"]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            assert ClaudeCodeBackend().get_credential_mounts() == []

        with patch.dict(os.environ, {}, clear=True):
            assert ClaudeCodeBackend().get_credential_mounts() == ["claude"]

        with patch.dict(os.environ, {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_BEARER_TOKEN_BEDROCK": "token"}, clear=True):
            assert ClaudeCodeBackend().get_credential_mounts() == []

        with patch.dict(os.environ, {}, clear=True):
            assert LiteLLMBackend(model="bedrock/anthropic.claude-3-5-sonnet").get_credential_mounts() == ["aws"]

        with patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "token"}, clear=True):
            assert LiteLLMBackend(model="bedrock/anthropic.claude-3-5-sonnet").get_credential_mounts() == []

        with patch.dict(os.environ, {}, clear=True):
            assert CopilotBackend().get_credential_mounts() == []

    def test_codex_bedrock_bearer_token_with_config_region_passes_auth(self, tmp_path):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            """
model_provider = "amazon-bedrock"

[model_providers.amazon-bedrock.aws]
region = "us-east-2"
"""
        )
        with (
            patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "token"}, clear=True),
            patch("evaluator.backends.codex.Path.home", return_value=tmp_path),
        ):
            assert CodexBackend(model="openai.gpt-5.5").check_auth() is None

    def test_bedrock_env_auth_requires_backend_specific_region(self, tmp_path):
        with (
            patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "token"}, clear=True),
            patch("evaluator.backends.codex.Path.home", return_value=tmp_path),
        ):
            assert "AWS_REGION" in (CodexBackend(model="openai.gpt-5.5").check_auth() or "")

        with (
            patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "token", "AWS_REGION": "us-east-1"}, clear=True),
            patch("evaluator.backends.codex.Path.home", return_value=tmp_path),
        ):
            assert CodexBackend(model="openai.gpt-5.5").check_auth() is None

        with patch.dict(
            os.environ,
            {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_BEARER_TOKEN_BEDROCK": "token"},
            clear=True,
        ):
            assert "AWS_REGION" in (ClaudeCodeBackend().check_auth() or "")

        with patch.dict(
            os.environ,
            {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_BEARER_TOKEN_BEDROCK": "token", "AWS_REGION": "us-east-1"},
            clear=True,
        ):
            assert ClaudeCodeBackend().check_auth() is None

        with patch.dict(os.environ, {"AWS_BEARER_TOKEN_BEDROCK": "token"}, clear=True):
            assert "AWS_REGION_NAME" in (LiteLLMBackend(model="bedrock/anthropic.claude-3-5-sonnet").check_auth() or "")

        with patch.dict(
            os.environ,
            {"AWS_BEARER_TOKEN_BEDROCK": "token", "AWS_REGION_NAME": "us-east-1"},
            clear=True,
        ):
            assert LiteLLMBackend(model="bedrock/anthropic.claude-3-5-sonnet").check_auth() is None


class TestForwardEnv:
    def test_forwards_set_vars(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test", "FOO": "bar"}, clear=True):
            result = forward_env(["FOO"])
            assert result["OPENAI_API_KEY"] == "sk-test"  # auto-forwarded
            assert result["FOO"] == "bar"  # backend-specific

    def test_skips_empty(self):
        with patch.dict(os.environ, {"EMPTY_KEY": ""}, clear=True):
            result = forward_env(["EMPTY_KEY"])
            assert "EMPTY_KEY" not in result

    def test_empty_keys_list(self):
        with patch.dict(os.environ, {}, clear=True):
            result = forward_env([])
            assert result == {}

    def test_model_passed(self):
        with patch.dict(os.environ, {}, clear=True):
            result = forward_env([], model="gpt-5.5")
            assert result["AGENT_MODEL_ID"] == "gpt-5.5"

    def test_model_none_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            result = forward_env([])
            assert "AGENT_MODEL_ID" not in result


class TestKill:
    @patch("subprocess.run")
    def test_kill_by_id(self, mock_run):
        runner = ContainerRunner()
        runner.kill_by_id("abc123")
        mock_run.assert_called_once_with(
            ["docker", "kill", "abc123"],
            capture_output=True,
            timeout=10,
        )

    @patch("subprocess.run")
    def test_kill_container_run(self, mock_run):
        runner = ContainerRunner()
        proc = MagicMock()
        run = MagicMock(container_id="abc123", proc=proc)
        runner.kill(run)
        mock_run.assert_called_once_with(
            ["docker", "kill", "abc123"],
            capture_output=True,
            timeout=10,
        )

    def test_kill_fallback_no_container_id(self):
        runner = ContainerRunner()
        proc = MagicMock()
        run = MagicMock(container_id="", proc=proc)
        runner.kill(run)
        proc.kill.assert_called_once()


class TestCopilotFirewallHosts:
    def test_includes_github_auth_host(self):
        # Copilot exchanges its GITHUB token at api.github.com before reaching
        # the inference API; without this host the firewall drops the auth call.
        hosts = CopilotBackend().firewall_hosts()
        assert "api.github.com" in hosts
        assert "api.githubcopilot.com" in hosts  # inference host still present


class TestRunPreflight:
    @patch("subprocess.run")
    def test_passes_through_install_and_firewall_path(self, mock_run):
        # A passing probe must still be routed through the real install +
        # firewall composite — that is what makes it able to catch an auth-host
        # block. The old preflight bypassed firewall.sh and so could not.
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        runner = ContainerRunner()
        config = ContainerConfig(
            workspace="/tmp/ws",
            result_dir="/tmp/res",
            firewall_hosts=["api.githubcopilot.com", "api.github.com"],
            install_script="install-copilot.sh",
        )
        runner.run_preflight(config, ["copilot", "-p", "ok"], "say ok")

        composite = mock_run.call_args.args[0][-1]
        assert "/opt/install-scripts/install-copilot.sh" in composite
        assert "/opt/firewall.sh" in composite
        assert mock_run.call_args.kwargs["input"] == "say ok"

    @patch("subprocess.run")
    def test_raises_on_nonzero_exit_with_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Authentication token found but could not be validated.",
        )
        runner = ContainerRunner()
        config = ContainerConfig(firewall_hosts=["api.githubcopilot.com"])
        with pytest.raises(RuntimeError, match="preflight failed"):
            runner.run_preflight(config, ["copilot"], "say ok")


class TestRunAgentContainerSessionWiring:
    """_run_backend_container composes keep_container / session_dir onto the config."""

    def test_copilot_prompt_and_otel_settings_reach_container_runner(self, tmp_path):
        from evaluator import runner as runner_mod

        backend = CopilotBackend(model="test-model")
        item = MagicMock(
            benchmark_path=str(tmp_path / "My-Bench.tla"),
            timeout=0,
            check_timeout=600,
            keep_container=False,
            session_dir="",
        )
        captured = {}

        class _FakeRunner:
            def run(self, config, cmd, stdin_data=None):
                captured.update(config=config, cmd=cmd, stdin_data=stdin_data)
                raise RuntimeError("stop after capture")

            def kill(self, run):
                pass

            def cleanup_credential_tmps(self):
                pass

        with patch.object(runner_mod, "ContainerRunner", _FakeRunner):
            runner_mod._run_backend_container(
                item,
                backend,
                str(tmp_path / "ws"),
                str(tmp_path / "agent"),
                str(tmp_path / "agent.jsonl"),
                "EXACT PROMPT",
                {},
            )

        assert captured["cmd"][-2:] == ["-p", "EXACT PROMPT"]
        assert captured["stdin_data"] is None
        assert captured["config"].env["COPILOT_OTEL_EXPORTER_TYPE"] == "file"
        assert captured["config"].env["COPILOT_OTEL_FILE_EXPORTER_PATH"] == "/results/copilot-otel.jsonl"
        assert captured["config"].agent_start_marker

    def test_container_time_starts_at_marker_and_marker_is_not_agent_output(self, tmp_path, monkeypatch):
        from evaluator import runner as runner_mod

        backend = CopilotBackend(model="test-model")
        item = SimpleNamespace(
            benchmark_path=str(tmp_path / "Bench.tla"),
            timeout=0,
            check_timeout=600,
            keep_container=False,
            session_dir="",
            container_image="unused",
            mode=SimpleNamespace(canonical_replay_required=False),
        )
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()

        class _FakeRunner:
            def run(self, config, _cmd, stdin_data=None):
                assert stdin_data is None
                proc = subprocess.Popen(
                    [
                        "bash",
                        "-c",
                        f"printf '%s\\n' {config.agent_start_marker!r}; printf '%s\\n' '{{\"type\":\"result\"}}'",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                return SimpleNamespace(proc=proc, container_id="")

            def kill(self, _run):
                pytest.fail("completed fake container must not be killed")

            def cleanup_credential_tmps(self):
                pass

        clock = iter((100.0, 105.0))
        monkeypatch.setattr(runner_mod, "ContainerRunner", _FakeRunner)
        monkeypatch.setattr(runner_mod.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr(runner_mod, "STREAM_AGENT_OUTPUT", False)
        output = agent_dir / "output.jsonl"
        result = {}

        duration = runner_mod._run_backend_container(
            item,
            backend,
            str(tmp_path / "workspace"),
            str(agent_dir),
            str(output),
            "prompt",
            result,
        )

        assert duration == 5.0
        assert output.read_text() == '{"type":"result"}\n'
        assert result["agent_exit"] == 0

    def _capture_config(
        self,
        tmp_path,
        *,
        keep_container=False,
        session_dir="",
        read_only_files=None,
        canonical_replay_required=False,
        benchmark_relative="My-Bench.tla",
    ):
        from evaluator import runner as runner_mod

        backend = CopilotBackend()
        item = MagicMock(
            benchmark_path=str(tmp_path / benchmark_relative),
            timeout=0,
            check_timeout=600,
            keep_container=keep_container,
            session_dir=session_dir,
            container_image="tlaps-bench-base:immutable",
            mode=SimpleNamespace(
                canonical_replay_required=canonical_replay_required,
                benchmark_dir=lambda: str(tmp_path),
            ),
        )
        captured = {}

        class _FakeRunner:
            def run(self, config, cmd, stdin_data=None):
                captured["config"] = config
                raise RuntimeError("stop after capture")  # short-circuit the stream loop

            def kill(self, run):
                pass

            def cleanup_credential_tmps(self):
                pass

        result: dict = {}
        with patch.object(runner_mod, "ContainerRunner", _FakeRunner):
            runner_mod._run_backend_container(
                item,
                backend,
                str(tmp_path / "ws"),
                str(tmp_path / "agent"),
                str(tmp_path / "agent.jsonl"),
                "prompt",
                result,
                read_only_files=read_only_files,
            )
        return captured["config"]

    def test_session_dir_keyed_by_benchmark_without_keep_container(self, tmp_path):
        from evaluator import runner as runner_mod

        session_root = tmp_path / "sessions"
        config = self._capture_config(tmp_path, session_dir=str(session_root))
        key = runner_mod._work_item_session_key(
            SimpleNamespace(
                benchmark_path=str(tmp_path / "My-Bench.tla"),
                mode=SimpleNamespace(benchmark_dir=lambda: str(tmp_path)),
            )
        )
        assert config.session_dir == str(session_root / "copilot" / key)
        assert config.session_container_path == "/root/.copilot"

    def test_keep_container_reuses_the_task_session_key(self, tmp_path):
        session_root = tmp_path / "sessions"
        ordinary = self._capture_config(tmp_path, session_dir=str(session_root))
        retained = self._capture_config(tmp_path, session_dir=str(session_root), keep_container=True)

        assert retained.session_dir == ordinary.session_dir
        assert retained.container_name.startswith("tlaps-bench-My-Bench-")

    def test_same_basename_in_different_modules_gets_distinct_sessions(self, tmp_path):
        session_root = tmp_path / "sessions"
        first = self._capture_config(
            tmp_path,
            session_dir=str(session_root),
            benchmark_relative="SuiteA/Consensus.tla",
        )
        second = self._capture_config(
            tmp_path,
            session_dir=str(session_root),
            benchmark_relative="SuiteB/Consensus.tla",
        )

        assert first.session_dir != second.session_dir
        assert os.path.basename(first.session_dir).startswith("SuiteA__Consensus-")
        assert os.path.basename(second.session_dir).startswith("SuiteB__Consensus-")

    def test_no_session_dir_leaves_config_empty(self, tmp_path):
        config = self._capture_config(tmp_path, session_dir="")
        assert config.image == "tlaps-bench-base:immutable"
        assert config.session_dir == ""
        assert config.session_container_path == ""

    def test_keep_container_names_container(self, tmp_path):
        config = self._capture_config(tmp_path, keep_container=True)
        assert config.keep_container is True
        assert config.container_name.startswith("tlaps-bench-My-Bench-")

    def test_read_only_workspace_files_are_mounted_at_their_basenames(self, tmp_path):
        workspace = tmp_path / "ws"
        context = [workspace / "Model.tla", workspace / "Defs.tla"]

        config = self._capture_config(tmp_path, read_only_files=[str(path) for path in context])

        assert config.read_only_files == [
            (str(workspace / "Model.tla"), "/workspace/Model.tla"),
            (str(workspace / "Defs.tla"), "/workspace/Defs.tla"),
        ]

    def test_required_canonical_replay_is_propagated_to_agent_self_check(self, tmp_path):
        config = self._capture_config(tmp_path, canonical_replay_required=True)

        assert config.env["TLAPS_CANONICAL_REPLAY_REQUIRED"] == "1"


class TestResolveSessionDir:
    def test_explicit_session_dir_wins(self, tmp_path):
        from evaluator.runner import _resolve_session_dir

        got = _resolve_session_dir(str(tmp_path / "s"), keep_container=False, use_container=True)
        assert got == str(tmp_path / "s")

    def test_session_dir_is_bound_to_its_physical_tree_before_resume(self, tmp_path):
        from evaluator.runner import _resolve_session_dir

        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        link = tmp_path / "sessions"
        link.symlink_to(first, target_is_directory=True)

        recorded = _resolve_session_dir(str(link), keep_container=False, use_container=True)
        link.unlink()
        link.symlink_to(second, target_is_directory=True)
        resumed = _resolve_session_dir(str(link), keep_container=False, use_container=True)

        assert recorded == str(first)
        assert resumed == str(second)
        assert recorded != resumed

    def test_keep_container_defaults_to_home_dir(self):
        from evaluator.runner import _resolve_session_dir

        got = _resolve_session_dir(None, keep_container=True, use_container=True)
        assert got == os.path.expanduser("~/.tlaps-bench/sessions")

    def test_off_without_keep_or_explicit(self):
        from evaluator.runner import _resolve_session_dir

        assert _resolve_session_dir(None, keep_container=False, use_container=True) == ""

    def test_off_without_container(self, tmp_path):
        from evaluator.runner import _resolve_session_dir

        assert _resolve_session_dir(str(tmp_path), keep_container=True, use_container=False) == ""


class TestPrepareSessionDir:
    def test_creates_dir_and_gitignore_star(self, tmp_path):
        from evaluator.runner import _prepare_session_dir

        session = tmp_path / "sessions"
        _prepare_session_dir(str(session))
        gitignore = session / ".gitignore"
        assert session.is_dir()
        # `*` ignores the whole tree so credential-bearing session data can't be
        # accidentally committed.
        assert "*" in gitignore.read_text().splitlines()

    def test_does_not_overwrite_existing_gitignore(self, tmp_path):
        from evaluator.runner import _prepare_session_dir

        session = tmp_path / "sessions"
        session.mkdir()
        (session / ".gitignore").write_text("custom\n")
        _prepare_session_dir(str(session))
        assert (session / ".gitignore").read_text() == "custom\n"
