"""VULN-13906: run_url_ingestion_flow must reject disallowed hosts before touching Langflow."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.langflow_file_service import LangflowFileService  # noqa: E402
from utils.ssrf_guard import SSRFBlockedError  # noqa: E402


@pytest.mark.asyncio
async def test_run_url_ingestion_flow_rejects_disallowed_host(monkeypatch):
    monkeypatch.setattr("utils.ssrf_guard.OPENRAG_URL_INGEST_ALLOWED_HOSTS", {"good.example.com"})

    service = LangflowFileService()
    service._ensure_url_ingest_flow_id = AsyncMock(
        side_effect=AssertionError("should not be reached: allowlist check must run first")
    )

    with pytest.raises(SSRFBlockedError):
        await service.run_url_ingestion_flow(
            docs_url="https://attacker.example/canary",
            crawl_depth=1,
        )

    service._ensure_url_ingest_flow_id.assert_not_called()


@pytest.mark.asyncio
async def test_run_url_ingestion_flow_rejects_private_ip_even_if_host_allowlisted(monkeypatch):
    monkeypatch.setattr("utils.ssrf_guard.OPENRAG_URL_INGEST_ALLOWED_HOSTS", {"localhost"})

    service = LangflowFileService()
    service._ensure_url_ingest_flow_id = AsyncMock(
        side_effect=AssertionError("should not be reached: IP-safety check must run first")
    )

    with pytest.raises(SSRFBlockedError):
        await service.run_url_ingestion_flow(
            docs_url="http://localhost:9200/",
            crawl_depth=1,
        )

    service._ensure_url_ingest_flow_id.assert_not_called()


@pytest.mark.asyncio
async def test_run_url_ingestion_flow_proceeds_for_allowlisted_public_host(monkeypatch):
    monkeypatch.setattr("utils.ssrf_guard.OPENRAG_URL_INGEST_ALLOWED_HOSTS", {"docs.example.com"})

    def fake_getaddrinfo(host, port):
        return [(None, None, None, None, ("8.8.8.8", 0))]

    monkeypatch.setattr("utils.ssrf_guard.socket.getaddrinfo", fake_getaddrinfo)

    service = LangflowFileService()
    service._ensure_url_ingest_flow_id = AsyncMock(
        side_effect=RuntimeError("stop here — past the allowlist check, rest of the flow is out of scope")
    )

    with pytest.raises(RuntimeError, match="stop here"):
        await service.run_url_ingestion_flow(
            docs_url="https://docs.example.com/report",
            crawl_depth=1,
        )

    service._ensure_url_ingest_flow_id.assert_called_once()
