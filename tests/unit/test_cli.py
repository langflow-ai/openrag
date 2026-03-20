from rich.console import Console

from tui import cli


class StubContainerManager:
    def __init__(self, available=True, events=None):
        self._available = available
        self._events = events or [(True, "Services started successfully", False)]

    def is_available(self):
        return self._available

    async def start_services(self):
        for event in self._events:
            yield event


class StubDoclingManager:
    def __init__(self, running=False, start_result=(True, "Docling serve starting")):
        self._running = running
        self._start_result = start_result

    def is_running(self):
        return self._running

    async def start(self):
        return self._start_result


def render_start_output(container_manager, docling_manager):
    original_console = cli.console
    test_console = Console(record=True, width=120)
    cli.console = test_console
    try:
        cli._start_services_cli(container_manager, docling_manager)
        return test_console.export_text()
    finally:
        cli.console = original_console


def test_start_services_reports_partial_start_when_docling_fails():
    output = render_start_output(
        StubContainerManager(),
        StubDoclingManager(start_result=(False, "Docling serve process exited immediately (code: 1)")),
    )

    assert "All services started" not in output
    assert "Containers started, but docling-serve did not start" in output
    assert "code: 1" in output


def test_start_services_reports_success_when_everything_starts():
    output = render_start_output(
        StubContainerManager(),
        StubDoclingManager(start_result=(True, "Docling serve starting on http://localhost:5001")),
    )

    assert "All services started" in output
    assert "did not start" not in output
