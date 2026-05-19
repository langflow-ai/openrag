"""Connector rename fix: _update_connector_metadata must rewrite the indexed
`filename` field so renamed source files don't leave their old name in
OpenSearch chunks.

Pins the painless script extension in src/connectors/service.py
`_update_connector_metadata`.
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
    """Build a ConnectorService whose only wired-up surface is what
    _update_connector_metadata touches: an opensearch client (via
    session_manager) and an index_name."""
    from connectors.service import ConnectorService

    service = ConnectorService.__new__(ConnectorService)
    service.session_manager = MagicMock()
    service.index_name = "test-index"

    opensearch_client = AsyncMock()
    service.session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    return service, opensearch_client


def _make_document(filename: str = "renamed.pdf"):
    from connectors.base import ConnectorDocument, DocumentACL

    return ConnectorDocument(
        id="graph-item-id-stable",
        filename=filename,
        mimetype="application/pdf",
        content=b"",
        source_url="https://contoso.sharepoint.com/.../renamed.pdf",
        acl=DocumentACL(owner="alice"),
        modified_time=datetime(2026, 5, 7),
        created_time=datetime(2026, 5, 1),
        metadata={"site": "marketing"},
    )


@pytest.mark.asyncio
async def test_update_includes_filename_in_script_and_params(monkeypatch):
    """The painless script must reference params.filename, and params must
    carry document.filename as-is."""
    service, opensearch_client = _make_service()

    # update_document_acl is invoked first; stub it to a no-op so the test
    # focuses on the metadata update_by_query.
    async def _noop_acl(**_kwargs):
        return {"status": "unchanged"}

    monkeypatch.setattr("utils.acl_utils.update_document_acl", _noop_acl)

    document = _make_document(filename="Report-FY26.docx")
    await service._update_connector_metadata(
        document, owner_user_id="alice", connector_type="sharepoint"
    )

    opensearch_client.update_by_query.assert_awaited_once()
    call = opensearch_client.update_by_query.await_args
    body = call.kwargs["body"]
    script = body["script"]
    params = script["params"]

    assert "params.filename" in script["source"], (
        "painless script must read params.filename so renamed files get "
        "the new name written through to indexed chunks"
    )
    assert params["filename"] == "Report-FY26.docx"
    # Sanity: scope is by document_id (the stable connector ID).
    assert body["query"] == {"term": {"document_id": "graph-item-id-stable"}}


@pytest.mark.asyncio
async def test_filename_passed_raw_not_cleaned(monkeypatch):
    """process_document_standard indexes chunks with the raw document.filename
    (see src/connectors/service.py:80 + src/models/processors.py:323).
    The metadata update must use the SAME raw value or chunks drift.
    """
    service, opensearch_client = _make_service()

    async def _noop_acl(**_kwargs):
        return {"status": "unchanged"}

    monkeypatch.setattr("utils.acl_utils.update_document_acl", _noop_acl)

    # A name with a quirky extension/suffix that clean_connector_filename
    # would normalize. We pass it through verbatim.
    raw_name = "Q4 Report (final).docx"
    document = _make_document(filename=raw_name)

    await service._update_connector_metadata(
        document, owner_user_id="alice", connector_type="sharepoint"
    )

    params = opensearch_client.update_by_query.await_args.kwargs["body"]["script"]["params"]
    assert params["filename"] == raw_name


@pytest.mark.asyncio
async def test_filename_overwritten_for_existing_indexed_chunks(monkeypatch):
    """End-to-end intent: when SharePoint rename triggers the unchanged ->
    metadata-update path, the painless update writes the new filename.
    Verified via the captured update_by_query body."""
    service, opensearch_client = _make_service()

    async def _noop_acl(**_kwargs):
        return {"status": "unchanged"}

    monkeypatch.setattr("utils.acl_utils.update_document_acl", _noop_acl)

    # Simulate the post-rename state: same ID, new filename.
    document = _make_document(filename="renamed-after-edit.pdf")
    await service._update_connector_metadata(
        document, owner_user_id="alice", connector_type="sharepoint"
    )

    body = opensearch_client.update_by_query.await_args.kwargs["body"]
    # The script must carry the new filename in its params, AND the source
    # must assign it onto _source.filename for every matching chunk.
    assert body["script"]["params"]["filename"] == "renamed-after-edit.pdf"
    assert "ctx._source.filename = params.filename" in body["script"]["source"]
