"""Messages for an upload that exceeds OPENRAG_MAX_UPLOAD_MB or the Docling proxy."""

import pytest

from utils import upload_limits
from utils.upload_limits import (
    docling_payload_too_large_message,
    docling_rejected_size_message,
    is_upload_size_error,
    max_upload_mb_from_env,
    read_upload_within_limit,
    upload_size_user_message,
    upload_too_large_message,
)


class _Warnings:
    def __init__(self):
        self.records: list[tuple[str, dict]] = []

    def warning(self, message, **fields):
        self.records.append((message, fields))

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def test_unset_upload_limit_stays_at_the_default_without_a_warning(monkeypatch):
    recorder = _Warnings()
    monkeypatch.setattr(upload_limits, "logger", recorder)

    assert max_upload_mb_from_env(None) == 100
    assert max_upload_mb_from_env("") == 100
    assert max_upload_mb_from_env("   ") == 100
    assert recorder.records == []


def test_bad_upload_limit_is_logged_and_replaced_with_the_default(monkeypatch):
    recorder = _Warnings()
    monkeypatch.setattr(upload_limits, "logger", recorder)

    for raw in ("100MB", "1.5", "0", "-1"):
        assert max_upload_mb_from_env(raw) == 100

    assert [fields["value"] for _, fields in recorder.records] == ["100MB", "1.5", "0", "-1"]


def test_a_positive_upload_limit_is_kept(monkeypatch):
    recorder = _Warnings()
    monkeypatch.setattr(upload_limits, "logger", recorder)

    assert max_upload_mb_from_env("1") == 1
    assert max_upload_mb_from_env(" 100 ") == 100
    assert recorder.records == []


def test_upload_too_large_message_names_the_file_and_its_size():
    message = upload_too_large_message("report.pdf", 2 * 1024 * 1024, 1)

    assert "report.pdf" in message
    assert "2.0 MB" in message
    assert "1 MB" in message
    assert "OPENRAG_MAX_UPLOAD_MB" in message
    assert is_upload_size_error(message)


def test_docling_413_message_names_the_endpoint_and_both_fixes():
    endpoint = "https://docling-serve:5001/v1/convert/file/async"
    message = docling_payload_too_large_message("report.pdf", 2 * 1024 * 1024, endpoint)

    assert "report.pdf" in message
    assert "2.0 MB" in message
    assert endpoint in message
    assert "HTTP 413" in message
    assert "client_max_body_size" in message
    assert "OPENRAG_MAX_UPLOAD_MB" in message
    assert is_upload_size_error(message)


def test_upload_size_user_message_drops_the_langflow_wrapper():
    inner = upload_too_large_message("report.pdf", 10, 1)
    assert upload_size_user_message(f"Docling upload failed: {inner}") == inner


def test_upload_size_user_message_hides_the_docling_endpoint(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    operator = docling_payload_too_large_message(
        "report.pdf",
        2 * 1024 * 1024,
        "https://docling-serve:5001/v1/convert/file/async",
    )

    message = upload_size_user_message(f"Docling upload failed: {operator}")

    assert message == docling_rejected_size_message("report.pdf", "2.0 MB", 1)
    assert "document-processing service" in message
    assert "within the configured upload limit" in message
    assert "docling-serve" not in message
    assert "client_max_body_size" not in message


class _ChunkedUpload:
    def __init__(self, chunks: list[bytes], size: int | None = None, filename: str = "notes.pdf"):
        self._chunks = list(chunks)
        self.size = size
        self.filename = filename
        self.reads = 0

    async def read(self, _n: int = -1) -> bytes:
        self.reads += 1
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


@pytest.mark.asyncio
async def test_read_upload_stops_when_the_declared_size_is_over_the_limit(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    upload = _ChunkedUpload([b"x" * 10], size=2 * 1024 * 1024)

    with pytest.raises(Exception, match="notes.pdf"):
        await read_upload_within_limit(upload)

    assert upload.reads == 0


@pytest.mark.asyncio
async def test_read_upload_stops_after_the_chunk_that_crosses_the_limit(monkeypatch):
    monkeypatch.setattr("config.settings.OPENRAG_MAX_UPLOAD_MB", 1)
    chunk = b"x" * (1024 * 1024)
    upload = _ChunkedUpload([chunk, chunk, chunk])

    with pytest.raises(Exception, match="notes.pdf"):
        await read_upload_within_limit(upload)

    assert upload.reads == 2


@pytest.mark.asyncio
async def test_read_upload_treats_a_short_chunk_as_the_end_of_the_body():
    upload = _ChunkedUpload([b"small", b"not-read"])

    assert await read_upload_within_limit(upload) == b"small"
    assert upload.reads == 1
