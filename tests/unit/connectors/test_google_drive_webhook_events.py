"""Google Drive webhook event coverage.

Pins that `handle_webhook` reports ALL events: created/updated files in the
selected scope AND deletions (`removed` changes and trashed files). Deletions
used to be skipped client-side, so removing a file in Drive never cleaned up
its indexed chunks. Deletions bypass the selected-scope filter deliberately:
a removed file has no metadata and a trashed file is excluded from the
selected-scope set, so neither could ever pass the membership test — and
downstream cleanup of a never-indexed id is a harmless no-op.
"""

import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_connector(changes_response: dict):
    from connectors.google_drive.connector import GoogleDriveConfig, GoogleDriveConnector

    connector = GoogleDriveConnector.__new__(GoogleDriveConnector)
    connector.cfg = GoogleDriveConfig(
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        token_file="/tmp/fake-token.json",
        changes_page_token="token-1",
    )
    connector.authenticate = AsyncMock(return_value=True)
    connector._iter_selected_items = MagicMock(return_value=[{"id": "in-scope-live"}])
    connector._resolve_shortcut = lambda meta: meta
    connector._lock = threading.Lock()
    connector._shortcut_cache = {}

    service = MagicMock()
    service.changes.return_value.list.return_value.execute.return_value = changes_response
    connector.service = service
    return connector


@pytest.mark.asyncio
async def test_handle_webhook_includes_removed_and_trashed_files():
    connector = _make_connector(
        {
            "changes": [
                # Hard delete: no file metadata at all
                {"fileId": "removed-1", "removed": True},
                # Soft delete: file moved to trash
                {"fileId": "trashed-1", "file": {"id": "trashed-1", "trashed": True}},
                # Live change inside the selected scope
                {"fileId": "in-scope-live", "file": {"id": "in-scope-live"}},
                # Live change outside the selected scope: filtered out
                {"fileId": "out-of-scope", "file": {"id": "out-of-scope"}},
                # No fileId at all: ignored
                {"file": {"id": "nameless"}},
            ],
            "newStartPageToken": "token-2",
        }
    )

    affected = await connector.handle_webhook({})

    assert affected == ["removed-1", "trashed-1", "in-scope-live"]
    # Checkpoint advanced for the next notification
    assert connector.cfg.changes_page_token == "token-2"
    # The changes query must request the `removed` flag
    list_kwargs = connector.service.changes.return_value.list.call_args.kwargs
    assert "removed" in list_kwargs["fields"]
