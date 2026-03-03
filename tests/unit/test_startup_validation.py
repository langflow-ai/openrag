"""Tests for startup validation module."""

import os
from unittest.mock import patch, MagicMock
import pytest

from config.startup_validation import (
    check_required_env_vars,
    detect_container_runtime,
    check_container_runtime_memory,
    check_opensearch_container_memory,
    validate_startup_requirements,
    ValidationError,
)


class TestCheckRequiredEnvVars:
    """Tests for check_required_env_vars."""

    def test_all_vars_set(self):
        env = {
            "OPENSEARCH_PASSWORD": "MyStr0ng!Pass",
            "LANGFLOW_SUPERUSER": "admin",
            "LANGFLOW_SUPERUSER_PASSWORD": "Admin!Pass123",
            "LANGFLOW_AUTO_LOGIN": "False",
        }
        assert check_required_env_vars(env) == []

    def test_missing_opensearch_password(self):
        env = {
            "OPENSEARCH_PASSWORD": "",
            "LANGFLOW_SUPERUSER": "admin",
            "LANGFLOW_SUPERUSER_PASSWORD": "pass",
        }
        missing = check_required_env_vars(env)
        assert "OPENSEARCH_PASSWORD" in missing

    def test_missing_langflow_superuser(self):
        env = {
            "OPENSEARCH_PASSWORD": "pass",
            "LANGFLOW_SUPERUSER": "",
            "LANGFLOW_SUPERUSER_PASSWORD": "pass",
            "LANGFLOW_AUTO_LOGIN": "False",
        }
        missing = check_required_env_vars(env)
        assert "LANGFLOW_SUPERUSER" in missing

    def test_missing_langflow_superuser_password(self):
        env = {
            "OPENSEARCH_PASSWORD": "pass",
            "LANGFLOW_SUPERUSER": "admin",
            "LANGFLOW_SUPERUSER_PASSWORD": "",
            "LANGFLOW_AUTO_LOGIN": "False",
        }
        missing = check_required_env_vars(env)
        assert "LANGFLOW_SUPERUSER_PASSWORD" in missing

    def test_langflow_auto_login_skips_superuser_checks(self):
        env = {
            "OPENSEARCH_PASSWORD": "pass",
            "LANGFLOW_SUPERUSER": "",
            "LANGFLOW_SUPERUSER_PASSWORD": "",
            "LANGFLOW_AUTO_LOGIN": "True",
        }
        assert check_required_env_vars(env) == []

    def test_all_missing(self):
        env = {
            "OPENSEARCH_PASSWORD": "",
            "LANGFLOW_SUPERUSER": "",
            "LANGFLOW_SUPERUSER_PASSWORD": "",
            "LANGFLOW_AUTO_LOGIN": "False",
        }
        missing = check_required_env_vars(env)
        assert "OPENSEARCH_PASSWORD" in missing
        assert "LANGFLOW_SUPERUSER" in missing
        assert "LANGFLOW_SUPERUSER_PASSWORD" in missing

    def test_defaults_to_os_environ(self):
        """When no env dict is passed, falls back to os.environ."""
        env = {
            "OPENSEARCH_PASSWORD": "pass",
            "LANGFLOW_SUPERUSER": "admin",
            "LANGFLOW_SUPERUSER_PASSWORD": "pass",
            "LANGFLOW_AUTO_LOGIN": "False",
        }
        with patch.dict(os.environ, env, clear=False):
            assert check_required_env_vars() == []


