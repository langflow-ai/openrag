from types import SimpleNamespace

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
    """Invoke the CLI helper with a recording console and return its output."""
    original = cli.console
    recorder = Console(record=True, width=120)
    cli.console = recorder
    try:
        cli._start_services_cli(container_manager, docling_manager)
        return recorder.export_text()
    finally:
        cli.console = original


def test_full_success_prints_no_summary_line():
    """Everything up: no warning, and no redundant success line (menu header covers it)."""
    output = _run(
        StubContainerManager(events=[(True, "Services started successfully", False)]),
        StubDoclingManager(start_result=(True, "Docling serve starting on http://localhost:5001")),
    )

    assert "Startup incomplete" not in output
    assert "All services started" not in output


def test_docling_failure_reports_partial_startup():
    """Containers up but the docling port is taken: warn, do not claim success."""
    output = _run(
        StubContainerManager(events=[(True, "Services started successfully", False)]),
        StubDoclingManager(
            start_result=(False, "Port 5001 on 0.0.0.0 is already in use by another process."),
        ),
    )

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
    output = _run(
        StubContainerManager(
            events=[(False, "ERROR: Port conflicts detected:", False)],
            statuses=running,
        ),
        StubDoclingManager(running=True),  # docling already running
    )

    assert "Startup incomplete" not in output
