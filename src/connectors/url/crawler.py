"""Scrapy subprocess adapter for the managed URL connector.

Scrapy runs outside the backend event loop so its Twisted reactor cannot affect
FastAPI. The subprocess is still owned by the existing TaskService task: it
uses a temporary work directory and returns the same ``CrawlResult`` consumed
by the native ingestion pipeline.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .document import WebDocument, html_to_document
from .policy import CrawlSpec


@dataclass(frozen=True)
class CrawledPage:
    canonical_url: str
    final_url: str
    depth: int
    document: WebDocument | None
    noindex: bool = False
    error: str | None = None


@dataclass(frozen=True)
class CrawlResult:
    pages: tuple[CrawledPage, ...]
    complete: bool
    capped: bool
    reason: str | None = None


async def _stop(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()


def _failure_reason(stderr: bytes) -> str:
    detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
    if detail:
        return f"Scrapy crawler failed: {detail[-1][:500]}"
    return "Scrapy crawler failed"


def _page(record: dict[str, Any], work_dir: Path) -> CrawledPage:
    canonical_url = str(record["canonical_url"])
    final_url = str(record.get("final_url") or canonical_url)
    error = record.get("error")
    document: WebDocument | None = None
    content_path = record.get("content_path")
    if not error and content_path:
        try:
            content = (work_dir / str(content_path)).read_bytes()
            document = html_to_document(content, final_url)
        except (OSError, ValueError) as exc:
            error = str(exc)
    return CrawledPage(
        canonical_url=canonical_url,
        final_url=final_url,
        depth=int(record["depth"]),
        document=document,
        noindex=bool(record.get("noindex", False)),
        error=str(error) if error else None,
    )


def _result(work_dir: Path) -> CrawlResult:
    manifest = json.loads((work_dir / "result.json").read_text(encoding="utf-8"))
    return CrawlResult(
        pages=tuple(_page(record, work_dir) for record in manifest.get("pages", [])),
        complete=bool(manifest.get("complete", False)),
        capped=bool(manifest.get("capped", False)),
        reason=manifest.get("reason"),
    )


async def crawl(spec: CrawlSpec) -> CrawlResult:
    """Run one bounded website crawl in the backend's existing task process."""

    with tempfile.TemporaryDirectory(prefix="openrag-url-crawl-") as directory:
        work_dir = Path(directory)
        environment = os.environ.copy()
        source_root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = os.pathsep.join(
            value for value in (source_root, environment.get("PYTHONPATH")) if value
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "connectors.url.scrapy_runner",
            "--output-dir",
            str(work_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(spec.as_dict()).encode()),
                timeout=spec.max_crawl_minutes * 60 + 30,
            )
        except TimeoutError:
            await _stop(process)
            return CrawlResult((), complete=False, capped=True, reason="safety limit reached")
        except asyncio.CancelledError:
            await _stop(process)
            raise

        if process.returncode:
            return CrawlResult((), complete=False, capped=False, reason=_failure_reason(stderr))
        try:
            return _result(work_dir)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return CrawlResult(
                (), complete=False, capped=False, reason=f"Scrapy crawler returned no result: {exc}"
            )
