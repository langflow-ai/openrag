"""Classify object-store failures for the S3, IBM COS and Azure Blob connectors.

Only a positive "this object does not exist" answer may be treated as a
deletion at source: ``ConnectorFileProcessor`` deletes indexed chunks on
``FileNotFoundError``. A missing bucket or container (misconfiguration or lost
scope, not proof the file was deleted), an auth failure (S3 also answers 403
for a missing key when the caller lacks ``s3:ListBucket``), throttling, server
and network errors prove nothing about the object and must propagate instead.
"""

# Object-level "not found" codes. Bucket/container-level codes (NoSuchBucket,
# ContainerNotFound) are deliberately absent.
S3_OBJECT_MISSING_CODES = frozenset({"NoSuchKey"})
AZURE_BLOB_MISSING_CODES = frozenset({"BlobNotFound"})


def s3_error_code(exc: BaseException) -> str | None:
    """Error code of a botocore / ibm_botocore ``ClientError``, else None.

    Duck-typed on ``exc.response["Error"]["Code"]`` so neither SDK has to be
    imported here.
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    error = response.get("Error")
    if not isinstance(error, dict):
        return None
    code = error.get("Code")
    return code if isinstance(code, str) else None


def is_s3_object_missing(exc: BaseException) -> bool:
    """True only when S3 / COS positively reported that the key does not exist."""
    return s3_error_code(exc) in S3_OBJECT_MISSING_CODES


def is_azure_blob_missing(exc: BaseException) -> bool:
    """True only when Azure positively reported that the blob does not exist.

    ``error_code`` is a ``StorageErrorCode`` (a ``str`` enum) or a plain string;
    compare on the enum's value so the check doesn't depend on enum hashing.
    """
    code = getattr(exc, "error_code", None)
    code = getattr(code, "value", code)
    return isinstance(code, str) and code in AZURE_BLOB_MISSING_CODES


def object_missing_error(file_id: str) -> FileNotFoundError:
    """The deleted-at-source signal; raise it ``from`` the provider error."""
    return FileNotFoundError(f"Object no longer exists at source: {file_id}")
