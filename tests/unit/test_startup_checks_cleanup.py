"""Tests for OpenRAG-only image cleanup behavior in startup checks."""

from unittest.mock import MagicMock, patch

from src.tui.utils import startup_checks


def _run_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Create a subprocess.run-like result mock."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_remove_openrag_images_filters_to_openrag_repos():
    with patch("src.tui.utils.startup_checks.subprocess.run") as mock_run:
        mock_run.side_effect = [
            _run_result(
                stdout=(
                    "langflowai/openrag-backend:latest\timg-openrag-1\n"
                    "docker.io/langflowai/openrag-frontend:v1\timg-openrag-2\n"
                    "library/ubuntu:latest\timg-ubuntu\n"
                    "<none>:<none>\timg-dangling\n"
                )
            ),
            _run_result(returncode=0),
            _run_result(returncode=0),
        ]

        removed, total = startup_checks.remove_openrag_images("docker")

    assert (removed, total) == (2, 2)
    calls = [call.args[0] for call in mock_run.call_args_list]
    assert calls[0] == ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}"]
    assert ["docker", "rmi", "-f", "img-openrag-1"] in calls
    assert ["docker", "rmi", "-f", "img-openrag-2"] in calls
    assert all("img-ubuntu" not in call for call in calls)


def test_fix_storage_corruption_docker_avoids_system_prune():
    with patch("src.tui.utils.startup_checks.ask_yes_no", return_value=True), patch(
        "src.tui.utils.startup_checks.remove_openrag_images", return_value=(1, 1)
    ) as mock_remove, patch("src.tui.utils.startup_checks.subprocess.run") as mock_run:
        ok = startup_checks.fix_storage_corruption(runtime="docker", version="26.1.0")

    assert ok is True
    mock_remove.assert_called_once_with("docker")
    mock_run.assert_not_called()
