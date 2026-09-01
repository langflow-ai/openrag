"""The gateway's record of what real traffic hit.

The health banner used to show only what its own probe hit, and a probe cannot
reproduce the request that failed — OpenAI checks request shape before billing,
so a probe reports "no credits remaining" while the agent's own call reports a
400 about its parameters. These pin that the record follows real calls and
does not outlive them.
"""

from __future__ import annotations

import pytest

from services import provider_error_log


@pytest.fixture(autouse=True)
def _clean():
    provider_error_log.clear()
    yield
    provider_error_log.clear()


def test_a_failure_is_readable_until_the_next_success():
    provider_error_log.record_failure("openai", "chat", "gpt-5.6-luna: bad params")
    assert provider_error_log.latest_failure("openai", "chat") == "gpt-5.6-luna: bad params"

    provider_error_log.record_success("openai", "chat")
    assert provider_error_log.latest_failure("openai", "chat") is None


def test_chat_and_embedding_are_recorded_apart():
    """One kind recovering must not clear the other's still-live failure."""
    provider_error_log.record_failure("openai", "chat", "chat is broken")
    provider_error_log.record_failure("openai", "embedding", "embedding is broken")

    provider_error_log.record_success("openai", "chat")

    assert provider_error_log.latest_failure("openai", "chat") is None
    assert provider_error_log.latest_failure("openai", "embedding") == "embedding is broken"


def test_providers_do_not_share_a_record():
    provider_error_log.record_failure("openai", "chat", "openai is broken")
    assert provider_error_log.latest_failure("anthropic", "chat") is None


def test_the_provider_name_is_matched_loosely():
    provider_error_log.record_failure("  OpenAI ", "chat", "boom")
    assert provider_error_log.latest_failure("openai", "chat") == "boom"


def test_a_failure_nobody_reproduces_stops_speaking(monkeypatch):
    """A provider that fails and is then never called again must not pin the banner."""
    provider_error_log.record_failure("openai", "chat", "boom")

    clock = [0.0]
    monkeypatch.setattr(provider_error_log.time, "monotonic", lambda: clock[0])
    provider_error_log.record_failure("openai", "chat", "boom")

    clock[0] = provider_error_log.STALE_AFTER_SECONDS - 1
    assert provider_error_log.latest_failure("openai", "chat") == "boom"

    clock[0] = provider_error_log.STALE_AFTER_SECONDS + 1
    assert provider_error_log.latest_failure("openai", "chat") is None


def test_nothing_is_recorded_without_a_provider_or_a_message():
    provider_error_log.record_failure("", "chat", "boom")
    provider_error_log.record_failure("openai", "chat", "")
    assert provider_error_log.latest_failure("openai", "chat") is None
    assert provider_error_log.latest_failure(None, "chat") is None
