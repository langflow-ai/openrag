"""Tests for OpenRAG-only image cleanup behavior in ContainerManager."""

from unittest.mock import AsyncMock

import pytest

from tui.managers.container_manager import ContainerManager


async def _collect(async_iterable):
    """Collect all items from an async iterator into a list."""
    return [item async for item in async_iterable]


def _make_manager() -> ContainerManager:
    """Create a minimal ContainerManager instance for unit tests."""
    manager = ContainerManager.__new__(ContainerManager)
    return manager


@pytest.mark.asyncio
async def test_list_openrag_images_filters_non_openrag_and_dangling():
    manager = _make_manager()
    manager._run_runtime_command = AsyncMock(
        return_value=(
            True,
            (
                "langflowai/openrag-backend:latest\timg-openrag-1\n"
                "docker.io/langflowai/openrag-frontend:v1\timg-openrag-2\n"
                "library/ubuntu:latest\timg-ubuntu\n"
                "<none>:<none>\timg-dangling\n"
            ),
            "",
        )
    )

    success, images, error = await manager._list_openrag_images()

    assert success is True
    assert error == ""
    assert [img["id"] for img in images] == ["img-openrag-1", "img-openrag-2"]
    assert all("openrag" in img["full_tag"] for img in images)


@pytest.mark.asyncio
async def test_reset_services_removes_only_openrag_images_without_system_prune():
    manager = _make_manager()
    manager._run_compose_command = AsyncMock(return_value=(True, "", ""))
    manager._list_openrag_images = AsyncMock(
        return_value=(
            True,
            [
                {"full_tag": "langflowai/openrag-backend:latest", "id": "img1"},
                {"full_tag": "langflowai/openrag-frontend:latest", "id": "img2"},
            ],
            "",
        )
    )
    manager._run_runtime_command = AsyncMock(return_value=(True, "", ""))

    updates = await _collect(manager.reset_services())

    assert updates[-1] == (
        True,
        "System reset completed - removed 2 OpenRAG image(s)",
    )
    runtime_calls = [call.args[0] for call in manager._run_runtime_command.call_args_list]
    assert runtime_calls == [["rmi", "img1"], ["rmi", "img2"]]
    assert all(call[:2] != ["system", "prune"] for call in runtime_calls)


@pytest.mark.asyncio
async def test_reset_services_handles_no_openrag_images():
    manager = _make_manager()
    manager._run_compose_command = AsyncMock(return_value=(True, "", ""))
    manager._list_openrag_images = AsyncMock(return_value=(True, [], ""))
    manager._run_runtime_command = AsyncMock()

    updates = await _collect(manager.reset_services())

    assert updates[-1] == (
        True,
        "System reset completed - OpenRAG containers and volumes removed",
    )
    manager._run_runtime_command.assert_not_called()
