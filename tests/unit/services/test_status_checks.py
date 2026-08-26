from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import services.component_logs as _cl
from api.schemas.status import ComponentState
from config.settings import clients
from services import status_checks
from services.status_checks import (
    check_docling,
    check_langflow,
    check_openrag_backend,
    check_opensearch,
)
from utils.version_utils import OPENRAG_VERSION

# OpenRAG backend check tests


@pytest.fixture
def config_ok(monkeypatch):
    monkeypatch.setattr(status_checks, "get_openrag_config", lambda: object(), raising=True)


@pytest.mark.asyncio
async def test_openrag_all_initialized_is_healthy(monkeypatch, config_ok):
    monkeypatch.setattr(clients, "opensearch", MagicMock(), raising=True)
    monkeypatch.setattr(clients, "langflow_http_client", MagicMock(), raising=True)
    monkeypatch.setattr(clients, "docling_http_client", MagicMock(), raising=True)

    r = await check_openrag_backend()

    assert r.name == "openrag"
    assert r.status == ComponentState.HEALTHY
    assert r.version == OPENRAG_VERSION


@pytest.mark.asyncio
async def test_openrag_missing_client_is_degraded(monkeypatch, config_ok):
    monkeypatch.setattr(clients, "opensearch", None, raising=False)
    monkeypatch.setattr(clients, "langflow_http_client", MagicMock(), raising=False)
    monkeypatch.setattr(clients, "docling_http_client", MagicMock(), raising=False)

    r = await check_openrag_backend()

    assert r.status == ComponentState.DEGRADED
    assert "opensearch" in (r.message or "").lower()


@pytest.mark.asyncio
async def test_openrag_config_not_loaded_is_unhealthy(monkeypatch):
    def _raise():
        raise RuntimeError("config not loaded")

    monkeypatch.setattr(status_checks, "get_openrag_config", _raise, raising=True)

    r = await check_openrag_backend()

    assert r.status == ComponentState.UNHEALTHY
    assert "configuration" in (r.message or "").lower()


@pytest.mark.asyncio
async def test_openrag_latency_is_measured(monkeypatch, config_ok):
    ticks = iter([1000.0, 1000.25])
    monkeypatch.setattr(status_checks, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(clients, "opensearch", MagicMock(), raising=False)
    monkeypatch.setattr(clients, "langflow_http_client", MagicMock(), raising=False)
    monkeypatch.setattr(clients, "docling_http_client", MagicMock(), raising=False)

    r = await check_openrag_backend()

    assert r.latency_ms == 250


# Docling check tests


def _mock_http(status_code=None, raises=None, json_data=None):
    c = MagicMock()
    if raises is not None:
        c.get = AsyncMock(side_effect=raises)
    else:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.json.return_value = (
            json_data
            if json_data is not None
            else {"docling-serve": "1.26.0", "version": "0.11.2rc0"}
        )
        c.get = AsyncMock(return_value=resp)
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="status_code,expected_status",
    argvalues=[
        (200, ComponentState.HEALTHY),
        (503, ComponentState.UNHEALTHY),
    ],
)
async def test_docling_correct_status(monkeypatch, status_code, expected_status):
    monkeypatch.setattr(clients, "docling_http_client", _mock_http(status_code), raising=False)

    r = await check_docling()

    assert r.name == "docling"
    assert r.status == expected_status
    assert r.required is True
    if expected_status == ComponentState.HEALTHY:
        assert r.version == "1.26.0"


@pytest.mark.asyncio
async def test_docling_unreachable_is_unhealthy(monkeypatch):
    monkeypatch.setattr(
        clients,
        "docling_http_client",
        _mock_http(raises=httpx.ConnectError("refused")),
        raising=False,
    )
    r = await check_docling()
    assert r.status == ComponentState.UNHEALTHY
    assert "unreachable" in (r.message or "").lower()
    assert r.version is None  # guards the unbound-variable regression on the failure path


# Langflow check tests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="status_code,expected_status",
    argvalues=[(200, ComponentState.HEALTHY), (500, ComponentState.UNHEALTHY)],
)
async def test_langflow_correct_status(monkeypatch, status_code, expected_status):
    monkeypatch.setattr(clients, "langflow_http_client", _mock_http(status_code), raising=False)
    r = await check_langflow()
    assert r.name == "langflow"
    assert r.status == expected_status
    if expected_status == ComponentState.HEALTHY:
        assert r.version == "0.11.2rc0"


