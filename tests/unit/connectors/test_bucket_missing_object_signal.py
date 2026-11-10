"""Bucket connectors: only a positive "object not found" means deleted.

``ConnectorFileProcessor`` deletes a file's indexed chunks when
``get_file_content`` raises ``FileNotFoundError``. S3 / IBM COS ``NoSuchKey``
and Azure ``BlobNotFound`` are that proof; a missing bucket or container, a
denied request, throttling or a network error is not, and must propagate as
itself so the indexed copy is kept (review 1l).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import botocore.exceptions
import ibm_botocore.exceptions
import pytest
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
from azure.storage.blob._generated.models import StorageErrorCode

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from connectors.aws_s3.connector import S3Connector  # noqa: E402
from connectors.bucket_errors import (  # noqa: E402
    is_azure_blob_missing,
    is_s3_object_missing,
    s3_error_code,
)
from enhancements.connectors.azure_blob.connector import AzureBlobConnector  # noqa: E402
from enhancements.connectors.ibm_cos.connector import IBMCOSConnector  # noqa: E402

FILE_ID = "b1::reports/q3.pdf"
NOT_DELETION_CODES = ["NoSuchBucket", "AccessDenied", "403", "SlowDown", "InternalError"]


def _aws_error(code: str) -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError({"Error": {"Code": code}}, "GetObject")


def _cos_error(code: str) -> ibm_botocore.exceptions.ClientError:
    return ibm_botocore.exceptions.ClientError({"Error": {"Code": code}}, "GetObject")


def _azure_error(cls=ResourceNotFoundError, code=None):
    error = cls(message="failed")
    if code is not None:
        error.error_code = code
    return error


# --- S3 / IBM COS -----------------------------------------------------------


def _s3(failure: BaseException) -> S3Connector:
    connector = S3Connector({"bucket_names": ["b1"]})
    connector._resource = MagicMock()
    connector._resource.Object.return_value.get.side_effect = failure
    return connector


def _cos(failure: BaseException, auth_mode: str) -> IBMCOSConnector:
    connector = IBMCOSConnector({"bucket_names": ["b1"], "auth_mode": auth_mode})
    handle = MagicMock()
    if auth_mode == "hmac":
        handle.Object.return_value.get.side_effect = failure  # resource API
    else:
        handle.get_object.side_effect = failure  # client API
    connector._handle = handle  # type: ignore[assignment]
    return connector


def _object_stores(failure_for):
    """(label, connector) for S3 and both COS auth modes."""
    return [
        ("s3", _s3(failure_for(_aws_error))),
        ("cos-hmac", _cos(failure_for(_cos_error), "hmac")),
        ("cos-iam", _cos(failure_for(_cos_error), "iam")),
    ]


@pytest.mark.asyncio
async def test_no_such_key_is_the_deleted_at_source_signal():
    for label, connector in _object_stores(lambda make: make("NoSuchKey")):
        with pytest.raises(FileNotFoundError) as raised:
            await connector.get_file_content(FILE_ID)
        assert raised.value.__cause__ is not None, label
        assert s3_error_code(raised.value.__cause__) == "NoSuchKey", label


@pytest.mark.asyncio
@pytest.mark.parametrize("code", NOT_DELETION_CODES)
async def test_other_object_store_errors_are_not_a_deletion(code):
    for label, connector in _object_stores(lambda make: make(code)):
        with pytest.raises(Exception) as raised:
            await connector.get_file_content(FILE_ID)
        assert not isinstance(raised.value, FileNotFoundError), label
        assert s3_error_code(raised.value) == code, label


@pytest.mark.asyncio
async def test_object_store_network_failure_is_not_a_deletion():
    for label, connector in _object_stores(lambda _make: ConnectionError("reset")):
        with pytest.raises(ConnectionError) as raised:
            await connector.get_file_content(FILE_ID)
        assert not isinstance(raised.value, FileNotFoundError), label


@pytest.mark.asyncio
async def test_invalid_file_id_is_not_a_deletion():
    connector = _s3(_aws_error("NoSuchKey"))
    with pytest.raises(ValueError):
        await connector.get_file_content("no-separator")


def test_s3_error_code_ignores_malformed_responses():
    for response in (None, "x", {}, {"Error": "x"}, {"Error": {"Code": 404}}):
        error = Exception()
        error.response = response
        assert s3_error_code(error) is None
        assert not is_s3_object_missing(error)


# --- Azure Blob -------------------------------------------------------------


def _azure(failure: BaseException) -> AzureBlobConnector:
    connector = AzureBlobConnector({"container_names": ["b1"]})
    client = MagicMock()
    client.get_blob_client.return_value.download_blob.side_effect = failure
    connector._client = client  # type: ignore[assignment]
    return connector


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", [StorageErrorCode.blob_not_found, "BlobNotFound"], ids=["enum", "str"]
)
async def test_blob_not_found_is_the_deleted_at_source_signal(code):
    connector = _azure(_azure_error(code=code))

    with pytest.raises(FileNotFoundError) as raised:
        await connector.get_file_content(FILE_ID)
    assert isinstance(raised.value.__cause__, ResourceNotFoundError)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        _azure_error(code=StorageErrorCode.container_not_found),
        _azure_error(code=None),
        _azure_error(ClientAuthenticationError, code=StorageErrorCode.authentication_failed),
        _azure_error(HttpResponseError, code=StorageErrorCode.server_busy),
        ConnectionError("reset"),
    ],
    ids=["container-missing", "no-code", "auth", "busy", "network"],
)
async def test_other_azure_errors_are_not_a_deletion(failure):
    connector = _azure(failure)

    with pytest.raises(type(failure)) as raised:
        await connector.get_file_content(FILE_ID)
    assert not isinstance(raised.value, FileNotFoundError)
    assert not is_azure_blob_missing(raised.value)
