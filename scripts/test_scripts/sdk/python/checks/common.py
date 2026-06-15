"""Helpers shared by check modules."""

from __future__ import annotations

import inspect
import uuid
from pathlib import Path

from harness import Context


def supports_delete_by_filter_id(client) -> bool:
    """documents.delete(filter_id=...) was added in openrag-sdk 0.4.0."""
    return "filter_id" in inspect.signature(client.documents.delete).parameters


def make_doc(ctx: Context, label: str, body: str) -> tuple[Path, str]:
    """Write a uniquely-named markdown file into the run's temp dir.

    Returns (path, token) where token is a unique hex string embedded in the
    document so search checks can target this exact file.
    """
    token = uuid.uuid4().hex
    path = Path(ctx.shared["tmpdir"]) / f"sdk_smoke_{label}_{token[:8]}.md"
    path.write_text(f"# SDK Smoke Test ({label})\n\nToken: {token}\n\n{body}\n")
    return path, token


def register_doc_cleanup(ctx: Context, filename: str) -> None:
    """Best-effort delete of an ingested document after the run."""
    ctx.add_cleanup(
        f"delete document {filename}",
        lambda: ctx.client.documents.delete(filename),
    )
