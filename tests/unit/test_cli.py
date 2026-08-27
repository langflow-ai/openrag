from types import SimpleNamespace
from unittest.mock import patch

from rich.console import Console

from tui import cli
from tui.managers.container_manager import ServiceStatus


class StubContainerManager:
    def __init__(self, events, available=True, statuses=None):
        self._events = events
        self._available = available
        self._statuses = statuses or {}

    def is_available(self):
        return self._available

    async def start_services(self):
        for event in self._events:
            yield event

    async def get_service_status(self, force_refresh=False):
        return self._statuses


class StubDoclingManager:
    def __init__(
        self, running=False, start_result=(True, "Docling serve starting on http://localhost:5001")
    ):
        self._running = running
        self._start_result = start_result

    def is_running(self):
        return self._running

    async def start(self):
        return self._start_result


def _run(container_manager, docling_manager):
    """Invoke the CLI helper with a recording console.

    Returns (fully_started, output) — the boolean is what the walkthrough
    gates its "OpenRAG is running" message and browser launch on.
    """
    original = cli.console
    recorder = Console(record=True, width=120)
    cli.console = recorder
    try:
        result = cli._start_services_cli(container_manager, docling_manager)
        return result, recorder.export_text()
    finally:
        cli.console = original


def test_full_success_prints_no_summary_line():
    """Everything up: returns True, no warning, no redundant success line (menu header covers it)."""
    fully_started, output = _run(
        StubContainerManager(events=[(True, "Services started successfully", False)]),
        StubDoclingManager(start_result=(True, "Docling serve starting on http://localhost:5001")),
    )

    assert fully_started is True
    assert "Startup incomplete" not in output
    assert "All services started" not in output


def test_docling_failure_reports_partial_startup():
    """Containers up but the docling port is taken: returns False, warns, does not claim success."""
    fully_started, output = _run(
        StubContainerManager(events=[(True, "Services started successfully", False)]),
        StubDoclingManager(
            start_result=(False, "Port 5001 on 0.0.0.0 is already in use by another process."),
        ),
    )

    assert fully_started is False
    assert "Startup incomplete" in output
    assert "docling-serve" in output
    assert "All services started" not in output


def test_container_port_conflict_from_own_containers_is_not_a_failure():
    """start_services reports a port conflict, but the containers are our own
    already-running ones so the status guard must treat them as up, not failed."""
    running = {
        "opensearch": SimpleNamespace(status=ServiceStatus.RUNNING),
        "openrag-backend": SimpleNamespace(status=ServiceStatus.RUNNING),
    }
    fully_started, output = _run(
        StubContainerManager(
            events=[(False, "ERROR: Port conflicts detected:", False)],
            statuses=running,
        ),
        StubDoclingManager(running=True),  # docling already running
    )

    assert fully_started is True
    assert "Startup incomplete" not in output


def test_start_services_cli_ensures_openrag_version(tmp_path, monkeypatch):
    """CLI _start_services_cli must call ensure_openrag_version to set OPENRAG_VERSION in .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("LANGFLOW_SUPERUSER_PASSWORD='secret'\n")

    monkeypatch.delenv("OPENRAG_VERSION", raising=False)

    with (
        patch("utils.paths.get_tui_env_file", return_value=env_file),
        patch("tui.utils.version_check.get_current_version", return_value="9.9.9"),
    ):
        _run(
            StubContainerManager(events=[(True, "Started", False)]),
            StubDoclingManager(running=True),
        )

    assert env_file.exists()
    assert "OPENRAG_VERSION='9.9.9'" in env_file.read_text()
