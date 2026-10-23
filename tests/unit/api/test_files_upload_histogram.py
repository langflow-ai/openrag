from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.files import upload_histogram
from services.file_service_v2 import FileServiceV2

USER = SimpleNamespace(user_id="u1", jwt_token="jwt")


def _call(file_service, **overrides):
    params = {
        "start": "2024-05-01T00:00:00Z",
        "end": "2024-06-20T23:59:59Z",
        "tz": "America/New_York",
        "connector_type": None,
        "mimetype": None,
        "owner": None,
        "data_sources": None,
        "file_service": file_service,
        "user": USER,
    }
    params.update(overrides)
    return upload_histogram(**params)


@pytest.mark.asyncio
async def test_passes_window_timezone_and_filters_to_service():
    service = MagicMock()
    service.upload_histogram = AsyncMock(return_value={"total": 2, "days": {"2024-06-01": 2}})

    response = await _call(service, owner=["u1"])

    assert response.status_code == 200
    kwargs = service.upload_histogram.await_args.kwargs
    assert kwargs["time_zone"] == "America/New_York"
    assert kwargs["start"] == "2024-05-01T00:00:00Z"
    assert kwargs["owner"] == ["u1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"start": "20240501"},
        {"end": "not-a-date"},
        {"start": "2024-07-01T00:00:00Z"},
        {"tz": "Mars/Olympus_Mons"},
    ],
)
async def test_rejects_bad_input(overrides):
    service = MagicMock()
    service.upload_histogram = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await _call(service, **overrides)
    assert exc.value.status_code == 422
    service.upload_histogram.assert_not_awaited()


@pytest.mark.asyncio
async def test_returns_500_when_service_fails():
    service = MagicMock()
    service.upload_histogram = AsyncMock(side_effect=RuntimeError("down"))
    response = await _call(service)
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_service_buckets_by_local_day_and_keeps_all_time_total():
    client = MagicMock()
    client.search = AsyncMock(
        return_value={
            "aggregations": {
                "total": {"value": 7},
                "window": {
                    "days": {
                        "buckets": [
                            {"key_as_string": "2024-06-01", "files": {"value": 2}},
                            {"key_as_string": "2024-06-03", "files": {"value": 5}},
                        ]
                    }
                },
            }
        }
    )
    session_manager = MagicMock()
    session_manager.get_user_opensearch_client.return_value = client

    result = await FileServiceV2(session_manager).upload_histogram(
        user_id="u1",
        start="2024-05-01T00:00:00Z",
        end="2024-06-20T23:59:59Z",
        time_zone="Asia/Kolkata",
        connector_type=["local"],
    )

    assert result == {"total": 7, "days": {"2024-06-01": 2, "2024-06-03": 5}}
    body = client.search.await_args.kwargs["body"]
    # The date window narrows only the histogram, never the all-time total.
    assert "range" not in str(body["query"])
    assert {"term": {"connector_type": "local"}} in body["query"]["bool"]["filter"]
    window = body["aggs"]["window"]
    assert window["filter"] == {
        "range": {"indexed_time": {"gte": "2024-05-01T00:00:00Z", "lte": "2024-06-20T23:59:59Z"}}
    }
    histogram = window["aggs"]["days"]["date_histogram"]
    assert histogram["time_zone"] == "Asia/Kolkata"
    assert histogram["calendar_interval"] == "day"
