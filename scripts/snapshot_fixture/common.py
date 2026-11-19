"""Shared helpers for the snapshot import fixture scripts (stdlib only)."""

from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent
DATA_DIR = FIXTURE_DIR / "data"
COMPOSE_FILE = FIXTURE_DIR / "docker-compose.yml"
SOURCE_CONTAINER = "openrag-snapshot-fixture-source-opensearch-1"


class OpenSearchError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"OpenSearch returned HTTP {status}: {body}")
        self.status = status
        self.body = body


@dataclass
class OpenSearch:
    """Minimal JSON client for the source cluster."""

    url: str
    username: str | None = None
    password: str | None = None
    verify_tls: bool = True

    def request(self, method: str, path: str, body: Any = None, *, ndjson: bool = False) -> Any:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            if ndjson:
                data = body.encode()
                headers["Content-Type"] = "application/x-ndjson"
            else:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
        if self.username:
            token = base64.b64encode(f"{self.username}:{self.password or ''}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        req = urllib.request.Request(
            self.url.rstrip("/") + path, data=data, headers=headers, method=method
        )
        context = None
        if self.url.startswith("https") and not self.verify_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, context=context, timeout=300) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = raw.decode(errors="replace")
            raise OpenSearchError(exc.code, parsed) from None
        return json.loads(raw) if raw else None

    def wait_until_ready(self, timeout_s: float = 180) -> dict:
        deadline = time.monotonic() + timeout_s
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                health = self.request("GET", "/_cluster/health")
                if health.get("status") in ("green", "yellow"):
                    return health
            except (OSError, OpenSearchError) as exc:
                last_error = exc
            time.sleep(2)
        raise TimeoutError(f"OpenSearch at {self.url} not ready after {timeout_s}s: {last_error}")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