@pytest.mark.asyncio
async def test_langflow_unreachable_is_unhealthy(monkeypatch):
    monkeypatch.setattr(
        clients,
        "langflow_http_client",
        _mock_http(raises=httpx.ConnectError("refused")),
        raising=False,
    )
    r = await check_langflow()
    assert r.status == ComponentState.UNHEALTHY
    assert "unreachable" in (r.message or "").lower()
    assert r.version is None


# OpenSearch Check tests


def _mock_os(health=None, raises=None):
    os = MagicMock()
    os.info = AsyncMock(return_value={"version": {"number": "3.2.0", "distribution": "opensearch"}})
    if raises is not None:
        os.cluster.health = AsyncMock(side_effect=raises)
    else:
        os.cluster.health = AsyncMock(return_value=health)
    return os


@pytest.mark.asyncio
@pytest.mark.parametrize(
    argnames="os_status,expected_status",
    argvalues=[
        ("green", ComponentState.HEALTHY),
        ("yellow", ComponentState.DEGRADED),
        ("red", ComponentState.UNHEALTHY),
    ],
)
async def test_opensearch_status_is_correct(monkeypatch, os_status, expected_status):
    monkeypatch.setattr(
        clients, "opensearch", _mock_os({"status": os_status, "cluster_name": "c"}), raising=False
    )

    r = await check_opensearch()

    assert r.name == "opensearch"
    assert r.status == expected_status
    assert r.version == "3.2.0"
    assert r.metadata.get("distribution") == "opensearch"


@pytest.mark.asyncio
async def test_opensearch_yellow_records_warning(monkeypatch):
    monkeypatch.setattr(
        clients,
        "opensearch",
        _mock_os({"status": "yellow", "cluster_name": "c"}),
        raising=False,
    )

    await check_opensearch()
    await check_opensearch()

    entries = _cl.get_entries("opensearch", 10)
    assert len(entries) == 1
    assert entries[0]["level"] == "warning"
    assert entries[0]["message"] == "Cluster Health is yellow"


@pytest.mark.asyncio
async def test_opensearch_unreachable_is_unhealthy(monkeypatch):
    monkeypatch.setattr(
        clients, "opensearch", _mock_os(raises=ConnectionError("down")), raising=False
    )
    r = await check_opensearch()
    assert r.status == ComponentState.UNHEALTHY
    assert "unreachable" in (r.message or "").lower()
    assert r.version is None


# ---------------------------------------------------------------------------
# Buffer recording assertions (added by #2178)
# ---------------------------------------------------------------------------
# Each block verifies that record_check_result() is called correctly by the
# check functions: errors always land in the buffer; healthy checks write once.


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
async def test_openrag_unhealthy_records_to_buffer(monkeypatch):
    def _raise():
        raise RuntimeError("config missing")

    monkeypatch.setattr(status_checks, "get_openrag_config", _raise, raising=True)

    r = await check_openrag_backend()

    assert r.status == ComponentState.UNHEALTHY
    entries = _cl.get_entries("openrag", 10)
    assert len(entries) >= 1
    assert entries[-1]["level"] == "error"
    assert entries[-1]["detail"] is not None
    assert "RuntimeError" in entries[-1]["detail"]


@pytest.mark.asyncio
async def test_openrag_degraded_records_to_buffer(monkeypatch):
    monkeypatch.setattr(status_checks, "get_openrag_config", lambda: object(), raising=True)
    monkeypatch.setattr(clients, "opensearch", None, raising=False)
    monkeypatch.setattr(clients, "langflow_http_client", MagicMock(), raising=False)
    monkeypatch.setattr(clients, "docling_http_client", MagicMock(), raising=False)

    r = await check_openrag_backend()

    assert r.status == ComponentState.DEGRADED
    entries = _cl.get_entries("openrag", 10)
    assert len(entries) >= 1
    assert entries[-1]["level"] == "warning"


