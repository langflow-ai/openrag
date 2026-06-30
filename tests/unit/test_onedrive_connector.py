from unittest.mock import AsyncMock

import pytest


class _GraphResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_onedrive_cached_download_path_returns_document_with_empty_acl(tmp_path):
    from connectors.onedrive.connector import OneDriveConnector

    connector = OneDriveConnector({"token_file": str(tmp_path / "token.json")})
    connector.authenticate = AsyncMock(return_value=True)
    connector._download_file_from_url = AsyncMock(return_value=b"cached bytes")
    connector.set_file_infos(
        [
            {
                "id": "cached-file",
                "name": "cached.pdf",
                "mimeType": "application/pdf",
                "downloadUrl": "https://download.example/cached.pdf",
                "webUrl": "https://onedrive.example/cached.pdf",
                "size": 12,
            }
        ]
    )

    doc = await connector.get_file_content("cached-file")

    connector._download_file_from_url.assert_awaited_once_with(
        "https://download.example/cached.pdf"
    )
    assert doc.id == "cached-file"
    assert doc.filename == "cached.pdf"
    assert doc.content == b"cached bytes"
    assert doc.acl.owner == ""
    assert doc.acl.allowed_users == []
    assert doc.acl.allowed_groups == []
    assert doc.acl.allowed_principals == []


@pytest.mark.asyncio
async def test_onedrive_fetch_item_metadata_uses_item_id_for_drive_scoped_ids(tmp_path):
    from connectors.onedrive.connector import OneDriveConnector

    connector = OneDriveConnector({"token_file": str(tmp_path / "token.json")})
    connector._make_graph_request = AsyncMock(
        return_value=_GraphResponse(200, {"id": "item-id", "file": {}})
    )

    item = await connector._fetch_item_metadata("drive-id!item-id")

    assert item == {"id": "item-id", "file": {}}
    connector._make_graph_request.assert_awaited_once()
    url = connector._make_graph_request.await_args.args[0]
    assert url == "https://graph.microsoft.com/v1.0/drives/drive-id/items/item-id"


@pytest.mark.asyncio
async def test_onedrive_fetch_item_metadata_strips_sharing_prefix_only_after_full_item_id_fails(
    tmp_path,
):
    from connectors.onedrive.connector import OneDriveConnector

    connector = OneDriveConnector({"token_file": str(tmp_path / "token.json")})
    connector._make_graph_request = AsyncMock(
        side_effect=[
            _GraphResponse(404),
            _GraphResponse(404),
            _GraphResponse(404),
            _GraphResponse(404),
            _GraphResponse(404),
            _GraphResponse(200, {"id": "item-id", "file": {}}),
        ]
    )

    item = await connector._fetch_item_metadata("drive-id!sitem-id")

    assert item == {"id": "item-id", "file": {}}
    urls = [call.args[0] for call in connector._make_graph_request.await_args_list]
    assert urls[4] == "https://graph.microsoft.com/v1.0/drives/drive-id/items/sitem-id"
    assert urls[5] == "https://graph.microsoft.com/v1.0/drives/drive-id/items/item-id"


@pytest.mark.asyncio
async def test_onedrive_sharing_id_fallback_returns_document_with_empty_acl(tmp_path):
    from connectors.onedrive.connector import OneDriveConnector

    class OAuth:
        def get_access_token(self):
            return "access-token"

    connector = OneDriveConnector({"token_file": str(tmp_path / "token.json")})
    connector.oauth = OAuth()
    connector.authenticate = AsyncMock(return_value=True)
    connector._get_file_metadata_by_id = AsyncMock(return_value=None)
    connector._download_via_shares_endpoint = AsyncMock(return_value=b"shared bytes")

    doc = await connector.get_file_content("drive-id!shared-item")

    connector._download_via_shares_endpoint.assert_awaited_once_with(
        "drive-id!shared-item",
        {"Authorization": "Bearer access-token"},
    )
    assert doc.id == "drive-id!shared-item"
    assert doc.content == b"shared bytes"
    assert doc.acl.owner == ""
    assert doc.acl.allowed_users == []
    assert doc.acl.allowed_groups == []
    assert doc.acl.allowed_principals == []
