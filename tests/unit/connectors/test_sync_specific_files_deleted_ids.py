"""sync_specific_files must not drop IDs of files deleted at the source.

Webhook delete events arrive as bare file IDs. `sync_specific_files`
re-expands IDs via the connector's `list_files()`, which only returns files
that still exist — so deleted IDs used to vanish from the batch (and a
delete-only batch raised "No files to sync after expanding folders"). The
fix re-adds requested IDs that are missing after expansion (excluding known
folders), so `ConnectorFileProcessor` can run its deleted-at-source cleanup
(get_file_content -> 404 -> delete indexed chunks).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_service(live_files: list[dict]):
    from connectors.service import ConnectorService

    service = ConnectorService.__new__(ConnectorService)
    service.session_manager = None
    service.models_service = MagicMock()

    service.task_service = MagicMock()
    service.task_service.document_service = MagicMock()
    service.task_service.create_custom_task = AsyncMock(return_value="task-1")

    connector = MagicMock()
    connector.is_authenticated = True
    connector.cfg = MagicMock()
    connector.list_files = AsyncMock(return_value={"files": live_files})
    service.get_connector = AsyncMock(return_value=connector)

    return service


def _synced_ids(service) -> list[str]:
    args = service.task_service.create_custom_task.await_args.args
    return args[1]


@pytest.mark.asyncio
async def test_deleted_ids_are_kept_alongside_live_files():
    service = _make_service(live_files=[{"id": "live-1", "name": "a.pdf"}])

    task_id = await service.sync_specific_files(
        connection_id="conn-1",
        user_id="user-1",
        file_ids=["live-1", "deleted-1"],
        jwt_token="jwt",
    )

    assert task_id == "task-1"
    assert _synced_ids(service) == ["live-1", "deleted-1"]


@pytest.mark.asyncio
async def test_delete_only_batch_no_longer_raises():
    service = _make_service(live_files=[])

    task_id = await service.sync_specific_files(
        connection_id="conn-1",
        user_id="user-1",
        file_ids=["deleted-1", "deleted-2"],
        jwt_token="jwt",
    )

    assert task_id == "task-1"
    assert _synced_ids(service) == ["deleted-1", "deleted-2"]


@pytest.mark.asyncio
async def test_known_folder_ids_are_not_readded():
    """A folder ID is legitimately replaced by its children during expansion;
    it must not be re-added as a phantom deleted file."""
    service = _make_service(live_files=[{"id": "child-1", "name": "inside.pdf"}])

    await service.sync_specific_files(
        connection_id="conn-1",
        user_id="user-1",
        file_ids=["folder-1"],
        jwt_token="jwt",
        file_infos=[{"id": "folder-1", "name": "Folder", "isFolder": True}],
    )

    assert _synced_ids(service) == ["child-1"]
