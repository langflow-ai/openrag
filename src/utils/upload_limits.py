"""Upload size limit shared by the API, Docling submission, and task errors.

The proxy in front of Docling Serve rejects the request body (often at 1 MB).
OpenRAG refuses a larger file at upload time, and turns a 413 from that proxy
into the same kind of message. URL ingest does not post a file body and does
not use this limit.
"""

from __future__ import annotations

import re

_MIB = 1024 * 1024
_READ_CHUNK = 1 << 20
_MARKER = "OPENRAG_MAX_UPLOAD_MB"
_UNITS = ("B", "KB", "MB", "GB", "TB")
# Operator text stored before a Docling task exists: filename, size, then the
# internal endpoint. The task UI must not show that endpoint.
_PROXY_REJECTION = re.compile(r'^"(?P<filename>.*)" \((?P<size>[^)]+)\) was rejected by \S+')


class UploadTooLarge(Exception):
    """The file is larger than OPENRAG_MAX_UPLOAD_MB."""

    def __init__(self, filename: str, size_bytes: int, limit_mb: int):
        self.filename = filename
        self.size_bytes = size_bytes
        self.limit_mb = limit_mb
        super().__init__(upload_too_large_message(filename, size_bytes, limit_mb))


def max_upload_mb() -> int:
    """Configured limit in mebibytes. Values below 1 fall back to 100."""
    from config import settings

    value = settings.OPENRAG_MAX_UPLOAD_MB
    if not isinstance(value, int) or value < 1:
        return 100
    return value


def max_upload_bytes() -> int:
    return max_upload_mb() * _MIB


def format_byte_size(num_bytes: int) -> str:
    """Match the frontend file-size label (1024-based, one decimal above bytes)."""
    size = float(max(num_bytes, 0))
    if size < 1024:
        return f"{int(size)} B"
    unit_index = 0
    while size >= 1024 and unit_index < len(_UNITS) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {_UNITS[unit_index]}"


def upload_too_large_message(filename: str, size_bytes: int, limit_mb: int) -> str:
    return (
        f'"{filename}" is {format_byte_size(size_bytes)}. '
        f"The upload limit is {limit_mb} MB ({_MARKER})."
    )


def docling_payload_too_large_message(filename: str, size_bytes: int, endpoint: str) -> str:
    return (
        f'"{filename}" ({format_byte_size(size_bytes)}) was rejected by {endpoint} '
        "with HTTP 413. The proxy in front of Docling Serve is limiting the request body. "
        "Raise that limit (nginx: client_max_body_size), or set "
        f"{_MARKER} to the proxy's real limit."
    )


def ensure_within_upload_limit(filename: str | None, size_bytes: int) -> None:
    """Raise UploadTooLarge when the file is over the configured limit."""
    limit_bytes = max_upload_bytes()
    if size_bytes > limit_bytes:
        raise UploadTooLarge(filename or "upload", size_bytes, max_upload_mb())


async def read_upload_within_limit(upload_file, filename: str | None = None) -> bytes:
    """Read an upload, stopping once it crosses OPENRAG_MAX_UPLOAD_MB.

    A known part size is checked before any bytes are copied into memory.
    Otherwise the body is read in 1 MiB chunks and the rest is left unread
    after the limit is crossed.
    """
    name = filename if filename is not None else getattr(upload_file, "filename", None)
    known_size = getattr(upload_file, "size", None)
    if isinstance(known_size, int) and known_size > max_upload_bytes():
        raise UploadTooLarge(name or "upload", known_size, max_upload_mb())

    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await upload_file.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        ensure_within_upload_limit(name, size)
        chunks.append(chunk)
        # A short read is the end of the body. Stopping here also keeps a
        # caller that returns the same bytes on every read from looping.
        if len(chunk) < _READ_CHUNK:
            break
    return b"".join(chunks)


def is_upload_size_error(error: str | None) -> bool:
    return _MARKER in (error or "")


def upload_size_user_message(error: str) -> str:
    """Limit line for the task UI, without the internal Docling URL."""
    text = error.removeprefix("Docling upload failed: ").strip()
    match = _PROXY_REJECTION.match(text)
    if match is None:
        return text
    return (
        f'"{match.group("filename")}" is {match.group("size")}. '
        f"The upload limit is {max_upload_mb()} MB ({_MARKER})."
    )
