import hashlib

import pytest


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None, text: str = ""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text


@pytest.mark.asyncio
async def test_signature_fallback_uses_get_body_when_head_has_no_cache_headers(monkeypatch):
    """When HEAD lacks ETag/Last-Modified, fallback must hash GET body content."""
    from main import _get_remote_docs_signature

    calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def head(self, _url):
            calls.append("head")
            return _FakeResponse(200, headers={}, text="")

        async def get(self, _url):
            calls.append("get")
            return _FakeResponse(200, headers={}, text="docs-content-v1")

    monkeypatch.setattr("main.httpx.AsyncClient", FakeAsyncClient)

    signature = await _get_remote_docs_signature("https://docs.example")
    expected = hashlib.sha256("docs-content-v1".encode("utf-8")).hexdigest()

    assert signature == expected
    assert calls == ["head", "get"]


@pytest.mark.asyncio
async def test_signature_changes_when_get_body_changes_without_cache_headers(monkeypatch):
    """Without cache headers, different GET content should produce different signatures."""
    from main import _get_remote_docs_signature

    get_bodies = ["docs-content-v1", "docs-content-v2"]

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def head(self, _url):
            return _FakeResponse(200, headers={}, text="")

        async def get(self, _url):
            return _FakeResponse(200, headers={}, text=get_bodies.pop(0))

    monkeypatch.setattr("main.httpx.AsyncClient", FakeAsyncClient)

    signature_1 = await _get_remote_docs_signature("https://docs.example")
    signature_2 = await _get_remote_docs_signature("https://docs.example")

    assert signature_1 is not None
    assert signature_2 is not None
    assert signature_1 != signature_2
