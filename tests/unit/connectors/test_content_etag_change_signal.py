"""Entity tags are the change signal sync can rely on.

Timestamp-only change detection silently fails closed: with no stored
``modified_time`` to compare against, an overwritten object reports "unchanged"
forever. Object stores change the ETag on every overwrite, so bucket connectors
report it in listings and persist it at ingest, and sync compares the two.

Covers the plumbing end to end: normalization, what each connector emits, and
the enrichment that writes it onto the indexed chunks.
"""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# normalize_etag
# ---------------------------------------------------------------------------


def test_normalize_etag_strips_quotes_and_weak_prefix():
    """The same tag must compare equal however the API that returned it spells it."""
    from connectors.base import normalize_etag

    assert normalize_etag('"abc123"') == "abc123"
    assert normalize_etag("abc123") == "abc123"
    assert normalize_etag('W/"abc123"') == "abc123"
    assert normalize_etag('w/"abc123"') == "abc123"
    assert normalize_etag('  "abc123"  ') == "abc123"


def test_normalize_etag_keeps_multipart_suffix():
    """The part count is part of the identity, so it must survive normalization.

    Identical bytes uploaded with different part sizes produce different tags;
    re-ingesting in that case is wasteful but safe, while treating them as equal
    would skip a real change.
    """
    from connectors.base import normalize_etag

    assert (
        normalize_etag('"d41d8cd98f00b204e9800998ecf8427e-12"')
        == "d41d8cd98f00b204e9800998ecf8427e-12"
    )


def test_normalize_etag_returns_none_for_empty_values():
    from connectors.base import normalize_etag

    assert normalize_etag(None) is None
    assert normalize_etag("") is None
    assert normalize_etag('""') is None
    assert normalize_etag("   ") is None
    assert normalize_etag(12345) is None


# ---------------------------------------------------------------------------
# Connectors report the tag in listings and persist it on the document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ibm_cos_hmac_listing_and_download_carry_the_etag():
    from connectors.base import CONTENT_ETAG_METADATA_KEY
    from enhancements.connectors.ibm_cos.connector import IBMCOSConnector

    connector = IBMCOSConnector({"bucket_names": ["b1"], "auth_mode": "hmac"})

    obj = SimpleNamespace(
        key="reports/q3.pdf",
        size=10,
        last_modified=datetime(2026, 5, 7),
        e_tag='"abc123"',
    )
    bucket = MagicMock()
    bucket.objects.all.return_value = [obj]
    resource = MagicMock()
    resource.Bucket.return_value = bucket
    resource.Object.return_value.get.return_value = {
        "Body": SimpleNamespace(read=lambda: b"%PDF-1.4"),
        "ContentType": "application/pdf",
        "ContentLength": 8,
        "LastModified": datetime(2026, 5, 7),
        "ETag": '"abc123"',
    }
    resource.meta.client.get_object_acl.side_effect = RuntimeError("acls disabled")
    connector._handle = resource

    listing = await connector.list_files()
    assert listing["files"][0]["etag"] == "abc123"

    document = await connector.get_file_content("b1::reports/q3.pdf")
    assert document.metadata[CONTENT_ETAG_METADATA_KEY] == "abc123"


@pytest.mark.asyncio
async def test_ibm_cos_iam_listing_carries_the_etag():
    from enhancements.connectors.ibm_cos.connector import IBMCOSConnector

    connector = IBMCOSConnector({"bucket_names": ["b1"]})  # iam is the default
    client = MagicMock()
    client.list_objects_v2.return_value = {
        "Contents": [
            {
                "Key": "reports/q3.pdf",
                "Size": 10,
                "LastModified": datetime(2026, 5, 7),
                "ETag": '"abc123"',
            }
        ],
        "IsTruncated": False,
    }
    connector._handle = client

    listing = await connector.list_files()
    assert listing["files"][0]["etag"] == "abc123"


@pytest.mark.asyncio
async def test_aws_s3_listing_and_download_carry_the_etag():
    from connectors.aws_s3.connector import S3Connector
    from connectors.base import CONTENT_ETAG_METADATA_KEY

    connector = S3Connector({"bucket_names": ["b1"]})

    obj = SimpleNamespace(
        key="reports/q3.pdf",
        size=10,
        last_modified=datetime(2026, 5, 7),
        e_tag='"abc123"',
    )
    bucket = MagicMock()
    bucket.objects.all.return_value = [obj]
    resource = MagicMock()
    resource.Bucket.return_value = bucket
    resource.Object.return_value.get.return_value = {
        "Body": SimpleNamespace(read=lambda: b"%PDF-1.4"),
        "ContentType": "application/pdf",
        "ContentLength": 8,
        "LastModified": datetime(2026, 5, 7),
        "ETag": '"abc123"',
    }
    connector._resource = resource
    connector._client = MagicMock()
    connector._client.get_object_acl.side_effect = RuntimeError("acls disabled")

    listing = await connector.list_files()
    assert listing["files"][0]["etag"] == "abc123"

    document = await connector.get_file_content("b1::reports/q3.pdf")
    assert document.metadata[CONTENT_ETAG_METADATA_KEY] == "abc123"