class TestDetectContainerRuntime:
    """Tests for detect_container_runtime."""

    def test_colima_detected(self):
        mock_result = MagicMock(returncode=0, stdout="Running")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            assert detect_container_runtime() == "colima"
            mock_run.assert_called_once()

    def test_docker_detected(self):
        def side_effect(cmd, **kwargs):
            if cmd[0] == "colima":
                raise FileNotFoundError
            if cmd[0] == "podman":
                raise FileNotFoundError
            return MagicMock(returncode=0, stdout="Docker Engine")

        with patch("subprocess.run", side_effect=side_effect):
            assert detect_container_runtime() == "docker"

    def test_podman_detected(self):
        def side_effect(cmd, **kwargs):
            if cmd[0] == "colima":
                raise FileNotFoundError
            if cmd[0] == "podman":
                return MagicMock(returncode=0, stdout="podman")
            raise FileNotFoundError

        with patch("subprocess.run", side_effect=side_effect):
            assert detect_container_runtime() == "podman"

    def test_podman_masquerading_as_docker(self):
        def side_effect(cmd, **kwargs):
            if cmd[0] == "colima":
                raise FileNotFoundError
            if cmd[0] == "podman":
                raise FileNotFoundError
            # docker info returns podman info
            return MagicMock(returncode=0, stdout="podman version 4.0")

        with patch("subprocess.run", side_effect=side_effect):
            assert detect_container_runtime() == "podman"

    def test_no_runtime(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert detect_container_runtime() is None


class TestCheckContainerRuntimeMemory:
    """Tests for check_container_runtime_memory."""

    def test_colima_sufficient_memory(self):
        import json
        status = json.dumps({"memory": 8192})
        mock_result = MagicMock(returncode=0, stdout=status)
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = check_container_runtime_memory("colima")
            assert ok is True
            assert msg == ""

    def test_colima_insufficient_memory(self):
        import json
        status = json.dumps({"memory": 2048})
        mock_result = MagicMock(returncode=0, stdout=status)
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = check_container_runtime_memory("colima")
            assert ok is False
            assert "insufficient memory" in msg.lower()
            assert "colima" in msg.lower()

    def test_no_runtime_returns_ok(self):
        """When no runtime is detected, assume OK."""
        with patch("config.startup_validation.detect_container_runtime", return_value=None):
            with patch("subprocess.run", side_effect=FileNotFoundError):
                ok, msg = check_container_runtime_memory(None)
                assert ok is True


class TestCheckOpensearchContainerMemory:
    """Tests for check_opensearch_container_memory."""

    def test_no_runtime_detected(self):
        with patch("config.startup_validation.detect_container_runtime", return_value=None):
            ok, msg = check_opensearch_container_memory()
            assert ok is True

    def test_container_not_running_falls_back_to_runtime_check(self):
        def mock_run(cmd, **kwargs):
            if "inspect" in cmd:
                return MagicMock(returncode=1, stdout="", stderr="no such container")
            if cmd[0] == "colima":
                return MagicMock(returncode=0, stdout='{"memory": 8192}')
            if "system" in cmd:
                return MagicMock(returncode=0, stdout="8589934592")
            return MagicMock(returncode=1)

        with patch("config.startup_validation.detect_container_runtime", return_value="colima"):
            with patch("subprocess.run", side_effect=mock_run):
                ok, msg = check_opensearch_container_memory()
                assert ok is True


class TestValidateStartupRequirements:
    """Tests for validate_startup_requirements."""

    def test_passes_with_valid_config(self):
        env = {
            "OPENSEARCH_PASSWORD": "MyStr0ng!Pass",
            "LANGFLOW_SUPERUSER": "admin",
            "LANGFLOW_SUPERUSER_PASSWORD": "Admin!Pass123",
            "LANGFLOW_AUTO_LOGIN": "False",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("config.startup_validation.check_opensearch_container_memory", return_value=(True, "")):
                # Should not raise
                validate_startup_requirements()

    def test_raises_on_missing_env_vars(self):
        env = {
            "OPENSEARCH_PASSWORD": "",
            "LANGFLOW_SUPERUSER": "",
            "LANGFLOW_SUPERUSER_PASSWORD": "",
            "LANGFLOW_AUTO_LOGIN": "False",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("config.startup_validation.check_opensearch_container_memory", return_value=(True, "")):
                with pytest.raises(ValidationError, match="Missing required environment variables"):
                    validate_startup_requirements()

    def test_raises_on_insufficient_memory(self):
        env = {
            "OPENSEARCH_PASSWORD": "MyStr0ng!Pass",
            "LANGFLOW_SUPERUSER": "admin",
            "LANGFLOW_SUPERUSER_PASSWORD": "Admin!Pass123",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "config.startup_validation.check_opensearch_container_memory",
                return_value=(False, "Colima has insufficient memory: 2048MB"),
            ):
                with pytest.raises(ValidationError, match="Memory check failed"):
                    validate_startup_requirements()

    def test_raises_with_both_errors(self):
        env = {
            "OPENSEARCH_PASSWORD": "",
            "LANGFLOW_SUPERUSER": "",
            "LANGFLOW_SUPERUSER_PASSWORD": "",
            "LANGFLOW_AUTO_LOGIN": "False",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "config.startup_validation.check_opensearch_container_memory",
                return_value=(False, "insufficient memory"),
            ):
                with pytest.raises(ValidationError) as exc_info:
                    validate_startup_requirements()
                error_msg = str(exc_info.value)
                assert "Missing required environment variables" in error_msg
                assert "Memory check failed" in error_msg
