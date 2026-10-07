"""The ingest body is capped while it is being read, not after it is stored.

``_oversized_upload_response`` still names a file that was fully received and
is over the per-file limit. A body past that limit plus the multipart
allowance must stop the read before the endpoint runs.
"""

import pytest
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.testclient import TestClient

from api.upload_body_limit import (
    UPLOAD_BODY_OVERHEAD_BYTES,
    UploadBodyLimitMiddleware,
    limited_receive,
)

MB = 1024 * 1024


async def _messages(*chunks: bytes):
    """An ASGI receive that yields these body chunks, then ends."""
    pending = [{"type": "http.request", "body": chunk, "more_body": True} for chunk in chunks]
    pending.append({"type": "http.request", "body": b"", "more_body": False})

    async def receive():
        return pending.pop(0)

    return receive


@pytest.mark.asyncio
async def test_chunks_under_the_limit_are_forwarded():
    receive = await _messages(b"abc", b"de")
    wrapped = limited_receive(receive, max_bytes=5)

    first = await wrapped()
    second = await wrapped()
    end = await wrapped()

    assert first["body"] == b"abc"
    assert second["body"] == b"de"
    assert end["body"] == b""


@pytest.mark.asyncio
async def test_the_chunk_that_crosses_the_limit_is_not_forwarded():
    receive = await _messages(b"abc", b"defgh")
    wrapped = limited_receive(receive, max_bytes=5)

    assert (await wrapped())["body"] == b"abc"
    with pytest.raises(HTTPException) as excinfo:
        await wrapped()
    assert excinfo.value.status_code == 413


def _client(monkeypatch, per_file: int, overhead: int):
    monkeypatch.setattr("config.settings.MAX_UPLOAD_SIZE_BYTES", per_file)
    monkeypatch.setattr("config.settings.MAX_UPLOAD_SIZE_MB", 1)
    monkeypatch.setattr("api.upload_body_limit.UPLOAD_BODY_OVERHEAD_BYTES", overhead)

    called: list[int] = []
    app = FastAPI()
    app.add_middleware(UploadBodyLimitMiddleware)

    @app.post("/router/upload_ingest")
    async def ingest(file: UploadFile = File(...)):
        called.append(file.size or 0)
        return {"size": file.size}

    @app.post("/other")
    async def other(file: UploadFile = File(...)):
        called.append(-(file.size or 0))
        return {"size": file.size}

    return TestClient(app), called


def test_a_body_past_the_allowance_stops_before_the_endpoint(monkeypatch):
    client, called = _client(monkeypatch, per_file=100, overhead=200)

    response = client.post(
        "/router/upload_ingest",
        files={"file": ("big.bin", b"x" * 1000, "application/octet-stream")},
    )

    assert response.status_code == 413
    assert "One ingest request cannot exceed" in response.json()["detail"]
    assert called == []


def test_a_file_over_the_per_file_limit_but_inside_the_allowance_reaches_the_endpoint(
    monkeypatch,
):
    """The named per-file error can only be built once the part is complete."""
    client, called = _client(monkeypatch, per_file=100, overhead=10_000)

    response = client.post(
        "/router/upload_ingest",
        files={"file": ("mid.bin", b"x" * 150, "application/octet-stream")},
    )

    assert response.status_code == 200
    assert called == [150]


def test_a_non_ingest_route_is_not_capped(monkeypatch):
    client, called = _client(monkeypatch, per_file=100, overhead=200)

    response = client.post(
        "/other",
        files={"file": ("big.bin", b"x" * 1000, "application/octet-stream")},
    )

    assert response.status_code == 200
    assert called == [-1000]


def test_the_allowance_is_one_mebibyte_above_the_per_file_limit(monkeypatch):
    monkeypatch.setattr("config.settings.MAX_UPLOAD_SIZE_BYTES", 100 * MB)
    from api.upload_body_limit import upload_request_body_limit_bytes

    assert upload_request_body_limit_bytes() == 100 * MB + UPLOAD_BODY_OVERHEAD_BYTES


@pytest.mark.parametrize("raw", ["0", "-1", "-100"])
def test_a_non_positive_upload_limit_is_rejected(monkeypatch, raw):
    monkeypatch.setenv("OPENRAG_MAX_UPLOAD_MB", raw)
    from config.settings import resolve_max_upload_size_mb

    with pytest.raises(RuntimeError, match="positive"):
        resolve_max_upload_size_mb()


def test_an_unset_upload_limit_uses_the_default(monkeypatch):
    monkeypatch.delenv("OPENRAG_MAX_UPLOAD_MB", raising=False)
    from config.settings import resolve_max_upload_size_mb

    assert resolve_max_upload_size_mb() == 100


def test_a_positive_upload_limit_is_kept(monkeypatch):
    monkeypatch.setenv("OPENRAG_MAX_UPLOAD_MB", "25")
    from config.settings import resolve_max_upload_size_mb

    assert resolve_max_upload_size_mb() == 25
