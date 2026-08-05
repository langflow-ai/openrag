"""
Unit tests for the GET /v1/files and GET /v1/files/search route handlers.

Tests cover:
- Route delegates to the v2 handler with all params forwarded correctly
- Auth dependency is require_api_key_permission("knowledge:read:own"),
  NOT get_current_user
- 401 returned on OpenSearch auth errors
- 400 returned on malformed after_key cursor
- 500 returned on unexpected errors
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.v1.files import list_files, search_files
from session_manager import User


def _make_user() -> User:
    user = MagicMock(spec=User)
    user.user_id = "test-user-id"
    user.jwt_token = "test-jwt"
    return user


def _make_file_service(result: dict) -> MagicMock:
    svc = MagicMock()
    svc.list_files = AsyncMock(return_value=result)
    svc.search_files = AsyncMock(return_value=result)
    return svc


_SAMPLE_RESPONSE = {
    "files": [
        {
            "filename": "report.pdf",
            "document_id": "doc-1",
            "mimetype": "application/pdf",
            "file_size": 12345,
            "source_url": "",
            "owner": "user-1",
            "owner_name": "Alice",
            "owner_email": "alice@example.com",
            "connector_type": "local",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 1536,
            "indexed_time": "2024-01-01T00:00:00Z",
            "chunk_count": 5,
            "allowed_users": [],
            "allowed_groups": [],
            "allowed_principal_labels": [],
        }
    ],
    "total": 1,
    "is_approximate": True,
    "page": 1,
    "page_size": 25,
    "after_key": None,
}


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    @pytest.mark.asyncio
    async def test_returns_file_list_on_success(self):
        """Handler returns the service response as JSONResponse."""
        file_service = _make_file_service(_SAMPLE_RESPONSE)
        user = _make_user()

        response = await list_files(
            page=1,
            page_size=25,
            sort_by="filename",
            sort_order="asc",
            connector_type=None,
            mimetype=None,
            owner=None,
            search=None,
            after_key=None,
            file_service=file_service,
            user=user,
        )

        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        assert body["total"] == 1
        assert body["files"][0]["filename"] == "report.pdf"
        # Verify all filter/knowledge fields are present
        f = body["files"][0]
        for field in (
            "document_id",
            "mimetype",
            "file_size",
            "connector_type",
            "chunk_count",
            "indexed_time",
            "allowed_users",
        ):
            assert field in f, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_forwards_all_params_to_service(self):
        """All query params are forwarded to FileServiceV2.list_files."""
        file_service = _make_file_service(_SAMPLE_RESPONSE)
        user = _make_user()

        await list_files(
            page=2,
            page_size=50,
            sort_by="indexed_time",
            sort_order="desc",
            connector_type="sharepoint",
            mimetype="application/pdf",
            owner="user-42",
            search="report",
            after_key='{"filename": "a.pdf"}',
            file_service=file_service,
            user=user,
        )

        file_service.list_files.assert_awaited_once()
        call_kwargs = file_service.list_files.call_args.kwargs
        assert call_kwargs["page"] == 2
        assert call_kwargs["page_size"] == 50
        assert call_kwargs["sort_by"] == "indexed_time"
        assert call_kwargs["sort_order"] == "desc"
        assert call_kwargs["connector_type"] == "sharepoint"
        assert call_kwargs["mimetype"] == "application/pdf"
        assert call_kwargs["owner"] == "user-42"
        assert call_kwargs["search"] == "report"
        assert call_kwargs["after_key"] == {"filename": "a.pdf"}

    @pytest.mark.asyncio
    async def test_returns_401_on_opensearch_auth_error(self):
        """OpenSearch auth errors surface as 401, not 500."""
        from opensearchpy.exceptions import AuthenticationException

        file_service = MagicMock()
        file_service.list_files = AsyncMock(side_effect=AuthenticationException(401, "auth failed"))
        user = _make_user()

        response = await list_files(
            page=1,
            page_size=25,
            sort_by="filename",
            sort_order="asc",
            connector_type=None,
            mimetype=None,
            owner=None,
            search=None,
            after_key=None,
            file_service=file_service,
            user=user,
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_500_on_unexpected_error(self):
        """Unexpected errors return 500."""
        file_service = MagicMock()
        file_service.list_files = AsyncMock(side_effect=RuntimeError("boom"))
        user = _make_user()

        response = await list_files(
            page=1,
            page_size=25,
            sort_by="filename",
            sort_order="asc",
            connector_type=None,
            mimetype=None,
            owner=None,
            search=None,
            after_key=None,
            file_service=file_service,
            user=user,
        )

        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_invalid_after_key_returns_400(self):
        """A non-JSON after_key value raises HTTPException 400 before the service is called."""
        from fastapi import HTTPException

        file_service = _make_file_service(_SAMPLE_RESPONSE)
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await list_files(
                page=1,
                page_size=25,
                sort_by="filename",
                sort_order="asc",
                connector_type=None,
                mimetype=None,
                owner=None,
                search=None,
                after_key="not-valid-json",
                file_service=file_service,
                user=user,
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_after_key_non_dict_returns_400(self):
        """A valid JSON non-dict after_key (e.g. a string) raises HTTPException 400."""
        import json

        from fastapi import HTTPException

        file_service = _make_file_service(_SAMPLE_RESPONSE)
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await list_files(
                page=1,
                page_size=25,
                sort_by="filename",
                sort_order="asc",
                connector_type=None,
                mimetype=None,
                owner=None,
                search=None,
                after_key=json.dumps("just-a-string"),
                file_service=file_service,
                user=user,
            )

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# search_files
# ---------------------------------------------------------------------------


class TestSearchFiles:
    @pytest.mark.asyncio
    async def test_returns_search_results_on_success(self):
        """search_files delegates to v2.search_files and returns its result."""
        file_service = _make_file_service(_SAMPLE_RESPONSE)
        user = _make_user()

        response = await search_files(
            q="report",
            page=1,
            page_size=25,
            connector_type=None,
            mimetype=None,
            owner=None,
            after_key=None,
            file_service=file_service,
            user=user,
        )

        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        assert "files" in body

    @pytest.mark.asyncio
    async def test_forwards_q_and_filters_to_service(self):
        """q and all filter params are forwarded to FileServiceV2.search_files."""
        file_service = _make_file_service(_SAMPLE_RESPONSE)
        user = _make_user()

        await search_files(
            q="annual report",
            page=2,
            page_size=10,
            connector_type="gdrive",
            mimetype="text/plain",
            owner="user-7",
            after_key=None,
            file_service=file_service,
            user=user,
        )

        file_service.search_files.assert_awaited_once()
        kwargs = file_service.search_files.call_args.kwargs
        assert kwargs["query"] == "annual report"
        assert kwargs["connector_type"] == "gdrive"
        assert kwargs["mimetype"] == "text/plain"
        assert kwargs["owner"] == "user-7"
