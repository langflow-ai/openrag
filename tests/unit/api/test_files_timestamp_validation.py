from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.files import _validate_date_range, _validate_iso_timestamp
from api.search import SearchBody
from api.search import search as search_endpoint
from api.v2.files import list_files as v2_list_files


@pytest.mark.parametrize(
    "value",
    [
        None,
        "2024-01-01",
        "2024-01-01T00:00",
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00.000Z",
        "2024-01-31T23:59:59.999+05:30",
    ],
)
def test_accepts_extended_iso_forms(value):
    _validate_iso_timestamp(value, "created_after")


@pytest.mark.parametrize(
    "value",
    [
        "20240101",
        "20240101T000000",
        "2024-01-01T000000",
        "2024-13-01",
        "not-a-date",
        "",
    ],
)
def test_rejects_basic_and_invalid_forms(value):
    with pytest.raises(HTTPException) as exc:
        _validate_iso_timestamp(value, "created_after")
    assert exc.value.status_code == 422
    assert "created_after" in exc.value.detail


@pytest.mark.parametrize(
    ("created_after", "created_before"),
    [
        (None, None),
        ("2024-01-01", None),
        (None, "2024-01-31"),
        ("2024-01-01", "2024-01-31"),
        ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
        # 09:00 at +05:30 is 03:30 UTC, which is before 04:00 UTC.
        ("2024-01-01T09:00:00+05:30", "2024-01-01T04:00:00Z"),
        # An offset-less bound is read as UTC, so it compares against an aware one.
        ("2024-01-01T00:00:00", "2024-01-01T00:00:00Z"),
    ],
)
def test_accepts_ordered_ranges(created_after, created_before):
    _validate_date_range(created_after, created_before)


@pytest.mark.parametrize(
    ("created_after", "created_before"),
    [
        ("2024-02-01", "2024-01-01"),
        ("2024-01-01T00:00:01Z", "2024-01-01T00:00:00Z"),
        # 05:00 UTC is after 09:00 at +05:30 (03:30 UTC).
        ("2024-01-01T05:00:00Z", "2024-01-01T09:00:00+05:30"),
    ],
)
def test_rejects_inverted_ranges(created_after, created_before):
    with pytest.raises(HTTPException) as exc:
        _validate_date_range(created_after, created_before)
    assert exc.value.status_code == 422
    assert "created_after must be earlier" in exc.value.detail


@pytest.mark.parametrize(
    ("created_after", "created_before", "bad_param"),
    [
        ("20240101", None, "created_after"),
        (None, "nope", "created_before"),
    ],
)
def test_range_rejects_malformed_bound(created_after, created_before, bad_param):
    with pytest.raises(HTTPException) as exc:
        _validate_date_range(created_after, created_before)
    assert exc.value.status_code == 422
    assert bad_param in exc.value.detail


def _call_v2_list_files(file_service, **overrides):
    params = {
        "page": 1,
        "page_size": 25,
        "sort_by": "filename",
        "sort_order": "asc",
        "connector_type": None,
        "mimetype": None,
        "owner": None,
        "search": None,
        "after_key": None,
        "data_sources": None,
        "created_after": None,
        "created_before": None,
        **overrides,
    }
    user = SimpleNamespace(user_id="user-1", jwt_token="jwt")
    return v2_list_files(**params, file_service=file_service, user=user)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"created_after": "not-a-date"},
        {"created_before": "20240101"},
        {"created_after": "2024-02-01", "created_before": "2024-01-01"},
    ],
)
async def test_v2_list_files_rejects_invalid_dates_before_querying(overrides):
    file_service = SimpleNamespace(list_files=AsyncMock())
    with pytest.raises(HTTPException) as exc:
        await _call_v2_list_files(file_service, **overrides)
    assert exc.value.status_code == 422
    file_service.list_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_v2_list_files_passes_valid_range_through():
    file_service = SimpleNamespace(list_files=AsyncMock(return_value={"files": []}))
    await _call_v2_list_files(file_service, created_after="2024-01-01", created_before="2024-01-31")
    kwargs = file_service.list_files.await_args.kwargs
    assert kwargs["created_after"] == "2024-01-01"
    assert kwargs["created_before"] == "2024-01-31"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"query": "q", "created_after": "2024-02-01", "created_before": "2024-01-01"},
        # Bounds smuggled through `filters` are validated too.
        {"query": "q", "filters": {"created_after": "garbage"}},
        {
            "query": "q",
            "filters": {"created_after": "2024-02-01"},
            "created_before": "2024-01-01",
        },
    ],
)
async def test_search_rejects_invalid_date_bounds(body):
    search_service = SimpleNamespace(search=AsyncMock())
    user = SimpleNamespace(user_id="user-1", jwt_token="jwt")
    with pytest.raises(HTTPException) as exc:
        await search_endpoint(
            SearchBody(**body),
            search_service=search_service,
            session_manager=None,
            user=user,
        )
    assert exc.value.status_code == 422
    search_service.search.assert_not_awaited()
