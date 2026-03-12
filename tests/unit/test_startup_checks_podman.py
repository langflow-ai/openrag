"""Tests for Podman setup helpers in startup checks."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parents[2] / "src" / "tui" / "utils" / "startup_checks.py"
SPEC = spec_from_file_location("startup_checks_under_test", MODULE_PATH)
startup_checks = module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(startup_checks)


def _run_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_ensure_krunkit_on_macos_installs_when_missing():
    with patch.object(startup_checks, "get_platform", return_value="macOS"), patch.object(
        startup_checks, "has_cmd", side_effect=lambda cmd: cmd == "brew"
    ), patch.object(startup_checks, "ask_yes_no", return_value=True), patch.object(
        startup_checks.subprocess, "run"
    ) as mock_run:
        ok = startup_checks.ensure_krunkit_on_macos()

    assert ok is True
    calls = [call.args[0] for call in mock_run.call_args_list]
    assert ["brew", "tap", "slp/krunkit"] in calls
    assert ["brew", "install", "krunkit"] in calls


def test_ensure_krunkit_on_macos_skips_when_already_installed():
    with patch.object(startup_checks, "get_platform", return_value="macOS"), patch.object(
        startup_checks, "has_cmd", side_effect=lambda cmd: cmd == "krunkit"
    ), patch.object(startup_checks.subprocess, "run") as mock_run:
        ok = startup_checks.ensure_krunkit_on_macos()

    assert ok is True
    mock_run.assert_not_called()


def test_setup_podman_machine_requires_krunkit_before_init():
    with patch.object(startup_checks, "get_platform", return_value="macOS"), patch.object(
        startup_checks, "ensure_krunkit_on_macos", return_value=False
    ) as mock_ensure, patch.object(startup_checks.subprocess, "run") as mock_run:
        ok = startup_checks.setup_podman_machine()

    assert ok is False
    mock_ensure.assert_called_once_with()
    mock_run.assert_not_called()


def test_install_podman_on_macos_installs_krunkit_dependency():
    with patch.object(startup_checks, "get_platform", return_value="macOS"), patch.object(
        startup_checks, "has_cmd", side_effect=lambda cmd: cmd == "brew"
    ), patch.object(startup_checks, "ask_yes_no", return_value=True), patch.object(
        startup_checks, "ensure_krunkit_on_macos", return_value=True
    ) as mock_ensure, patch.object(
        startup_checks.subprocess, "run", return_value=_run_result()
    ) as mock_run:
        ok = startup_checks.install_podman()

    assert ok is True
    mock_run.assert_called_once_with(["brew", "install", "podman"], check=True)
    mock_ensure.assert_called_once_with()
