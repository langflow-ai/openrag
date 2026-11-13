"""auth_me exposes the additive ``date_range_v2`` flag without changing other keys."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.auth import auth_me


async def _call():
    auth_service = MagicMock()
    auth_service.get_user_info = AsyncMock(return_value={"authenticated": False})
    response = await auth_me(
        request=MagicMock(),
        auth_service=auth_service,
        user=None,
        session=MagicMock(),
    )
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_date_range_v2_present_and_false_by_default(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.delenv("OPENRAG_DATE_RANGE_V2_ENABLED", raising=False)
    body = await _call()
    assert body["date_range_v2"] is False
    assert body["run_mode"] == "oss"
    assert "version" in body
    assert body["authenticated"] is False


@pytest.mark.asyncio
async def test_date_range_v2_true_when_flag_and_oss(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv("OPENRAG_DATE_RANGE_V2_ENABLED", "true")
    body = await _call()
    assert body["date_range_v2"] is True
    assert body["run_mode"] == "oss"


@pytest.mark.asyncio
async def test_date_range_v2_false_outside_oss(monkeypatch):
    monkeypatch.setenv("OPENRAG_RUN_MODE", "saas")
    monkeypatch.setenv("OPENRAG_DATE_RANGE_V2_ENABLED", "true")
    body = await _call()
    assert body["date_range_v2"] is False
    assert body["run_mode"] == "saas"
