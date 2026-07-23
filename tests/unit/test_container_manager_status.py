import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tui.managers.container_manager import ContainerManager, ServiceStatus
from tui.utils.platform import RuntimeType


def _make_manager() -> ContainerManager:
    """Build a ContainerManager without running __init__ (no runtime probing)."""
    manager = ContainerManager.__new__(ContainerManager)
    manager.runtime_info = SimpleNamespace(
        runtime_type=RuntimeType.PODMAN, runtime_command=["podman"]
    )
    manager.services_cache = {}
    manager.last_status_update = 0.0
    manager.expected_services = ["opensearch", "openrag-backend"]
    # Name map uses the default "openrag" prefix; real containers below are "tui-*".
    manager.container_name_map = {
        "openrag-opensearch": "opensearch",
        "openrag-backend": "openrag-backend",
    }
    return manager


@pytest.mark.asyncio
async def test_status_resolves_by_compose_label_despite_prefix_mismatch():
    """A tui-* container must resolve to RUNNING via its compose service label."""
    manager = _make_manager()
    containers = [
        {
            "Names": ["tui-opensearch"],
            "State": "running",
            "Labels": {"com.docker.compose.service": "opensearch"},
        },
    ]
    manager._run_runtime_command = AsyncMock(return_value=(True, json.dumps(containers), ""))

    services = await manager.get_service_status(force_refresh=True)

    assert services["opensearch"].status == ServiceStatus.RUNNING


def test_process_service_json_resolves_by_service_field_despite_prefix_mismatch():
    """Docker: _process_service_json must resolve tui-* containers via the Service field."""
    manager = _make_manager()
    services: dict = {}

    manager._process_service_json(
        {"Name": "tui-opensearch", "Service": "opensearch", "State": "running"}, services
    )

    assert services["opensearch"].status == ServiceStatus.RUNNING


def test_resolve_service_name_falls_back_to_name_map():
    """Without a compose label, resolution matches the legacy name map (no regression)."""
    manager = _make_manager()

    assert manager._resolve_service_name(None, "openrag-opensearch") == "opensearch"
    assert manager._resolve_service_name(None, "unrelated-container") is None
