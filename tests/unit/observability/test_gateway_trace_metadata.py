"""What each gateway call tells Langfuse about itself, beyond LiteLLM's defaults.

LiteLLM's `langfuse_otel` callback reads the call's `metadata` kwarg:
`generation_name` names the observation, `trace_user_id` / `session_id` set
Langfuse's user and session, and `trace_metadata` keys become filterable
metadata (other keys are dropped). Verified against Langfuse Cloud.
"""

import pytest

from observability import tracing
from observability.tracing import gateway_trace_kwargs, trace_context


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(tracing, "_enabled", True)
    monkeypatch.delenv("OPENRAG_RUN_MODE", raising=False)


def test_nothing_is_added_when_tracing_is_off(monkeypatch):
    monkeypatch.setattr(tracing, "_enabled", False)

    assert gateway_trace_kwargs("embedding", "ingest", inputs=3) == {}


def test_names_the_observation_after_kind_and_purpose(enabled):
    metadata = gateway_trace_kwargs("embedding", "query")["metadata"]

    assert metadata["generation_name"] == "embedding.query"
    assert metadata["trace_metadata"]["openrag.purpose"] == "query"


def test_backend_calls_are_attributed_to_openrag_by_default(enabled):
    metadata = gateway_trace_kwargs("embedding", "ingest")["metadata"]

    assert metadata["trace_metadata"]["openrag.source"] == "openrag"
    assert metadata["trace_metadata"]["openrag.run_mode"] == "oss"
    assert set(metadata["tags"]) == {"source:openrag", "purpose:ingest"}
    assert "trace_user_id" not in metadata
    assert "session_id" not in metadata


def test_sizes_are_recorded_as_openrag_attributes(enabled):
    metadata = gateway_trace_kwargs("embedding", "ingest", inputs=3, input_chars=120)["metadata"]

    assert metadata["trace_metadata"]["openrag.embedding.inputs"] == 3
    assert metadata["trace_metadata"]["openrag.embedding.input_chars"] == 120


def test_none_sizes_are_left_out(enabled):
    metadata = gateway_trace_kwargs("chat", "completion", tools=None)["metadata"]

    assert "openrag.chat.tools" not in metadata["trace_metadata"]


def test_call_context_sets_source_user_and_session(enabled):
    with trace_context(source="langflow", user_id="user-1", session_id="run-1"):
        metadata = gateway_trace_kwargs("embedding", "ingest")["metadata"]

    assert metadata["trace_metadata"]["openrag.source"] == "langflow"
    assert metadata["trace_user_id"] == "user-1"
    assert metadata["session_id"] == "run-1"
    assert "source:langflow" in metadata["tags"]


def test_call_context_purpose_overrides_the_callers_default(enabled):
    with trace_context(purpose="dimension_probe"):
        metadata = gateway_trace_kwargs("embedding", "ingest")["metadata"]

    assert metadata["generation_name"] == "embedding.dimension_probe"


def test_call_context_attributes_are_added(enabled):
    with trace_context(attributes={"openrag.langflow_run_purpose": "chat"}):
        metadata = gateway_trace_kwargs("chat", "completion")["metadata"]

    assert metadata["trace_metadata"]["openrag.langflow_run_purpose"] == "chat"


def test_call_context_nests_and_restores(enabled):
    with trace_context(source="langflow", user_id="user-1"):
        with trace_context(purpose="query"):
            inner = gateway_trace_kwargs("embedding", "ingest")["metadata"]
        outer = gateway_trace_kwargs("embedding", "ingest")["metadata"]
    after = gateway_trace_kwargs("embedding", "ingest")["metadata"]

    assert inner["generation_name"] == "embedding.query"
    assert inner["trace_user_id"] == "user-1"
    assert outer["generation_name"] == "embedding.ingest"
    assert after["trace_metadata"]["openrag.source"] == "openrag"
    assert "trace_user_id" not in after


def test_empty_user_and_session_are_left_out(enabled):
    with trace_context(user_id="", session_id=None):
        metadata = gateway_trace_kwargs("embedding", "ingest")["metadata"]

    assert "trace_user_id" not in metadata
    assert "session_id" not in metadata
