"""Opaque keyset cursors for the Activity endpoints.

A cursor carries the last ``(timestamp, id)`` pair, the frozen upper time
bound taken at the first page, and a digest of the normalised filters it was
issued for. Reusing it with different filters, or tampering with it, is a 422.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException


@dataclass(frozen=True)
class Cursor:
    ts: datetime
    id: str
    upper: datetime


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def filters_digest(filters: dict) -> str:
    canonical = json.dumps(filters, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def encode_cursor(ts: datetime, row_id: str, upper: datetime, filters: dict) -> str:
    payload = {
        "t": _utc(ts).isoformat(),
        "i": row_id,
        "u": _utc(upper).isoformat(),
        "f": filters_digest(filters),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def decode_cursor(value: str, filters: dict) -> Cursor:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
        cursor = Cursor(
            ts=_utc(datetime.fromisoformat(payload["t"])),
            id=str(payload["i"]),
            upper=_utc(datetime.fromisoformat(payload["u"])),
        )
        digest = payload["f"]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_cursor"}) from exc
    if digest != filters_digest(filters):
        raise HTTPException(status_code=422, detail={"error": "cursor_filter_mismatch"})
    return cursor
