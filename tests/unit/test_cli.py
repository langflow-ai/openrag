"""Regression tests for CLI start-services summaries."""

from src.tui import cli


class FakeContainerManager:
    def __init__(self, items=None, available=True):
        self._items = items or []
        self._available = available

    def is_available(self):
        return self._available

    async def start_services(self):
        for item in self._items:
            yield item


class FakeDoclingManager:
    def __init__(self, running=False, start_result=(True, "Docling serve starting on http://localhost:5001")):
        self._running = running
        self._start_result = start_result

    def is_running(self):
        return self._running

    async def start(self):
        success, message = self._start_result
        self._running = success
        return success, message


class PrintCapture:
    def __init__(self):
        self.lines = []

    def __call__(self, *args, **kwargs):
        self.lines.append(" ".join(str(arg) for arg in args))


def test_start_services_cli_warns_when_docling_fails(monkeypatch):
    capture = PrintCapture()
    monkeypatch.setattr(cli.console, "print", capture)

    container_manager = FakeContainerManager(
        items=[
            (False, "Starting OpenRAG services...", False),
            (True, "Services started successfully", False),
        ]
    )
    docling_manager = FakeDoclingManager(
        running=False,
        start_result=(False, "Docling serve process exited immediately (code: 1)"),
    )

    cli._start_services_cli(container_manager, docling_manager)

    output = "\n".join(capture.lines)
    assert "All services started" not in output
    assert "docling-serve is not running" in output


def test_start_services_cli_reports_success_when_containers_and_docling_start(monkeypatch):
    capture = PrintCapture()
    monkeypatch.setattr(cli.console, "print", capture)

    container_manager = FakeContainerManager(
        items=[
            (False, "Starting OpenRAG services...", False),
            (True, "Services started successfully", False),
        ]
    )
    docling_manager = FakeDoclingManager(running=False)

    cli._start_services_cli(container_manager, docling_manager)

    output = "\n".join(capture.lines)
    assert "✓ All services started" in output
