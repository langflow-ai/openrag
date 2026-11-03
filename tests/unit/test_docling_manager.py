"""Tests for the local Docling Serve process launcher."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.openrag_skip_app_onboard


@pytest.mark.asyncio
async def test_docling_launcher_pins_patched_opentelemetry_api(monkeypatch, tmp_path):
    """The transient uvx environment must not reintroduce the reported CVE."""
    import tui.managers.docling_manager as manager_module
    import utils.paths

    class RunningProcess:
        pid = 1234
        returncode = None

        def poll(self):
            return None

    captured_popen = Mock(return_value=RunningProcess())
    monkeypatch.setattr(utils.paths, "get_tui_dir", lambda: tmp_path)
    monkeypatch.setattr(manager_module.subprocess, "Popen", captured_popen)
    monkeypatch.setattr(manager_module.DoclingManager, "_instance", None)
    monkeypatch.setattr(manager_module.DoclingManager, "_initialized", False)

    manager = manager_module.DoclingManager()
    monkeypatch.setattr(manager, "is_running", lambda: False)
    monkeypatch.setattr(manager, "_start_output_capture", lambda: None)

    started, _ = await manager.start(port=0, timeout=0)

    assert started is True
    command = captured_popen.call_args.args[0]
    opentelemetry_index = command.index("opentelemetry-api>=1.45.1,<2.0.0")
    assert command[opentelemetry_index - 1] == "--with"
