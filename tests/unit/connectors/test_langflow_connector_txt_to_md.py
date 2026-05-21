"""Regression guard for SharePoint .txt ingestion via the Langflow connector
path.

Background: Langflow's docling component fails on text/plain. The
user-upload path already applies a .txt -> .md rename (commit f6b9fe0).
This test pins that the connector path
(`LangflowConnectorService.process_connector_document`) applies the same
rule, so a SharePoint .txt reaches Langflow as .md / text/markdown — not
the unhandled text/plain shape that previously broke ingestion.

This test drives the production code path; if the rename is ever removed
or shorted around, the assertions will catch it.
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _make_service():
    """Build a LangflowConnectorService with the surface
    process_connector_document touches stubbed:
    - session_manager (only needed if pre-delete fires; we let it run as
      a no-op against a mocked OpenSearch client).
    - langflow_service.upload_user_file / run_ingestion_flow / delete_user_file.
    """
    from connectors.langflow_connector_service import LangflowConnectorService

    service = LangflowConnectorService.__new__(LangflowConnectorService)

    # OpenSearch mock for the pre-delete step (collect+delete). Empty result
    # so the pre-delete is a no-op; the test isn't about that path.
    opensearch_client = AsyncMock()
    opensearch_client.search = AsyncMock(return_value={"_scroll_id": None, "hits": {"hits": []}})
    opensearch_client.delete = AsyncMock(return_value={"result": "deleted"})

    session_manager = MagicMock()
    session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)

    service.session_manager = session_manager
    service.docling_service = MagicMock()
    service.connection_manager = MagicMock()

    # Mock Langflow service — the surface we're asserting against is its
    # upload_user_file (the file_tuple it receives).
    langflow_service = MagicMock()
    langflow_service.upload_user_file = AsyncMock(
        return_value={"id": "lf-file-id", "path": "/lf/path/file"}
    )
    langflow_service.run_ingestion_flow = AsyncMock(return_value={"status": "ok"})
    langflow_service.delete_user_file = AsyncMock()
    service.langflow_service = langflow_service

    return service, langflow_service


def _make_document(filename: str, mimetype: str, content: bytes = b"hello world"):
    from connectors.base import ConnectorDocument, DocumentACL

    return ConnectorDocument(
        id="graph-item-id-stable",
        filename=filename,
        mimetype=mimetype,
        content=content,
        source_url="https://contoso.sharepoint.com/.../notes.txt",
        acl=DocumentACL(owner="alice"),
        modified_time=datetime(2026, 5, 21),
        created_time=datetime(2026, 5, 1),
        metadata={"site": "marketing"},
    )


@pytest.mark.asyncio
async def test_sharepoint_txt_is_uploaded_to_langflow_as_md():
    """A connector document with mimetype text/plain must reach Langflow's
    upload_user_file with a .md filename and text/markdown mimetype."""
    service, langflow_service = _make_service()
    document = _make_document(filename="notes.txt", mimetype="text/plain")

    # auto_cleanup_tempfile is a context manager that yields a real path;
    # let it run normally — it just creates a temp file we won't use.
    await service.process_connector_document(
        document=document,
        owner_user_id="alice",
        connector_type="sharepoint",
        jwt_token="jwt",
    )

    langflow_service.upload_user_file.assert_awaited_once()
    (file_tuple, _jwt) = langflow_service.upload_user_file.await_args.args
    filename, content, mimetype = file_tuple

    assert filename.endswith(".md"), (
        f"SharePoint .txt must reach Langflow as .md; got {filename!r}. "
        "Langflow's docling component fails on text/plain — see "
        "langflow_safe_filename_and_mimetype."
    )
    assert mimetype == "text/markdown", (
        f"SharePoint .txt must reach Langflow as text/markdown; got {mimetype!r}."
    )
    # Content bytes are unchanged by the rename.
    assert content == document.content


@pytest.mark.asyncio
async def test_sharepoint_pdf_passes_through_untouched():
    """The rename rule must NOT touch non-.txt files."""
    service, langflow_service = _make_service()
    document = _make_document(
        filename="report.pdf", mimetype="application/pdf", content=b"%PDF-1.4..."
    )

    await service.process_connector_document(
        document=document,
        owner_user_id="alice",
        connector_type="sharepoint",
        jwt_token="jwt",
    )

    (file_tuple, _jwt) = langflow_service.upload_user_file.await_args.args
    filename, _content, mimetype = file_tuple
    assert filename == "report.pdf"
    assert mimetype == "application/pdf"
