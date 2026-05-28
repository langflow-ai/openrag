"""Google Drive orphan-detection correctness.

Pins two invariants introduced to fix Google Drive sync:

1. Trashed files must be treated as missing in `_iter_selected_items` when
   iterating the `file_ids` path (the path used by `compute_orphans_for_
   connector_type`). Files moved to Google Drive trash still exist by ID and
   `_get_file_meta_by_id` returns their metadata — without an explicit trash
   check the orphan-detection would consider them still present and fail to
   surface them as orphans.

2. `authenticate()` must not make a live API call. The sanity-check
   (`files().get("root")`) was causing false "connection may need
   re-authentication" warnings when the call failed transiently (rate-limit,
   network blip) even though the OAuth token was valid. Credential validity
   is already ensured by `load_credentials()` and `oauth.is_authenticated()`.
"""

import sys
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_connector(file_ids: list[str]):
    """Build a minimal GoogleDriveConnector via __new__, bypassing __init__.

    Only the attributes read by `_iter_selected_items` and `authenticate` are
    set. This avoids the need for real OAuth credentials or token files.
    """
    from connectors.google_drive.connector import GoogleDriveConfig, GoogleDriveConnector

    connector = GoogleDriveConnector.__new__(GoogleDriveConnector)
    connector.cfg = GoogleDriveConfig(
        client_id="fake-client-id",
        client_secret="fake-client-secret",
        token_file="/tmp/fake-token.json",
        file_ids=file_ids,
        folder_ids=None,
        include_mime_types=None,
        exclude_mime_types=None,
    )
    connector.service = MagicMock()
    connector._authenticated = False
    connector._lock = threading.Lock()
    connector._shortcut_cache = {}
    return connector


# ---------------------------------------------------------------------------
# _iter_selected_items — trashed / missing / present
# ---------------------------------------------------------------------------


def test_trashed_file_not_in_iter_selected_items():
    """A file that exists in Drive trash must be excluded from orphan listing.

    Without this guard, `_get_file_meta_by_id` returns metadata for trashed
    files (they still exist by ID), causing them to appear in `remote_ids`
    and thus NOT be flagged as orphans.
    """
    connector = _make_connector(file_ids=["trashed-file-id"])

    with patch.object(
        connector,
        "_get_file_meta_by_id",
        return_value={"id": "trashed-file-id", "mimeType": "application/pdf", "trashed": True},
    ):
        result = connector._iter_selected_items()

    assert result == [], "trashed file must not appear in iter_selected_items output"


def test_non_trashed_file_is_in_iter_selected_items():
    """A file that exists and is not trashed must appear in the results."""
    connector = _make_connector(file_ids=["live-file-id"])

    with patch.object(
        connector,
        "_get_file_meta_by_id",
        return_value={"id": "live-file-id", "mimeType": "application/pdf", "trashed": False},
    ):
        result = connector._iter_selected_items()

    assert len(result) == 1
    assert result[0]["id"] == "live-file-id"


def test_missing_file_id_not_in_iter_selected_items():
    """A file that returns None from `_get_file_meta_by_id` (e.g. permanently
    deleted or permission error) must not appear in the results.

    Regression guard for the pre-existing `if not meta: continue` behavior.
    """
    connector = _make_connector(file_ids=["gone-file-id"])

    with patch.object(connector, "_get_file_meta_by_id", return_value=None):
        result = connector._iter_selected_items()

    assert result == []


# ---------------------------------------------------------------------------
# authenticate() — no live API call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_succeeds_without_live_api_call():
    """authenticate() must not make a live API call to verify credentials.

    The sanity-check `files().get("root").execute()` caused false auth
    failures when the call failed transiently. Removing it means successful
    authentication is determined solely by credential validity — which
    `load_credentials()` and `oauth.is_authenticated()` already ensure.
    """
    from connectors.google_drive.connector import GoogleDriveConnector

    connector = GoogleDriveConnector.__new__(GoogleDriveConnector)
    connector._authenticated = False

    fake_creds = MagicMock()
    fake_service = MagicMock()

    connector.oauth = MagicMock()
    connector.oauth.load_credentials = AsyncMock(return_value=fake_creds)
    connector.oauth.is_authenticated = AsyncMock(return_value=True)
    connector.oauth.get_service = MagicMock(return_value=fake_service)

    result = await connector.authenticate()

    assert result is True
    assert connector._authenticated is True
    # The service must be set — connector is usable after authenticate().
    assert connector.service is fake_service
    # No live API call must have been made.
    fake_service.files.assert_not_called()
