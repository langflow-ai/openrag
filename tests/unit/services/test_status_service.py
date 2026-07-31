import asyncio
import pytest

from api.schemas.status import ComponentState, ComponentStatus
from services import status_service

def _result(name, status, required=True):
    return ComponentStatus(name=name, display_name=name.title(),
                           status=status, required=required)

@pytest.mark.asyncio
async def test_all_healthy_overall_healthy(monkeypatch):
    async def ok(name): 
        return _result(name, ComponentState.HEALTHY)
    monkeypatch.setattr(status_service, "CHECK_SPECS", [
        lambda: ok("openrag"),
        lambda: ok("opensearch"),
    ], raising=True)

    result = await status_service.aggregate_status()
    assert result.overall_status == ComponentState.HEALTHY
    assert len(result.components) == 2
    assert isinstance(result.components[0], ComponentStatus)
    assert result.checked_at


@pytest.mark.asyncio
async def test_worst_wins(monkeypatch):
    async def healthy(): 
        return _result("openrag", ComponentState.HEALTHY)
    async def unhealthy(): 
        return _result("opensearch", ComponentState.UNHEALTHY)
    monkeypatch.setattr(status_service, "CHECK_SPECS", [healthy, unhealthy], raising=True)

    result = await status_service.aggregate_status()
    assert result.overall_status == ComponentState.UNHEALTHY


@pytest.mark.asyncio
async def test_timeout_becomes_unknown_and_does_not_block(monkeypatch):
    async def slow():
        await asyncio.sleep(5)
        return _result("docling", ComponentState.HEALTHY)
    async def fast():
        return _result("openrag", ComponentState.HEALTHY)
    
    monkeypatch.setattr(status_service, "CHECK_TIMEOUT_S", 0.05, raising=True)
    monkeypatch.setattr(status_service, "CHECK_SPECS", [fast, slow], raising=True)

    result = await status_service.aggregate_status()

    assert len(result.components) == 2
    unknown = [c for c in result.components if c.status == ComponentState.UNKNOWN]
    assert len(unknown) == 1, [(c.name, c.status) for c in result.components]

    assert result.overall_status == ComponentState.UNHEALTHY


@pytest.mark.asyncio
async def test_check_exception_becomes_unknown(monkeypatch):
    async def healthy(): 
        return _result("openrag", ComponentState.HEALTHY)
    async def boom(): 
        raise RuntimeError("x")
    
    monkeypatch.setattr(status_service, "CHECK_SPECS", [healthy, boom], raising=True)

    result = await status_service.aggregate_status()

    assert result.overall_status == ComponentState.UNHEALTHY