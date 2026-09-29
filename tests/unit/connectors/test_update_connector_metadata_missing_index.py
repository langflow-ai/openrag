"""_update_connector_metadata must not fail a connector file when the target
index is missing.

The document chunks are already indexed by the time enrichment runs; writing
source_url / timestamps / ACL onto them is best-effort and is retried on the
next sync. A transient or residual index-name mismatch (issue 81583) should
degrade to "file OK, warning logged", not a FAILED task.

Mirrors the tolerance already in get_synced_file_ids_for_connector
(connectors.py) and should_update_acl (acl_utils.py).
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from opensearchpy.exceptions import NotFoundError, RequestError

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_service():
    from connectors.service import ConnectorService

    service = ConnectorService.__new__(ConnectorService)
    service.session_manager = MagicMock()
    service.index_name = "orag-documents"

    opensearch_client = AsyncMock()
    service.session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    service.clients = MagicMock()
    service.clients.opensearch = opensearch_client
    return service, opensearch_client


def _make_document():
    from connectors.base import ConnectorDocument, DocumentACL

    return ConnectorDocument(
        id="stable-connector-id",
        filename="report.pdf",
        mimetype="application/pdf",
        content=b"",
        source_url="https://example.com/report.pdf",
        acl=DocumentACL(owner="alice"),
        modified_time=datetime(2026, 5, 7),
        created_time=datetime(2026, 5, 1),
        metadata={},
    )


@pytest.fixture
def _noop_acl(monkeypatch):
    async def _acl(**_kwargs):
        return {"status": "unchanged"}

    monkeypatch.setattr("utils.acl_utils.update_document_acl", _acl)


@pytest.mark.asyncio
async def test_missing_index_does_not_raise(_noop_acl, monkeypatch):
    service, opensearch_client = _make_service()
    opensearch_client.update_by_query.side_effect = NotFoundError(
        404, "index_not_found_exception", "no such index [documents]"
    )

    import connectors.service as service_module

    logger_mock = MagicMock()
    monkeypatch.setattr(service_module, "logger", logger_mock)

    # Must return normally rather than propagate — the caller marks the file
    # FAILED on any exception here.
    await service._update_connector_metadata(
        _make_document(), owner_user_id="alice", connector_type="ibm_cos"
    )

    # The missing index is swallowed with a warning, not an error.
    logger_mock.error.assert_not_called()
    logger_mock.warning.assert_called_once()
    _, warning_kwargs = logger_mock.warning.call_args
    assert warning_kwargs["document_id"] == "stable-connector-id"
    assert "index_not_found_exception" in warning_kwargs["error"]


@pytest.mark.asyncio
async def test_other_opensearch_errors_still_raise(_noop_acl):
    service, opensearch_client = _make_service()
    opensearch_client.update_by_query.side_effect = RequestError(
        400, "mapper_parsing_exception", "bad script"
    )

    with pytest.raises(RequestError):
        await service._update_connector_metadata(
            _make_document(), owner_user_id="alice", connector_type="ibm_cos"
        )


@pytest.mark.asyncio
async def test_non_index_error_mentioning_token_still_raises(_noop_acl):
    """A non-index failure whose message merely contains the
    'index_not_found_exception' token must not be swallowed — only a real
    404 NotFoundError with that structured error type is best-effort."""
    service, opensearch_client = _make_service()
    opensearch_client.update_by_query.side_effect = RequestError(
        400,
        "search_phase_execution_exception",
        "shard failure caused by index_not_found_exception downstream",
    )

    with pytest.raises(RequestError):
        await service._update_connector_metadata(
            _make_document(), owner_user_id="alice", connector_type="ibm_cos"
        )
