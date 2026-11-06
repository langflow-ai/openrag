import json

import pytest

from api.knowledge_filter import normalize_query_data
from api.v1._filter_resolution import _strip_wildcards

AFTER = "2026-10-07T07:00:00Z"
BEFORE = "2026-10-11T06:59:59.999Z"
CONTEXT = {"from": "2026-10-07", "to": "2026-10-10", "timezone": "America/Los_Angeles"}


def _norm(data):
    return json.loads(normalize_query_data(data))


def test_filter_without_dates_stays_unrestricted():
    out = _norm({"filters": {"document_types": ["application/pdf"]}})
    assert "created_after" not in out["filters"]
    assert "created_before" not in out["filters"]
    assert "date_range_context" not in out


def test_dates_and_context_round_trip_with_context_outside_filters():
    out = _norm(
        {
            "filters": {"created_after": AFTER, "created_before": BEFORE},
            "date_range_context": CONTEXT,
        }
    )
    assert out["filters"]["created_after"] == AFTER
    assert out["filters"]["created_before"] == BEFORE
    assert out["date_range_context"] == CONTEXT
    assert "date_range_context" not in out["filters"]
    # Idempotent through a second save
    assert _norm(out) == out


def test_context_dropped_when_no_bounds():
    assert "date_range_context" not in _norm({"date_range_context": CONTEXT})


@pytest.mark.parametrize(
    "filters",
    [
        {"created_after": 123},
        {"created_before": ["2026-10-07"]},
        {"created_after": "not-a-date"},
        {"created_after": BEFORE, "created_before": AFTER},
    ],
)
def test_invalid_bounds_rejected(filters):
    with pytest.raises(ValueError):
        normalize_query_data({"filters": filters})


@pytest.mark.parametrize(
    "context",
    [
        "x",
        {"from": "2026-13-01"},
        {"from": 5},
        {"from": "2026-10-10", "to": "2026-10-07"},
        {"timezone": "Not/AZone"},
        {"timezone": 7},
    ],
)
def test_invalid_context_rejected(context):
    with pytest.raises(ValueError):
        normalize_query_data({"filters": {"created_after": AFTER}, "date_range_context": context})


def test_v1_resolution_keeps_date_bounds():
    out = _strip_wildcards(
        {
            "document_types": ["application/pdf"],
            "owners": ["*"],
            "created_after": AFTER,
            "created_before": BEFORE,
        }
    )
    assert out == {
        "document_types": ["application/pdf"],
        "created_after": AFTER,
        "created_before": BEFORE,
    }
    assert _strip_wildcards({"created_after": 5}) == {}


def test_unpadded_calendar_days_rejected():
    # "2026-2-9" would string-compare as later than "2026-10-10".
    for context in (
        {"from": "2026-10-10", "to": "2026-2-9"},
        {"from": "2026-2-9"},
        {"to": "2026-10-1"},
    ):
        with pytest.raises(ValueError):
            normalize_query_data(
                {"filters": {"created_after": AFTER}, "date_range_context": context}
            )


@pytest.mark.asyncio
async def test_rejected_update_neither_deletes_nor_recreates():
    from unittest.mock import AsyncMock, MagicMock

    from api.knowledge_filter import UpdateFilterBody, update_knowledge_filter

    service = MagicMock()
    service.get_knowledge_filter = AsyncMock(
        return_value={
            "success": True,
            "filter": {
                "id": "f1",
                "name": "n",
                "description": "",
                "query_data": "{}",
                "owner": "u",
            },
        }
    )
    service.delete_knowledge_filter = AsyncMock()
    service.create_knowledge_filter = AsyncMock()
    user = MagicMock(user_id="u", jwt_token="t")

    response = await update_knowledge_filter(
        "f1",
        UpdateFilterBody(queryData={"filters": {"created_after": 123}}),
        knowledge_filter_service=service,
        session_manager=MagicMock(),
        user=user,
    )

    assert response.status_code == 400
    service.delete_knowledge_filter.assert_not_called()
    service.create_knowledge_filter.assert_not_called()
