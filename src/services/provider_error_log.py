"""The most recent real provider failure, per provider and call kind.

The health banner reports what a synthetic probe hit, and a probe cannot
reproduce the request that actually failed. OpenAI validates request shape
before it checks billing, so a plain probe completion comes back "You have no
credits remaining" while the agent's own call — function tools plus
``reasoning_effort`` — comes back a 400 about the parameters. Both are true.
The one the operator needs is the one their own traffic produced.

So the gateway records what it saw. An entry is written when a call fails and
erased when the next call on the same provider and kind succeeds, which means
its presence says traffic is failing *now* rather than that it once did.
``STALE_AFTER_SECONDS`` covers the remaining case: a provider that fails and
is then never called again would otherwise pin the banner forever.

In-process and per-worker, deliberately. This is a diagnostic for the operator
watching the console, not a durable record — an entry that is lost on restart
is one whose failure has not recurred.
"""

from __future__ import annotations

import time
from typing import Literal

CallKind = Literal["chat", "embedding"]

#: How long a recorded failure keeps speaking for a provider that has gone
#: quiet. Long enough to survive the banner's polling gap, short enough that a
#: failure nobody is reproducing stops being news.
STALE_AFTER_SECONDS = 15 * 60

# (provider, kind) -> (monotonic timestamp, client-facing message)
_failures: dict[tuple[str, str], tuple[float, str]] = {}


def _key(provider: str, kind: CallKind) -> tuple[str, str]:
    return ((provider or "").strip().lower(), kind)


def record_failure(provider: str, kind: CallKind, message: str) -> None:
    """Remember why a real call to `provider` failed.

    `message` is the text already shown to the caller, so the banner and the
    chat bubble cannot disagree about what went wrong.
    """
    if not provider or not message:
        return
    _failures[_key(provider, kind)] = (time.monotonic(), message)


def record_success(provider: str, kind: CallKind) -> None:
    """Forget any recorded failure: this provider is serving traffic again."""
    _failures.pop(_key(provider, kind), None)


def latest_failure(provider: str | None, kind: CallKind) -> str | None:
    """The last real failure for `provider`, if one is still current."""
    if not provider:
        return None
    entry = _failures.get(_key(provider, kind))
    if entry is None:
        return None
    recorded_at, message = entry
    if time.monotonic() - recorded_at > STALE_AFTER_SECONDS:
        _failures.pop(_key(provider, kind), None)
        return None
    return message


def clear() -> None:
    """Drop every recorded failure. For tests."""
    _failures.clear()
