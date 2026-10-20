"""OpenRAG's own spans (ingest, search) as Langfuse observations.

Spans go through the real Langfuse SDK client into an in-memory exporter, so
these assert the OTel attributes Langfuse ingests.
"""

import pytest
from langfuse._client.attributes import LangfuseOtelSpanAttributes as LF
from opentelemetry import context as otel_context
from opentelemetry import trace

from observability import spans
from observability.spans import trace_root, trace_span
from observability.tracing import gateway_trace_kwargs, trace_context


def _metadata(span, key):
    return span.attributes.get(f"{LF.OBSERVATION_METADATA}.{key}")


def _trace_metadata(span, key):
    return span.attributes.get(f"{LF.TRACE_METADATA}.{key}")


# --- off -------------------------------------------------------------------


def test_off_by_default_everything_is_a_no_op(monkeypatch):
    monkeypatch.setattr(spans, "_client", None)

    with trace_root("ingest.file", attributes={"openrag.document_id": "d"}) as root:
        with trace_span("ingest.parse") as parse:
            parse.set(chunks=3)
            parse.set_content(filename="secret.pdf")
            parse.fail("ValueError")
        root.set(status="indexed")


def test_off_exceptions_still_propagate(monkeypatch):
    monkeypatch.setattr(spans, "_client", None)

    with pytest.raises(ValueError), trace_root("ingest.file", attributes={}):
        raise ValueError("boom")


# --- shape -----------------------------------------------------------------


def test_root_and_stage_spans_nest(finished):
    with trace_root("ingest.file", attributes={}), trace_span("ingest.parse"):
        pass

    exported = finished()
    root, parse = exported["ingest.file"], exported["ingest.parse"]
    assert root.parent is None
    assert parse.parent.span_id == root.context.span_id
    assert parse.context.trace_id == root.context.trace_id


def test_a_root_starts_its_own_trace_inside_another_span(finished):
    """Background ingest inherits the request's (e.g. Instana's) span; the file gets its own trace."""
    foreign = trace.NonRecordingSpan(
        trace.SpanContext(
            trace_id=0x1234,
            span_id=0x5678,
            is_remote=False,
            trace_flags=trace.TraceFlags(trace.TraceFlags.SAMPLED),
        )
    )
    token = otel_context.attach(trace.set_span_in_context(foreign))
    try:
        with trace_root("ingest.file", attributes={}):
            pass
        assert trace.get_current_span() is foreign
    finally:
        otel_context.detach(token)

    root = finished()["ingest.file"]
    assert root.parent is None
    assert root.context.trace_id != 0x1234


def test_root_sets_trace_name_user_session_tags_and_metadata(finished):
    with trace_root(
        "ingest.file",
        user_id="user-1",
        session_id="task-1",
        tags=["ingest_path:openrag"],
        attributes={"openrag.document_id": "doc-1", "openrag.file.size": 42, "skip": None},
    ):
        pass

    root = finished()["ingest.file"]
    assert root.attributes[LF.TRACE_NAME] == "ingest.file"
    assert root.attributes[LF.TRACE_USER_ID] == "user-1"
    assert root.attributes[LF.TRACE_SESSION_ID] == "task-1"
    assert list(root.attributes[LF.TRACE_TAGS]) == ["ingest_path:openrag"]
    assert _trace_metadata(root, "openrag.document_id") == "doc-1"
    assert _trace_metadata(root, "openrag.file.size") == "42"
    assert _trace_metadata(root, "openrag.run_mode") == "oss"
    assert _trace_metadata(root, "skip") is None


def test_root_takes_user_session_and_attributes_from_the_trace_context(finished):
    with (
        trace_context(
            user_id="user-2", session_id="task-2", attributes={"openrag.task_id": "task-2"}
        ),
        trace_root("ingest.file", attributes={}),
    ):
        pass

    root = finished()["ingest.file"]
    assert root.attributes[LF.TRACE_USER_ID] == "user-2"
    assert root.attributes[LF.TRACE_SESSION_ID] == "task-2"
    assert _trace_metadata(root, "openrag.task_id") == "task-2"


