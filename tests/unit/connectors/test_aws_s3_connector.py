"""Unit tests for the AWS S3 connector.

Mirrors the IBM COS and Azure Blob coverage
(tests/unit/connectors/test_ibm_cos_connector.py,
tests/unit/connectors/test_azure_blob_connector.py) for the `is_available`
gating, and pins the change-detection signals S3 reports.

S3 is the bucket connector with the least real-world validation — until
OPENRAG_DEV_AWS_S3 it could not be enabled at all without IBM auth, so its sync
behaviour was only ever exercised through machinery shared with COS. These
assert the S3 path directly rather than inferring it from its siblings.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from connectors.aws_s3 import connector as aws_s3_connector  # noqa: E402
from connectors.aws_s3.connector import S3Connector  # noqa: E402
from connectors.base import CONTENT_ETAG_METADATA_KEY  # noqa: E402

MODIFIED = datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# is_available gating
# ---------------------------------------------------------------------------


def test_is_available_gated_on_ibm_auth_enabled(monkeypatch):
    monkeypatch.setattr(aws_s3_connector, "IBM_AUTH_ENABLED", True)
    monkeypatch.setattr(aws_s3_connector, "is_dev_aws_s3_enabled", lambda: False)
    assert S3Connector.is_available(MagicMock()) is True
    monkeypatch.setattr(aws_s3_connector, "IBM_AUTH_ENABLED", False)
    assert S3Connector.is_available(MagicMock()) is False


def test_is_available_dev_flag_bypasses_ibm_auth(monkeypatch):
    """Without this, S3 could not be exercised locally at all (e.g. MinIO)."""
    monkeypatch.setattr(aws_s3_connector, "IBM_AUTH_ENABLED", False)
    monkeypatch.setattr(aws_s3_connector, "is_dev_aws_s3_enabled", lambda: True)
    assert S3Connector.is_available(MagicMock()) is True


def test_is_dev_aws_s3_enabled_defaults_false_when_unset(monkeypatch):
    from config.settings import is_dev_aws_s3_enabled

    monkeypatch.delenv("OPENRAG_DEV_AWS_S3", raising=False)
    assert is_dev_aws_s3_enabled() is False
    monkeypatch.setenv("OPENRAG_DEV_AWS_S3", "true")
    assert is_dev_aws_s3_enabled() is True


# ---------------------------------------------------------------------------
# Change-detection signals
# ---------------------------------------------------------------------------


def _object(key: str, etag: str):
    return SimpleNamespace(key=key, size=10, last_modified=MODIFIED, e_tag=etag)


def _connector_with(objects):
    connector = S3Connector({"bucket_names": ["b1"]})
    bucket = MagicMock()
    bucket.objects.all.return_value = objects
    resource = MagicMock()
    resource.Bucket.return_value = bucket
    connector._resource = resource
    return connector


@pytest.mark.asyncio
async def test_listing_reports_the_signals_sync_compares():
    """Sync needs both an id and an etag off the listing to spot an overwrite."""
    connector = _connector_with([_object("reports/q3.pdf", '"abc123"')])

    listed = (await connector.list_files())["files"][0]

    assert listed["id"] == "b1::reports/q3.pdf"
    assert listed["modified_time"] == MODIFIED.isoformat()
    # Normalized: S3 quotes its tags, the stored copy is unquoted.
    assert listed["etag"] == "abc123"


@pytest.mark.asyncio
async def test_listing_skips_directory_placeholders():
    connector = _connector_with(
        [_object("folder/", '"dir"'), _object("folder/real.pdf", '"abc123"')]
    )

    files = (await connector.list_files())["files"]

    assert [f["id"] for f in files] == ["b1::folder/real.pdf"]


@pytest.mark.asyncio
async def test_download_persists_the_etag_for_the_next_sync():
    connector = _connector_with([])
    connector._resource.Object.return_value.get.return_value = {
        "Body": SimpleNamespace(read=lambda: b"%PDF-1.4"),
        "ContentType": "application/pdf",
        "ContentLength": 8,
        "LastModified": MODIFIED,
        "ETag": '"abc123"',
    }
    connector._client = MagicMock()
    connector._client.get_object_acl.side_effect = RuntimeError("acls disabled")

    document = await connector.get_file_content("b1::reports/q3.pdf")

    assert document.metadata[CONTENT_ETAG_METADATA_KEY] == "abc123"
    assert document.modified_time == MODIFIED


@pytest.mark.asyncio
async def test_overwriting_an_object_classifies_as_changed():
    """The end-to-end question this connector kept getting asked.

    Drives the real classifier off the real listing, for each combination of
    stored signals a deployment can actually have.
    """
    from api.connectors import SyncedFileState, classify_remote_file_change

    fid = "b1::reports/q3.pdf"
    stored_ms = MODIFIED.timestamp() * 1000
    later = datetime(2026, 6, 1, tzinfo=UTC)

    overwritten = _connector_with([_object("reports/q3.pdf", '"v2"')])
    overwritten._resource.Bucket.return_value.objects.all.return_value = [
        SimpleNamespace(key="reports/q3.pdf", size=11, last_modified=later, e_tag='"v2"')
    ]
    remote = (await overwritten.list_files())["files"][0]

    for label, stored in (
        ("etag + timestamp", SyncedFileState(stored_ms, "v1")),
        ("timestamp only (ingested before etags)", SyncedFileState(stored_ms, None)),
        ("etag only", SyncedFileState(None, "v1")),
    ):
        assert (
            classify_remote_file_change(
                fid, remote["modified_time"], True, {fid: stored}, remote["etag"]
            )
            == "changed"
        ), label


@pytest.mark.asyncio
async def test_identical_bytes_are_not_re_ingested_when_the_timestamp_moves():
    """A copy or re-upload bumps LastModified without changing the content."""
    from api.connectors import SyncedFileState, classify_remote_file_change

    fid = "b1::reports/q3.pdf"
    later = datetime(2026, 6, 1, tzinfo=UTC)
    connector = _connector_with([])
    connector._resource.Bucket.return_value.objects.all.return_value = [
        SimpleNamespace(key="reports/q3.pdf", size=10, last_modified=later, e_tag='"v1"')
    ]
    remote = (await connector.list_files())["files"][0]

    stored = SyncedFileState(MODIFIED.timestamp() * 1000, "v1")
    assert (
        classify_remote_file_change(
            fid, remote["modified_time"], True, {fid: stored}, remote["etag"]
        )
        == "unchanged"
    )
