"""Bucket connectors never return a partial inventory.

Orphan reconciliation deletes the indexed chunks of every file missing from a
successful ``list_files``. A bucket or container that failed to list, or a
failed auto-discovery that yields no buckets, must therefore raise instead of
returning what did list; ``list_remote_files_for_connector_type`` then aborts
the pass and nothing is deleted.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.connectors import list_remote_files_for_connector_type  # noqa: E402
from connectors.aws_s3.connector import S3Connector  # noqa: E402
from enhancements.connectors.azure_blob.connector import AzureBlobConnector  # noqa: E402
from enhancements.connectors.ibm_cos.connector import IBMCOSConnector  # noqa: E402

MODIFIED = datetime(2024, 1, 1, tzinfo=UTC)


class ListingFailed(Exception):
    pass


def _obj(key):
    return SimpleNamespace(key=key, size=1, last_modified=MODIFIED, e_tag='"t"')


def _resource(failing_bucket):
    """boto-style resource: ``ok`` lists one object, ``failing_bucket`` raises."""
    resource = MagicMock()

    def bucket(name):
        handle = MagicMock()
        if name == failing_bucket:
            handle.objects.all.side_effect = ListingFailed(name)
        else:
            handle.objects.all.return_value = [_obj("a.pdf")]
        return handle

    resource.Bucket.side_effect = bucket
    return resource


def _s3(failing_bucket="bad"):
    connector = S3Connector({"bucket_names": ["ok", "bad"]})
    connector._resource = _resource(failing_bucket)
    return connector


def _cos_hmac(failing_bucket="bad"):
    connector = IBMCOSConnector({"bucket_names": ["ok", "bad"], "auth_mode": "hmac"})
    connector._handle = _resource(failing_bucket)
    return connector


def _cos_iam(failing_bucket="bad"):
    connector = IBMCOSConnector({"bucket_names": ["ok", "bad"], "auth_mode": "iam"})
    client = MagicMock()

    def list_objects_v2(Bucket, **_kwargs):
        if Bucket == failing_bucket:
            raise ListingFailed(Bucket)
        return {"Contents": [{"Key": "a.pdf", "Size": 1, "LastModified": MODIFIED}]}

    client.list_objects_v2.side_effect = list_objects_v2
    connector._handle = client
    return connector


def _azure(failing_bucket="bad"):
    connector = AzureBlobConnector({"container_names": ["ok", "bad"]})
    client = MagicMock()

    def container_client(name):
        handle = MagicMock()
        if name == failing_bucket:
            handle.list_blobs.side_effect = ListingFailed(name)
        else:
            blob = MagicMock()
            blob.name, blob.size, blob.last_modified, blob.etag = "a.pdf", 1, MODIFIED, '"t"'
            handle.list_blobs.return_value = iter([blob])
        return handle

    client.get_container_client.side_effect = container_client
    connector._client = client
    return connector


FACTORIES = {"s3": _s3, "cos-hmac": _cos_hmac, "cos-iam": _cos_iam, "azure": _azure}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", FACTORIES)
async def test_one_unlistable_bucket_fails_the_whole_listing(kind):
    with pytest.raises(ListingFailed):
        await FACTORIES[kind]().list_files()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", FACTORIES)
async def test_listing_succeeds_when_every_bucket_lists(kind):
    files = (await FACTORIES[kind](failing_bucket=None).list_files())["files"]
    assert {f["bucket"] for f in files} == {"ok", "bad"}


@pytest.mark.asyncio
async def test_failed_bucket_discovery_raises_instead_of_listing_nothing():
    s3 = S3Connector({})
    s3._resource = MagicMock()
    s3._resource.buckets.all.side_effect = ListingFailed("discovery")

    cos_hmac = IBMCOSConnector({"auth_mode": "hmac"})
    cos_hmac._handle = MagicMock()
    cos_hmac._handle.buckets.all.side_effect = ListingFailed("discovery")

    cos_iam = IBMCOSConnector({"auth_mode": "iam"})
    cos_iam._handle = MagicMock()
    cos_iam._handle.list_buckets.side_effect = ListingFailed("discovery")

    azure = AzureBlobConnector({})
    azure._client = MagicMock()
    azure._client.list_containers.side_effect = ListingFailed("discovery")

    for connector in (s3, cos_hmac, cos_iam, azure):
        with pytest.raises(ListingFailed):
            await connector.list_files()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", FACTORIES)
async def test_unlistable_bucket_aborts_orphan_reconciliation(kind):
    connector = FACTORIES[kind]()
    connector._authenticated = True
    service = SimpleNamespace(
        connection_manager=SimpleNamespace(
            list_connections=AsyncMock(
                return_value=[SimpleNamespace(connection_id="c1", is_active=True)]
            )
        ),
        get_connector=AsyncMock(return_value=connector),
    )

    remote = await list_remote_files_for_connector_type(
        connector_type=connector.CONNECTOR_TYPE,
        user_id="alice",
        connector_service=service,
        existing_file_ids=["bad::indexed.pdf"],
    )

    assert remote is None  # "could not determine safely", not "bad bucket is empty"
