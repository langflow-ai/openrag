"""Unit tests for ``utils.logging_config`` — production JSON logs must never
serialize exception-frame locals, since those routinely hold API keys, JWTs,
and other request headers (see src/agent.py's extra_headers/request_params)."""

import io
import json

import structlog

from utils import logging_config

FAKE_SECRET = "sk-test-should-not-leak-0123456789"


def _raise_with_secret():
    api_key = FAKE_SECRET  # noqa: F841 - intentionally kept as a local
    raise ValueError("boom")


def _capture_json_exception_log() -> dict:
    logging_config.configure_logging(json_logs=True, include_timestamps=False)
    stream = io.StringIO()
    structlog.configure(
        processors=structlog.get_config()["processors"],
        wrapper_class=structlog.get_config()["wrapper_class"],
        context_class=dict,
        logger_factory=structlog.WriteLoggerFactory(stream),
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger()
    try:
        _raise_with_secret()
    except ValueError:
        logger.exception("something failed")
    return json.loads(stream.getvalue())


def test_json_exception_logs_do_not_leak_locals():
    event = _capture_json_exception_log()

    raw = json.dumps(event)
    assert FAKE_SECRET not in raw

    exception = event["exception"]
    assert exception, "expected a rendered exception traceback"
    for stack in exception:
        for frame in stack.get("frames", []):
            assert not frame.get("locals"), (
                f"frame {frame.get('name')} unexpectedly serialized locals: {frame.get('locals')}"
            )


def test_json_exception_logs_still_include_frame_identity():
    event = _capture_json_exception_log()

    exception = event["exception"]
    frame_names = [f.get("name") for stack in exception for f in stack.get("frames", [])]
    assert "_raise_with_secret" in frame_names
    assert exception[0]["exc_type"] == "ValueError"