def test_stage_spans_carry_the_trace_metadata(finished):
    with trace_root("ingest.file", attributes={"openrag.document_id": "doc-1"}):
        with trace_span("ingest.embed"):
            pass

    assert _trace_metadata(finished()["ingest.embed"], "openrag.document_id") == "doc-1"


def test_gateway_calls_inside_a_root_carry_its_user_session_and_attributes(finished):
    with trace_root(
        "ingest.file",
        user_id="user-1",
        session_id="task-1",
        attributes={"openrag.document_id": "doc-1"},
    ):
        metadata = gateway_trace_kwargs("embedding", "ingest")["metadata"]

    assert metadata["trace_user_id"] == "user-1"
    assert metadata["session_id"] == "task-1"
    assert metadata["trace_metadata"]["openrag.document_id"] == "doc-1"


# --- values ----------------------------------------------------------------


def test_set_records_openrag_metadata_and_merges(finished):
    with (
        trace_root("ingest.file", attributes={}),
        trace_span("ingest.resplit", chunk_size=1000) as span,
    ):
        span.set(chunks_in=4)
        span.set(chunks_out=9, skipped=None)

    resplit = finished()["ingest.resplit"]
    assert _metadata(resplit, "openrag.chunk_size") == 1000
    assert _metadata(resplit, "openrag.chunks_in") == 4
    assert _metadata(resplit, "openrag.chunks_out") == 9
    assert _metadata(resplit, "openrag.skipped") is None


def test_content_is_dropped_unless_capture_is_on(finished, monkeypatch):
    with trace_root("ingest.file", attributes={}) as root:
        root.set_content(filename="q3-salaries.pdf")
    with_capture_off = finished()["ingest.file"]
    assert "q3-salaries.pdf" not in str(dict(with_capture_off.attributes))

    monkeypatch.setattr(spans, "content_capture_enabled", lambda: True)
    with trace_root("ingest.file", attributes={}) as root:
        root.set_content(filename="q3-salaries.pdf")
    assert _metadata(finished()["ingest.file"], "openrag.filename") == "q3-salaries.pdf"


# --- failures --------------------------------------------------------------


def test_a_failing_stage_marks_itself_and_the_trace_and_reraises(finished):
    with pytest.raises(ValueError):
        with trace_root("ingest.file", attributes={}), trace_span("ingest.embed"):
            raise ValueError("chunk text: the quarterly salaries are")

    exported = finished()
    embed, root = exported["ingest.embed"], exported["ingest.file"]
    assert embed.attributes[LF.OBSERVATION_LEVEL] == "ERROR"
    assert embed.attributes[LF.OBSERVATION_STATUS_MESSAGE] == "ValueError"
    assert root.attributes[LF.OBSERVATION_LEVEL] == "ERROR"
    assert root.attributes[LF.OBSERVATION_STATUS_MESSAGE] == "ValueError in ingest.embed"


def test_exception_text_stays_out_of_spans_unless_capture_is_on(finished):
    with pytest.raises(ValueError):
        with trace_root("ingest.file", attributes={}), trace_span("ingest.embed"):
            raise ValueError("chunk text: the quarterly salaries are")

    for span in finished().values():
        assert "quarterly salaries" not in str(dict(span.attributes))
        assert not any(event.name == "exception" for event in span.events)


def test_exception_text_is_kept_when_capture_is_on(finished, monkeypatch):
    monkeypatch.setattr(spans, "content_capture_enabled", lambda: True)

    with pytest.raises(ValueError), trace_root("ingest.file", attributes={}):
        raise ValueError("bad page 3")

    root = finished()["ingest.file"]
    assert root.attributes[LF.OBSERVATION_STATUS_MESSAGE] == "ValueError: bad page 3"


def test_fail_marks_a_span_without_an_exception(finished):
    with trace_root("ingest.file", attributes={}) as root:
        root.fail("NoEmbeddings")

    root_span = finished()["ingest.file"]
    assert root_span.attributes[LF.OBSERVATION_LEVEL] == "ERROR"
    assert root_span.attributes[LF.OBSERVATION_STATUS_MESSAGE] == "NoEmbeddings"
    assert _metadata(root_span, "openrag.error_type") == "NoEmbeddings"
