"""Microsoft Graph connectors: only a positive "item not found" means deleted.

``ConnectorFileProcessor`` deletes a file's indexed chunks when
``get_file_content`` raises ``FileNotFoundError``, and orphan reconciliation
deletes ids missing from ``list_selected_files``. A 401/403/429/5xx, a network
error or a malformed body proves nothing about the file, so it must propagate
instead of reading as "deleted at source" (review 1e).
"""

from unittest.mock import AsyncMock

import httpx
import pytest

GRAPH = "https://graph.microsoft.com/v1.0"


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"{GRAPH}/drives/drive/items/item")
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=httpx.Response(status, request=request)
    )


class _Response:
    """A 200 whose body is not JSON (malformed Graph reply)."""

    status_code = 200
    text = "<html>"

    def json(self):
        raise ValueError("Expecting value")


def _connector(kind: str, tmp_path):
    if kind == "sharepoint":
        from connectors.sharepoint.connector import SharePointConnector

        connector = SharePointConnector({"token_file": str(tmp_path / "token.json")})
    else:
        from connectors.onedrive.connector import OneDriveConnector

        connector = OneDriveConnector({"token_file": str(tmp_path / "token.json")})
    connector.authenticate = AsyncMock(return_value=True)
    return connector


# A plain item id for OneDrive takes the single-request path; SharePoint's
# composite id avoids needing a configured site URL.
_FILE_ID = {"sharepoint": "drive!item", "onedrive": "item"}
KINDS = ["sharepoint", "onedrive"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("status", [404, 410])
async def test_graph_not_found_is_the_deleted_at_source_signal(kind, status, tmp_path):
    connector = _connector(kind, tmp_path)
    connector._make_graph_request = AsyncMock(side_effect=_status_error(status))

    with pytest.raises(FileNotFoundError):
        await connector.get_file_content(_FILE_ID[kind])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "failure",
    [
        _status_error(401),
        _status_error(403),
        _status_error(429),
        _status_error(503),
        httpx.ConnectError("connection refused"),
    ],
    ids=["401", "403", "429", "503", "network"],
)
async def test_transient_metadata_failure_is_not_a_deletion(kind, failure, tmp_path):
    connector = _connector(kind, tmp_path)
    connector._make_graph_request = AsyncMock(side_effect=failure)

    with pytest.raises(type(failure)) as raised:
        await connector.get_file_content(_FILE_ID[kind])
    assert not isinstance(raised.value, FileNotFoundError)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_malformed_metadata_body_is_not_a_deletion(kind, tmp_path):
    connector = _connector(kind, tmp_path)
    connector._make_graph_request = AsyncMock(return_value=_Response())

    with pytest.raises(ValueError) as raised:
        await connector.get_file_content(_FILE_ID[kind])
    assert not isinstance(raised.value, FileNotFoundError)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_selected_listing_drops_only_files_graph_reports_missing(kind, tmp_path):
    """Orphan reconciliation treats an id absent from this listing as deleted,
    so a transient failure must abort the listing rather than drop the id."""
    connector = _connector(kind, tmp_path)
    file_id = _FILE_ID[kind]

    connector._make_graph_request = AsyncMock(side_effect=_status_error(404))
    assert (await connector.list_selected_files([file_id]))["files"] == []

    connector._make_graph_request = AsyncMock(side_effect=_status_error(503))
    with pytest.raises(httpx.HTTPStatusError):
        await connector.list_selected_files([file_id])


# OneDrive's composite / sharing ids try several endpoints in turn.


def _onedrive(tmp_path):
    return _connector("onedrive", tmp_path)


@pytest.mark.asyncio
async def test_onedrive_composite_id_missing_everywhere_is_not_found(tmp_path):
    connector = _onedrive(tmp_path)
    connector._make_graph_request = AsyncMock(side_effect=_status_error(404))

    assert await connector._fetch_item_metadata("drive!item") is None


@pytest.mark.asyncio
async def test_onedrive_composite_id_with_one_transient_failure_raises(tmp_path):
    connector = _onedrive(tmp_path)
    # drives endpoint 503s, the /me/drive fallback 404s: absence is unproven.
    connector._make_graph_request = AsyncMock(side_effect=[_status_error(503), _status_error(404)])

    with pytest.raises(httpx.HTTPStatusError) as raised:
        await connector._fetch_item_metadata("drive!item")
    assert raised.value.response.status_code == 503


@pytest.mark.asyncio
async def test_onedrive_bad_share_encodings_do_not_block_a_later_match(tmp_path):
    connector = _onedrive(tmp_path)
    item = {"id": "sitem", "file": {}}

    class _Ok:
        status_code = 200

        def json(self):
            return item

    # Four share encodings rejected (400), then the drives endpoint resolves it.
    connector._make_graph_request = AsyncMock(side_effect=[_status_error(400)] * 4 + [_Ok()])

    assert await connector._fetch_item_metadata("drive!sitem") == item


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_failed_listing_raises_instead_of_reporting_no_files(kind, tmp_path):
    """An empty listing reads as "every indexed file was deleted"."""
    connector = _connector(kind, tmp_path)
    connector.authenticate = AsyncMock(return_value=False)

    with pytest.raises(RuntimeError):
        await connector.list_files()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_transient_graph_failure_aborts_orphan_reconciliation(kind, tmp_path):
    from types import SimpleNamespace

    from api.connectors import list_remote_files_for_connector_type

    connector = _connector(kind, tmp_path)
    connector._authenticated = True
    connector._make_graph_request = AsyncMock(side_effect=_status_error(503))
    service = SimpleNamespace(
        connection_manager=SimpleNamespace(
            list_connections=AsyncMock(
                return_value=[SimpleNamespace(connection_id="c1", is_active=True)]
            )
        ),
        get_connector=AsyncMock(return_value=connector),
    )

    remote = await list_remote_files_for_connector_type(
        connector_type=kind,
        user_id="alice",
        connector_service=service,
        existing_file_ids=[_FILE_ID[kind]],
    )

    assert remote is None  # "could not determine safely", not "nothing there"
