from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api import files as internal_files
from api.v2 import files as v2_files
from services.file_service_v2 import FileServiceV2

USER = SimpleNamespace(user_id="u1", jwt_token="jwt")
AFTER = "2024-01-01T00:00:00Z"
BEFORE = "2024-01-31T23:59:59Z"


def _search_kwargs(**overrides):
    kwargs = {
        "q": "report",
        "page": 1,
        "page_size": 25,
        "connector_type": None,
        "mimetype": None,
        "owner": None,
        "after_key": None,
        "data_sources": None,
        "created_after": AFTER,
        "created_before": BEFORE,
        "user": USER,
    }
    kwargs.update(overrides)
    return kwargs


def _service():
    service = MagicMock()
    service.search_files = AsyncMock(return_value={"files": []})
    return service


@pytest.mark.asyncio
async def test_internal_search_forwards_date_bounds():
    service = _service()
    response = await internal_files.search_files(**_search_kwargs(file_service=service))
    assert response.status_code == 200
    kwargs = service.search_files.await_args.kwargs
    assert kwargs["created_after"] == AFTER
    assert kwargs["created_before"] == BEFORE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"created_after": BEFORE, "created_before": AFTER},
        {"created_after": "20240101"},
    ],
)
async def test_internal_search_rejects_bad_bounds(overrides):
    service = _service()
    with pytest.raises(HTTPException) as exc:
        await internal_files.search_files(**_search_kwargs(file_service=service, **overrides))
    assert exc.value.status_code == 422
    service.search_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_v2_search_forwards_date_bounds():
    service = _service()
    await v2_files.search_files(**_search_kwargs(file_service=service))
    kwargs = service.search_files.await_args.kwargs
    assert kwargs["created_after"] == AFTER
    assert kwargs["created_before"] == BEFORE


@pytest.mark.asyncio
async def test_service_search_passes_bounds_to_list_files():
    service = FileServiceV2(MagicMock())
    service.list_files = AsyncMock(return_value={"files": []})
    await service.search_files(
        user_id="u1", query="report", created_after=AFTER, created_before=BEFORE
    )
    kwargs = service.list_files.await_args.kwargs
    assert kwargs["created_after"] == AFTER
    assert kwargs["created_before"] == BEFORE


@pytest.mark.parametrize(
    "handler",
    [
        internal_files.list_files,
        internal_files.search_files,
        v2_files.list_files,
        v2_files.search_files,
    ],
)
def test_bounds_are_documented_as_inclusive(handler):
    defaults = handler.__defaults__ or ()
    descriptions = [getattr(d, "description", "") or "" for d in defaults]
    assert internal_files.CREATED_AFTER_DESCRIPTION in descriptions
    assert internal_files.CREATED_BEFORE_DESCRIPTION in descriptions
    assert "Inclusive" in internal_files.CREATED_BEFORE_DESCRIPTION