@pytest.mark.asyncio
async def test_openrag_healthy_does_not_flood_buffer(monkeypatch):
    """Steady-state healthy should not write to the buffer on repeated calls."""
    monkeypatch.setattr(status_checks, "get_openrag_config", lambda: object(), raising=True)
    monkeypatch.setattr(clients, "opensearch", MagicMock(), raising=False)
    monkeypatch.setattr(clients, "langflow_http_client", MagicMock(), raising=False)
    monkeypatch.setattr(clients, "docling_http_client", MagicMock(), raising=False)

    await check_openrag_backend()
    await check_openrag_backend()
    await check_openrag_backend()

    entries = _cl.get_entries("openrag", 10)
    assert len(entries) == 1
    assert entries[0]["level"] == "info"


@pytest.mark.asyncio
async def test_docling_unreachable_records_detail_with_target_url(monkeypatch):
    monkeypatch.setattr(
        clients,
        "docling_http_client",
        _mock_http(raises=httpx.ConnectError("refused")),
        raising=False,
    )

    r = await check_docling()

    assert r.status == ComponentState.UNHEALTHY
    entries = _cl.get_entries("docling", 10)
    assert len(entries) >= 1
    e = entries[-1]
    assert e["level"] == "error"
    assert "ConnectError" in (e["detail"] or "")
    assert "target:" in (e["detail"] or "")


@pytest.mark.asyncio
async def test_docling_healthy_does_not_flood_buffer(monkeypatch):
    monkeypatch.setattr(clients, "docling_http_client", _mock_http(200), raising=False)

    await check_docling()
    await check_docling()

    entries = _cl.get_entries("docling", 10)
    assert len(entries) == 1
    assert entries[0]["level"] == "info"


@pytest.mark.asyncio
async def test_langflow_unreachable_records_detail_with_target_url(monkeypatch):
    monkeypatch.setattr(
        clients,
        "langflow_http_client",
        _mock_http(raises=httpx.ConnectError("refused")),
        raising=False,
    )

    r = await check_langflow()

    assert r.status == ComponentState.UNHEALTHY
    entries = _cl.get_entries("langflow", 10)
    assert len(entries) >= 1
    e = entries[-1]
    assert e["level"] == "error"
    assert "ConnectError" in (e["detail"] or "")
    assert "target:" in (e["detail"] or "")
    # last_error on the returned status should match detail prefix
    assert r.last_error is not None
    assert "ConnectError" in r.last_error


@pytest.mark.asyncio
async def test_opensearch_unreachable_records_to_buffer(monkeypatch):
    monkeypatch.setattr(
        clients, "opensearch", _mock_os(raises=ConnectionError("down")), raising=False
    )

    r = await check_opensearch()

    assert r.status == ComponentState.UNHEALTHY
    entries = _cl.get_entries("opensearch", 10)
    assert len(entries) >= 1
    assert entries[-1]["level"] == "error"
    assert "ConnectionError" in (entries[-1]["detail"] or "")
    assert r.last_error is not None


@pytest.mark.asyncio
async def test_opensearch_recovery_writes_info_entry(monkeypatch):
    """After a failure, a subsequent healthy check writes one 'recovered' info entry."""
    # First call: unhealthy
    monkeypatch.setattr(
        clients, "opensearch", _mock_os(raises=ConnectionError("down")), raising=False
    )
    await check_opensearch()

    # Second call: healthy
    monkeypatch.setattr(
        clients, "opensearch", _mock_os({"status": "green", "cluster_name": "c"}), raising=False
    )
    await check_opensearch()

    entries = _cl.get_entries("opensearch", 10)
    levels = [e["level"] for e in entries]
    assert "error" in levels
    assert "info" in levels
    info_entries = [e for e in entries if e["level"] == "info"]
    assert any("recovered" in e["message"] for e in info_entries)


@pytest.mark.asyncio
async def test_last_error_is_none_when_healthy(monkeypatch):
    """last_error on ComponentStatus must be None for a healthy check."""
    monkeypatch.setattr(clients, "docling_http_client", _mock_http(200), raising=False)
    r = await check_docling()
    assert r.status == ComponentState.HEALTHY
    assert r.last_error is None


@pytest.mark.asyncio
async def test_last_error_populated_on_failure(monkeypatch):
    monkeypatch.setattr(
        clients,
        "langflow_http_client",
        _mock_http(raises=httpx.ConnectError("refused")),
        raising=False,
    )
    r = await check_langflow()
    assert r.last_error is not None
    assert len(r.last_error) > 0
