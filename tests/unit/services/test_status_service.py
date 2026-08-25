import asyncio

import pytest

import services.component_logs as _cl
from api.schemas.status import ComponentState, ComponentStatus
from services import status_service


def _result(name, status, required=True):
    return ComponentStatus(name=name, display_name=name.title(), status=status, required=required)


@pytest.mark.asyncio
async def test_all_healthy_overall_healthy(monkeypatch):
    async def ok(name):
        return _result(name, ComponentState.HEALTHY)

    monkeypatch.setattr(
        status_service,
        "CHECK_SPECS",
        [
            lambda: ok("openrag"),
            lambda: ok("opensearch"),
        ],
        raising=True,
    )

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

    assert result.overall_status == ComponentState.UNKNOWN


@pytest.mark.asyncio
async def test_check_exception_becomes_unknown(monkeypatch):
    async def healthy():
        return _result("openrag", ComponentState.HEALTHY)

    async def boom():
        raise RuntimeError("x")

    monkeypatch.setattr(status_service, "CHECK_SPECS", [healthy, boom], raising=True)

    result = await status_service.aggregate_status()

    assert result.overall_status == ComponentState.UNKNOWN


# ---------------------------------------------------------------------------
# Buffer recording assertions for _run_check (added by #2178)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_log_buffer():
    _cl._buffers.clear()
    _cl._locks.clear()
    _cl._last_state.clear()
    yield
    _cl._buffers.clear()
    _cl._locks.clear()
    _cl._last_state.clear()


@pytest.mark.asyncio
async def test_timeout_records_error_to_buffer(monkeypatch):
    """A timed-out check must write an error entry to the component buffer."""

    async def slow():
        await asyncio.sleep(5)
        return _result("docling", ComponentState.HEALTHY)

    monkeypatch.setattr(status_service, "CHECK_TIMEOUT_S", 0.05, raising=True)
    monkeypatch.setattr(status_service, "CHECK_SPECS", [slow], raising=True)

    result = await status_service.aggregate_status()

    assert result.components[0].status == ComponentState.UNKNOWN
    # _run_check names the component from the function name: "slow" → but we
    # patch the name via fn.__name__. Use the actual function name here.
    entries = _cl.get_entries("slow", tail=10)
    assert len(entries) >= 1
    assert entries[-1]["level"] == "error"
    assert (
        "timeout" in entries[-1]["message"].lower() or "timed out" in entries[-1]["message"].lower()
    )
    assert result.components[0].last_error is not None


@pytest.mark.asyncio
async def test_check_exception_records_error_to_buffer(monkeypatch):
    """An unexpected exception must write an error entry to the component buffer."""

    async def boom():
        raise ValueError("unexpected")

    monkeypatch.setattr(status_service, "CHECK_SPECS", [boom], raising=True)

    result = await status_service.aggregate_status()

    assert result.components[0].status == ComponentState.UNKNOWN
    entries = _cl.get_entries("boom", tail=10)
    assert len(entries) >= 1
    assert entries[-1]["level"] == "error"
    assert "ValueError" in (entries[-1]["detail"] or "")
    assert result.components[0].last_error is not None
    assert "ValueError" in result.components[0].last_error
