"""A real Langfuse SDK client for our spans, exporting to memory."""

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from observability import spans, tracing


@pytest.fixture(scope="session")
def _span_client_and_exporter():
    exporter = InMemorySpanExporter()
    patch = pytest.MonkeyPatch()
    # The SDK caches one client per public key; this key is only used here.
    patch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-openrag-spans-test")
    patch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-openrag-spans-test")
    patch.setenv("LANGFUSE_HOST", "http://127.0.0.1:9")
    try:
        spans.init_span_client(span_exporter=exporter)
        client = spans._client
    finally:
        patch.undo()
        spans._client = None
    yield client, exporter
    client.shutdown()


@pytest.fixture
def finished(_span_client_and_exporter, monkeypatch):
    """Turn tracing on; returns a function giving the exported spans by name.

    Content capture is off unless a test patches ``spans.content_capture_enabled``.
    """
    client, exporter = _span_client_and_exporter
    exporter.clear()
    monkeypatch.setattr(spans, "_client", client)
    monkeypatch.setattr(tracing, "_enabled", True)
    monkeypatch.delenv("OPENRAG_RUN_MODE", raising=False)
    monkeypatch.setattr(spans, "content_capture_enabled", lambda: False)

    def _finished():
        client.flush()
        return {span.name: span for span in exporter.get_finished_spans()}

    return _finished
