"""Unit tests for GET /v1/status/{component}/logs endpoint handler.

Tests call the endpoint function directly (not via a full TestClient stack)
to stay consistent with the other unit/api tests in this directory.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import services.component_logs as cl  # noqa: E402
from api.schemas.status import LogsResponse  # noqa: E402
from api.v1.status import get_component_logs_endpoint  # noqa: E402
from session_manager import User  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user():
    return MagicMock(spec=User)


@pytest.fixture(autouse=True)
def _reset_buffer():
    cl._buffers.clear()
    cl._locks.clear()
    cl._last_state.clear()
    yield
    cl._buffers.clear()
    cl._locks.clear()
    cl._last_state.clear()


# ---------------------------------------------------------------------------
# 404 — unknown component
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_component_raises_404():
    with pytest.raises(HTTPException) as exc_info:
        await get_component_logs_endpoint(component="foobar", tail=50, user=_user())

    assert exc_info.value.status_code == 404
    assert "foobar" in exc_info.value.detail
    assert "Valid names" in exc_info.value.detail


@pytest.mark.asyncio
async def test_404_detail_lists_all_known_names():
    with pytest.raises(HTTPException) as exc_info:
        await get_component_logs_endpoint(component="unknown", tail=50, user=_user())

    detail = exc_info.value.detail
    for name in ("docling", "langflow", "bomarag", "opensearch"):
        assert name in detail


# ---------------------------------------------------------------------------
# 200 — known components from buffer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_component_returns_200_shape():
    cl.record("opensearch", "error", "cluster red", detail="status=red")

    result = await get_component_logs_endpoint(component="opensearch", tail=50, user=_user())

    assert isinstance(result, LogsResponse)
    assert result.component == "opensearch"
    assert result.count == 1
    assert len(result.entries) == 1
    e = result.entries[0]
    assert e.level == "error"
    assert e.message == "cluster red"
    assert e.detail == "status=red"


@pytest.mark.asyncio
async def test_empty_buffer_returns_zero_count():
    result = await get_component_logs_endpoint(component="docling", tail=50, user=_user())

    assert result.component == "docling"
    assert result.count == 0
    assert result.entries == []


@pytest.mark.asyncio
async def test_tail_parameter_limits_entries():
    for i in range(20):
        cl.record("bomarag", "warning", f"msg-{i}")

    result = await get_component_logs_endpoint(component="bomarag", tail=5, user=_user())

    assert result.count == 5
    assert len(result.entries) == 5
    # Should be most recent 5
    assert result.entries[-1].message == "msg-19"
    assert result.entries[0].message == "msg-15"


@pytest.mark.asyncio
async def test_entries_are_oldest_to_newest():
    for i in range(3):
        cl.record("docling", "error", f"err-{i}")

    result = await get_component_logs_endpoint(component="docling", tail=10, user=_user())

    messages = [e.message for e in result.entries]
    assert messages == ["err-0", "err-1", "err-2"]


@pytest.mark.asyncio
async def test_count_matches_entries_length():
    cl.record("opensearch", "error", "a")
    cl.record("opensearch", "error", "b")
    cl.record("opensearch", "error", "c")

    result = await get_component_logs_endpoint(component="opensearch", tail=100, user=_user())

    assert result.count == len(result.entries) == 3


# ---------------------------------------------------------------------------
# Response schema validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_entry_detail_can_be_none():
    cl.record("bomarag", "warning", "no detail")

    result = await get_component_logs_endpoint(component="bomarag", tail=10, user=_user())

    assert result.entries[0].detail is None


@pytest.mark.asyncio
async def test_langflow_uses_buffer_like_all_other_components():
    """Langflow now goes through the same buffer path as every other component."""
    cl.record("langflow", "error", "langflow-down", detail="ConnectError")

    result = await get_component_logs_endpoint(component="langflow", tail=50, user=_user())

    assert result.component == "langflow"
    assert result.count == 1
    assert result.entries[0].message == "langflow-down"


@pytest.mark.asyncio
async def test_all_known_components_return_200():
    """All four known components must not raise, even with empty buffers."""
    for name in ("bomarag", "langflow", "docling", "opensearch"):
        result = await get_component_logs_endpoint(component=name, tail=10, user=_user())
        assert result.component == name
        assert isinstance(result.entries, list)