@pytest.mark.asyncio
async def test_azure_blob_listing_and_download_carry_the_etag():
    from connectors.base import CONTENT_ETAG_METADATA_KEY
    from enhancements.connectors.azure_blob.connector import AzureBlobConnector

    connector = AzureBlobConnector({"container_names": ["c1"]})

    blob = SimpleNamespace(
        name="reports/q3.pdf",
        size=10,
        last_modified=datetime(2026, 5, 7),
        # Azure marks its tags weak.
        etag='W/"abc123"',
    )
    container_client = MagicMock()
    container_client.list_blobs.return_value = [blob]
    client = MagicMock()
    client.get_container_client.return_value = container_client
    downloader = MagicMock()
    downloader.readall.return_value = b"%PDF-1.4"
    downloader.properties = SimpleNamespace(
        content_settings=SimpleNamespace(content_type="application/pdf"),
        last_modified=datetime(2026, 5, 7),
        etag='W/"abc123"',
        size=8,
    )
    client.get_blob_client.return_value.download_blob.return_value = downloader
    connector._client = client

    listing = await connector.list_files()
    assert listing["files"][0]["etag"] == "abc123"

    document = await connector.get_file_content("c1::reports/q3.pdf")
    assert document.metadata[CONTENT_ETAG_METADATA_KEY] == "abc123"


# ---------------------------------------------------------------------------
# The enrichment persists it onto the indexed chunks
# ---------------------------------------------------------------------------


def _make_service():
    from connectors.service import ConnectorService

    service = ConnectorService.__new__(ConnectorService)
    service.session_manager = MagicMock()
    service.index_name = "test-index"
    opensearch_client = AsyncMock()
    service.session_manager.get_user_opensearch_client = MagicMock(return_value=opensearch_client)
    service.clients = MagicMock()
    service.clients.opensearch = opensearch_client
    return service, opensearch_client


def _make_document(metadata):
    from connectors.base import ConnectorDocument, DocumentACL

    return ConnectorDocument(
        id="b1::reports/q3.pdf",
        filename="q3.pdf",
        mimetype="application/pdf",
        content=b"",
        source_url="cos://b1/reports/q3.pdf",
        acl=DocumentACL(owner="alice"),
        modified_time=datetime(2026, 5, 7),
        created_time=datetime(2026, 5, 1),
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_metadata_update_promotes_content_etag_to_a_top_level_field(monkeypatch):
    """Stored as its own keyword so sync can read it back with a terms agg."""
    from connectors.base import CONTENT_ETAG_METADATA_KEY

    service, opensearch_client = _make_service()

    async def _noop_acl(**_kwargs):
        return {"status": "unchanged"}

    monkeypatch.setattr("utils.acl_utils.update_document_acl", _noop_acl)

    document = _make_document({"size": 8, CONTENT_ETAG_METADATA_KEY: '"abc123"'})
    await service._update_connector_metadata(
        document, owner_user_id="alice", connector_type="ibm_cos"
    )

    script = opensearch_client.update_by_query.await_args.kwargs["body"]["script"]
    assert "ctx._source.content_etag = params.content_etag" in script["source"]
    # Normalized on the way in so it compares equal to a fresh listing's tag.
    assert script["params"]["content_etag"] == "abc123"


@pytest.mark.asyncio
async def test_metadata_update_omits_content_etag_when_connector_reports_none(monkeypatch):
    """OAuth connectors report no tag; the field must stay absent, not empty."""
    service, opensearch_client = _make_service()

    async def _noop_acl(**_kwargs):
        return {"status": "unchanged"}

    monkeypatch.setattr("utils.acl_utils.update_document_acl", _noop_acl)

    await service._update_connector_metadata(
        _make_document({"site": "marketing"}), owner_user_id="alice", connector_type="sharepoint"
    )

    script = opensearch_client.update_by_query.await_args.kwargs["body"]["script"]
    # The script guards on null, so a None param leaves existing chunks alone.
    assert script["params"]["content_etag"] is None
    assert "if (params.content_etag != null)" in script["source"]
