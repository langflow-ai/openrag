"""Unit tests for services.component_logs.

Covers: ring buffer behaviour, record_check_result() transition logic,
get_entries() tail slicing, redaction of sensitive values and Bearer tokens.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import services.component_logs as cl  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_buffer():
    """Clear all buffer state before every test so tests are independent."""
    cl._buffers.clear()
    cl._locks.clear()
    cl._last_ok.clear()
    yield
    cl._buffers.clear()
    cl._locks.clear()
    cl._last_ok.clear()


# ---------------------------------------------------------------------------
# record() and get_entries() basics
# ---------------------------------------------------------------------------


def test_record_stores_entry():
    cl.record("langflow", "error", "down", detail="ConnectError")
    entries = cl.get_entries("langflow", tail=10)
    assert len(entries) == 1
    e = entries[0]
    assert e["level"] == "error"
    assert e["message"] == "down"
    assert e["detail"] == "ConnectError"
    assert "timestamp" in e


def test_get_entries_unknown_component_returns_empty():
    result = cl.get_entries("nope", tail=50)
    assert result == []


def test_get_entries_tail_slices_most_recent():
    for i in range(10):
        cl.record("opensearch", "error", f"msg-{i}")
    entries = cl.get_entries("opensearch", tail=3)
    assert len(entries) == 3
    # Last three messages
    assert entries[-1]["message"] == "msg-9"
    assert entries[0]["message"] == "msg-7"


def test_get_entries_tail_larger_than_buffer_returns_all():
    cl.record("docling", "error", "one")
    cl.record("docling", "error", "two")
    assert len(cl.get_entries("docling", tail=500)) == 2


def test_buffer_respects_maxlen():
    """Oldest entries are evicted once maxlen is hit."""
    for i in range(cl.BUFFER_MAXLEN + 5):
        cl.record("langflow", "error", f"msg-{i}")
    entries = cl.get_entries("langflow", tail=cl.BUFFER_MAXLEN + 5)
    assert len(entries) == cl.BUFFER_MAXLEN
    # First entry should be msg-5 (the first five were evicted)
    assert entries[0]["message"] == "msg-5"


def test_entries_oldest_to_newest_order():
    for i in range(5):
        cl.record("openrag", "warning", f"w{i}")
    msgs = [e["message"] for e in cl.get_entries("openrag", tail=10)]
    assert msgs == ["w0", "w1", "w2", "w3", "w4"]


def test_separate_components_have_independent_buffers():
    cl.record("langflow", "error", "langflow-err")
    cl.record("docling", "error", "docling-err")
    assert cl.get_entries("langflow", 10)[0]["message"] == "langflow-err"
    assert cl.get_entries("docling", 10)[0]["message"] == "docling-err"
    assert len(cl.get_entries("opensearch", 10)) == 0


# ---------------------------------------------------------------------------
# record_check_result() transition logic
# ---------------------------------------------------------------------------


def test_failure_always_records():
    cl.record_check_result("langflow", False, "down", detail="err")
    entries = cl.get_entries("langflow", 10)
    assert len(entries) == 1
    assert entries[0]["level"] == "error"


def test_repeated_failures_all_recorded():
    for _ in range(3):
        cl.record_check_result("langflow", False, "still down")
    assert len(cl.get_entries("langflow", 10)) == 3


def test_healthy_after_healthy_records_nothing():
    """Steady-state healthy should not write anything."""
    cl.record_check_result("langflow", True, "ok")
    cl.record_check_result("langflow", True, "ok")
    assert cl.get_entries("langflow", 10) == []


def test_recovery_transition_writes_one_info_entry():
    """False→True transition: exactly one info 'recovered' entry."""
    cl.record_check_result("opensearch", False, "cluster red")
    cl.record_check_result("opensearch", True, "cluster green")
    entries = cl.get_entries("opensearch", 10)
    assert len(entries) == 2  # 1 error + 1 info
    assert entries[0]["level"] == "error"
    assert entries[1]["level"] == "info"
    assert "recovered" in entries[1]["message"]


def test_no_recovery_entry_when_first_call_is_healthy():
    """The very first call with ok=True (no prior failure) records nothing."""
    cl.record_check_result("docling", True, "reachable")
    assert cl.get_entries("docling", 10) == []


def test_healthy_after_recovery_records_nothing_more():
    """After a recovery entry, subsequent healthy calls are still silent."""
    cl.record_check_result("langflow", False, "down")
    cl.record_check_result("langflow", True, "up")   # recovery → 1 info
    cl.record_check_result("langflow", True, "up")   # steady healthy → nothing
    cl.record_check_result("langflow", True, "up")
    assert len(cl.get_entries("langflow", 10)) == 2  # still just error + recovery


def test_second_failure_after_recovery_is_recorded():
    """Failure → recovery → failure again: second failure should be recorded."""
    cl.record_check_result("opensearch", False, "down1")     # error
    cl.record_check_result("opensearch", True, "up")         # info recovery
    cl.record_check_result("opensearch", False, "down2")     # error again
    entries = cl.get_entries("opensearch", 10)
    assert len(entries) == 3
    levels = [e["level"] for e in entries]
    assert levels == ["error", "info", "error"]


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_bearer_token_in_detail_is_redacted():
    cl.record("openrag", "error", "auth failed", detail="Authorization: Bearer abc123token")
    detail = cl.get_entries("openrag", 1)[0]["detail"]
    assert "abc123token" not in detail
    assert "Bearer ***" in detail


def test_redact_dict_masks_sensitive_keys():
    safe = cl._redact_dict({"api_key": "sk-secret", "message": "hello", "token": "xyz"})
    assert safe["api_key"] == "***"
    assert safe["token"] == "***"
    assert safe["message"] == "hello"


def test_redact_dict_strips_bearer_from_string_values():
    safe = cl._redact_dict({"info": "header: Bearer supersecret rest"})
    assert "supersecret" not in safe["info"]
    assert "Bearer ***" in safe["info"]


def test_detail_none_stored_as_none():
    cl.record("docling", "error", "fail", detail=None)
    assert cl.get_entries("docling", 1)[0]["detail"] is None
