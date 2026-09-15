import asyncio
from unittest.mock import AsyncMock

import pytest

from app import lifespan
from services.conversation_persistence_service import conversation_persistence


@pytest.mark.asyncio
async def test_periodic_conversation_pruning_runs_immediately(monkeypatch):
    prune = AsyncMock(return_value=3)
    monkeypatch.setattr(conversation_persistence, "prune_stale_conversations", prune)

    # Mock the retention service
    retention_service = AsyncMock()
    retention_service.is_pruning_enabled = AsyncMock(return_value=True)

    monkeypatch.setattr(lifespan, "OPENRAG_CONVERSATION_TTL_DAYS", 90)
    monkeypatch.setattr(lifespan.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

    await lifespan._periodic_conversation_pruning(retention_service)

    prune.assert_awaited_once_with(90)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ttl_days", "setting_enabled"),
    [(0, True), (90, False)],
)
async def test_periodic_conversation_pruning_honors_opt_out(monkeypatch, ttl_days, setting_enabled):
    prune = AsyncMock()
    monkeypatch.setattr(conversation_persistence, "prune_stale_conversations", prune)

    # Mock the retention service
    retention_service = AsyncMock()
    retention_service.is_pruning_enabled = AsyncMock(return_value=setting_enabled)

    monkeypatch.setattr(lifespan, "OPENRAG_CONVERSATION_TTL_DAYS", ttl_days)
    monkeypatch.setattr(lifespan.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

    await lifespan._periodic_conversation_pruning(retention_service)

    prune.assert_not_awaited()
