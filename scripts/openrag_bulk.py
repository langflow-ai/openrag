#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.25.0,<1"]
# ///
"""Standalone bulk ingestion and arXiv benchmark client for OpenRAG.

The script intentionally imports no OpenRAG application or SDK modules. This keeps it
usable from a checkout, a Kubernetes job, or a machine that only has ``uv`` installed.
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import unquote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from uuid import uuid4

import httpx

TERMINAL_TASK_STATUSES = {"completed", "failed", "skipped"}
TRANSIENT_HTTP_STATUSES = {502, 503, 504}
DEFAULT_RUNS_DIR = Path("~/.openrag/bulk/runs")
DEFAULT_ARXIV_DIR = Path("~/.openrag/benchmarks/arxiv")
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
DEFAULT_ARXIV_CATEGORY = "cs.CL"
DEFAULT_ARXIV_DATE_FROM = "2025-01-01"
DEFAULT_ARXIV_DATE_TO = "2025-12-31"
DEFAULT_ARXIV_SOURCE = "s3"
DEFAULT_ARXIV_S3_URI = "s3://arxiv/pdf/arXiv_pdf_1001_001.tar"


class ApiError(RuntimeError):
    """An OpenRAG API request failed."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class ArxivBenchmarkError(RuntimeError):
    """The arXiv source could not be staged safely."""


@dataclass(frozen=True)
class BulkUploadItem:
    path: Path
    filename: str | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class BulkUploadOptions:
    batch_size: int = 10
    max_inflight: int = 1
    max_submit: int | None = None
    request_timeout: float = 300.0
    poll_request_timeout: float = 10.0
    task_timeout: float = 1800.0
    poll_interval: float = 1.0
    progress_interval: float = 5.0
    summary_interval: float = 60.0
    input_sort: str = "path"
    settings_json: str | None = None
    tweaks_json: str | None = None
    replace_duplicates: bool = True

    def validate(self) -> None:
        positive = {
            "batch_size": self.batch_size,
            "max_inflight": self.max_inflight,
            "request_timeout": self.request_timeout,
            "poll_request_timeout": self.poll_request_timeout,
            "task_timeout": self.task_timeout,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_submit is not None and self.max_submit <= 0:
            raise ValueError("max_submit must be positive")
        for name, value in {
            "poll_interval": self.poll_interval,
            "progress_interval": self.progress_interval,
            "summary_interval": self.summary_interval,
        }.items():
            if value < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class ArxivPaper:
    arxiv_id: str
    title: str
    summary: str
    authors: tuple[str, ...]
    published: str | None
    updated: str | None
    abs_url: str
    pdf_url: str


@dataclass(frozen=True)
class DownloadedPaper:
    paper: ArxivPaper
    path: Path
    size: int
    sha256: str
    cached: bool = False


class RateLimiter:
    def __init__(self, delay_seconds: float):
        self.delay_seconds = max(delay_seconds, 0.0)
        self.last_request: float | None = None

    def wait(self) -> None:
        if self.last_request is not None:
            remaining = self.delay_seconds - (time.monotonic() - self.last_request)
            if remaining > 0:
                time.sleep(remaining)
        self.last_request = time.monotonic()


class ProgressReporter:
    def __init__(
        self,
        *,
        enabled: bool = True,
        started: float | None = None,
        prefix: str = "openrag bulk",
        stream=None,
    ) -> None:
        self.enabled = enabled
        self.started = time.monotonic() if started is None else started
        self.prefix = prefix
        self.stream = stream or sys.stderr

    def log(self, message: str) -> None:
        if not self.enabled:
            return
        elapsed = time.monotonic() - self.started
        print(f"{self.prefix} [{elapsed:8.1f}s] {message}", file=self.stream, flush=True)


class OpenRAGApiClient:
    """Small API client covering only the two calls bulk ingestion needs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_prefix: str = "/api/v1",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        root = base_url.rstrip("/")
        prefix = "/" + api_prefix.strip("/") if api_prefix.strip("/") else ""
        self._base_url = root + prefix
        self._http = httpx.AsyncClient(
            headers={"X-API-Key": api_key},
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> OpenRAGApiClient:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.close()

    async def submit_batch(
        self,
        items: Sequence[BulkUploadItem],
        *,
        settings_json: str | None,
        tweaks_json: str | None,
        replace_duplicates: bool,
        timeout: float,
    ) -> dict[str, Any]:
        data: dict[str, str] = {
            "replace_duplicates": str(replace_duplicates).lower(),
        }
        if settings_json is not None:
            data["settings"] = settings_json
        if tweaks_json is not None:
            data["tweaks"] = tweaks_json

        with ExitStack() as stack:
            files = [
                (
                    "file",
                    (
                        item.filename or item.path.name,
                        stack.enter_context(item.path.open("rb")),
                        item.content_type
                        or mimetypes.guess_type(item.filename or item.path.name)[0]
                        or "application/octet-stream",
                    ),
                )
                for item in items
            ]
            response = await self._http.post(
                f"{self._base_url}/documents/ingest",
                data=data,
                files=files,
                timeout=timeout,
            )
        return _response_json(response)

    async def get_task_status(self, task_id: str, *, timeout: float) -> dict[str, Any]:
        response = await self._http.get(
            f"{self._base_url}/tasks/{task_id}",
            timeout=timeout,
        )
        return _response_json(response)


SummaryCallback = Callable[[dict[str, Any]], Any]


def collect_upload_items(
    paths: Sequence[str],
    *,
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
    recursive: bool = True,
) -> list[BulkUploadItem]:
    include_patterns = list(include or ["*"])
    exclude_patterns = list(exclude or [])
    items: list[BulkUploadItem] = []
    seen: set[Path] = set()

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if path.is_file():
            root = path.parent
            candidates = [path]
        elif path.is_dir():
            root = path
            iterator = path.rglob("*") if recursive else path.glob("*")
            candidates = [candidate for candidate in iterator if candidate.is_file()]
        else:
            raise FileNotFoundError(f"bulk upload path not found: {raw_path}")

        for candidate in sorted(candidates):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            relative = candidate.name if path.is_file() else str(candidate.relative_to(root))
            if not _matches(relative, candidate.name, include_patterns):
                continue
            if _matches(relative, candidate.name, exclude_patterns):
                continue
            seen.add(resolved)
            items.append(BulkUploadItem(path=resolved))

    return items


def sort_upload_items(items: Sequence[BulkUploadItem], order: str) -> list[BulkUploadItem]:
    if order == "path":
        return sorted(items, key=lambda item: str(item.path))
    if order == "size-asc":
        return sorted(items, key=lambda item: (item.path.stat().st_size, str(item.path)))
    if order == "size-desc":
        return sorted(items, key=lambda item: (-item.path.stat().st_size, str(item.path)))
    raise ValueError(f"unsupported bulk upload sort: {order}")


async def upload_bulk_items(
    *,
    client: Any,
    items: Sequence[BulkUploadItem],
    options: BulkUploadOptions,
    progress: ProgressReporter,
    summary_callback: SummaryCallback | None = None,
) -> dict[str, Any]:
    """Submit batches concurrently, poll each task, and return a run summary."""
    options.validate()
    batches = _chunks(list(items), options.batch_size)
    max_submit = min(options.max_inflight, options.max_submit or options.max_inflight)
    total_bytes = sum(item.path.stat().st_size for item in items)
    summary: dict[str, Any] = {
        "total_files": len(items),
        "total_bytes": total_bytes,
        "total_mb": round(_mb(total_bytes), 3),
        "batch_size": options.batch_size,
        "max_inflight": options.max_inflight,
        "max_submit": max_submit,
        "input_sort": options.input_sort,
        "replace_duplicates": options.replace_duplicates,
        "client_concurrency": {
            "batch_size": options.batch_size,
            "max_inflight_upload_tasks": options.max_inflight,
            "max_inflight_submit_requests": max_submit,
            "request_timeout_seconds": options.request_timeout,
            "poll_request_timeout_seconds": options.poll_request_timeout,
            "task_timeout_seconds": options.task_timeout,
            "poll_interval_seconds": options.poll_interval,
        },
        "batches": [
            _new_batch_result(batch, batch_index=index)
            for index, batch in enumerate(batches, start=1)
        ],
    }
    _notify(summary_callback, summary)
    if not batches:
        return summary

    progress.log(
        f"starting files={len(items)} batches={len(batches)} "
        f"batch_size={options.batch_size} max_inflight={options.max_inflight} "
        f"max_submit={max_submit} input_mb={_mb(total_bytes):.2f}"
    )
    inflight_semaphore = asyncio.Semaphore(options.max_inflight)
    submit_semaphore = asyncio.Semaphore(max_submit)
    finished = asyncio.Event()

    async def process_batch(index: int, batch: list[BulkUploadItem]) -> None:
        result = summary["batches"][index - 1]
        async with inflight_semaphore:
            result.update(status="submitting", phase="multipart_upload")
            _notify(summary_callback, summary)
            submitted_at = time.monotonic()
            try:
                async with submit_semaphore:
                    response = await client.submit_batch(
                        batch,
                        settings_json=options.settings_json,
                        tweaks_json=options.tweaks_json,
                        replace_duplicates=options.replace_duplicates,
                        timeout=options.request_timeout,
                    )
                task_id = str(response["task_id"])
                submit_seconds = round(time.monotonic() - submitted_at, 3)
                result.update(
                    task_id=task_id,
                    status=str(response.get("status") or "accepted"),
                    phase="task_poll",
                    submit_seconds=submit_seconds,
                )
                progress.log(
                    f"batch {index}/{len(batches)} submitted task_id={task_id} "
                    f"files={len(batch)} submit_seconds={submit_seconds:.3f}"
                )
                _notify(summary_callback, summary)
            except Exception as exc:
                result.update(
                    status="failed",
                    phase="multipart_upload",
                    duration_seconds=round(time.monotonic() - submitted_at, 3),
                    error=_error_text(exc),
                )
                progress.log(f"batch {index}/{len(batches)} submit failed: {_error_text(exc)}")
                _notify(summary_callback, summary)
                return

            await _poll_batch(
                client=client,
                result=result,
                batch_count=len(batches),
                options=options,
                progress=progress,
                summary=summary,
                summary_callback=summary_callback,
            )

    async def report_summary() -> None:
        if options.summary_interval == 0:
            return
        while not finished.is_set():
            try:
                await asyncio.wait_for(finished.wait(), timeout=options.summary_interval)
            except TimeoutError:
                progress.log(format_summary_progress(summary))

    reporter = asyncio.create_task(report_summary())
    try:
        await asyncio.gather(
            *(process_batch(index, batch) for index, batch in enumerate(batches, start=1))
        )
    finally:
        finished.set()
        await reporter

    _update_summary_totals(summary)
    _notify(summary_callback, summary)
    return summary


async def _poll_batch(
    *,
    client: Any,
    result: dict[str, Any],
    batch_count: int,
    options: BulkUploadOptions,
    progress: ProgressReporter,
    summary: dict[str, Any],
    summary_callback: SummaryCallback | None,
) -> None:
    task_id = str(result["task_id"])
    started = time.monotonic()
    last_log = 0.0
    last_snapshot: tuple[Any, ...] | None = None
    poll_errors = 0

    while True:
        if time.monotonic() - started >= options.task_timeout:
            result.update(
                status="failed",
                phase="task_poll",
                duration_seconds=round(time.monotonic() - started, 3),
                error=f"task did not finish within {options.task_timeout:g}s",
            )
            progress.log(f"batch {result['batch_index']}/{batch_count} task {task_id} timed out")
            _notify(summary_callback, summary)
            return

        try:
            status = await client.get_task_status(
                task_id,
                timeout=options.poll_request_timeout,
            )
            poll_errors = 0
        except Exception as exc:
            if not _is_transient_error(exc):
                result.update(
                    status="failed",
                    phase="task_poll",
                    duration_seconds=round(time.monotonic() - started, 3),
                    error=_error_text(exc),
                )
                progress.log(
                    f"batch {result['batch_index']}/{batch_count} task {task_id} "
                    f"poll failed: {_error_text(exc)}"
                )
                _notify(summary_callback, summary)
                return
            poll_errors += 1
            now = time.monotonic()
            if _should_log(now, last_log, options.progress_interval):
                progress.log(
                    f"batch {result['batch_index']}/{batch_count} task {task_id} "
                    f"poll_error_count={poll_errors} error={_error_text(exc)}"
                )
                last_log = now
            await asyncio.sleep(options.poll_interval)
            continue

        _update_batch_from_status(result, status)
        _notify(summary_callback, summary)
        snapshot = _status_snapshot(status)
        now = time.monotonic()
        if (
            str(status.get("status")) in TERMINAL_TASK_STATUSES
            or snapshot != last_snapshot
            or _should_log(now, last_log, options.progress_interval)
        ):
            progress.log(
                f"batch {result['batch_index']}/{batch_count} task {task_id} "
                f"{format_task_progress(status)}"
            )
            last_log = now
            last_snapshot = snapshot

        if str(status.get("status")) in TERMINAL_TASK_STATUSES:
            return
        await asyncio.sleep(options.poll_interval)


def bulk_failed(summary: dict[str, Any]) -> bool:
    return any(
        batch.get("status") != "completed" or _int_value(batch.get("failed_files")) > 0
        for batch in summary.get("batches") or []
    )


def format_task_progress(status: dict[str, Any]) -> str:
    values = [f"status={status.get('status')}", f"phase={_task_phase(status)}"]
    for label in (
        "processed_files",
        "total_files",
        "successful_files",
        "failed_files",
        "running_files",
        "pending_files",
    ):
        if status.get(label) is not None:
            values.append(f"{label.removesuffix('_files')}={status[label]}")
    error = _task_error(status)
    if error:
        values.append(f"error={error}")
    return " ".join(values)


def format_summary_progress(summary: dict[str, Any]) -> str:
    statuses: dict[str, int] = {}
    processed = successful = failed = 0
    for batch in summary.get("batches") or []:
        status = str(batch.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        processed += _int_value(batch.get("processed_files"))
        successful += _int_value(batch.get("successful_files"))
        failed += _int_value(batch.get("failed_files"))
    counts = ",".join(f"{key}:{value}" for key, value in sorted(statuses.items()))
    return (
        f"summary batches={counts} files processed={processed}/{summary.get('total_files', 0)} "
        f"successful={successful} failed={failed}"
    )


def persist_summary(
    summary: dict[str, Any],
    *,
    output_dir: Path,
    run_id: str,
    started: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.json"
    summary.update(
        run_id=run_id,
        output_dir=str(output_dir),
        summary_path=str(summary_path),
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
    ordered = _ordered_summary(summary)
    temporary = output_dir / ".summary.json.tmp"
    temporary.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
    temporary.replace(summary_path)
    return ordered


def list_runs(runs_dir: Path, *, limit: int = 20) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    if runs_dir.is_dir():
        paths = sorted(
            (path for path in runs_dir.glob("*/summary.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if limit > 0:
            paths = paths[:limit]
        for path in paths:
            try:
                summary = _load_summary(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            records.append(_run_overview(summary, path))
    return {"runs_dir": str(runs_dir), "count": len(records), "runs": records}


def load_summary_reference(
    runs_dir: Path,
    reference: str | None,
    *,
    detail: bool,
) -> dict[str, Any]:
    value = (reference or "latest").strip()
    if value in {"latest", "current", "recent"}:
        listed = list_runs(runs_dir, limit=1)
        if not listed["runs"]:
            raise FileNotFoundError(f"no runs found under {runs_dir}")
        path = Path(listed["runs"][0]["summary_path"])
    else:
        candidate = Path(value).expanduser()
        if candidate.is_file():
            path = candidate
        elif candidate.is_dir():
            path = candidate / "summary.json"
        else:
            path = runs_dir / value / "summary.json"
    summary = _load_summary(path.resolve())
    if detail:
        return summary
    response = dict(summary)
    response.pop("batches", None)
    response["summary"] = _run_overview(summary, path.resolve())
    return response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bulk-load local files or benchmark OpenRAG ingestion.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bulk = subparsers.add_parser("bulk", help="Bulk-load local files and directories.")
    bulk_subparsers = bulk.add_subparsers(dest="bulk_action", required=True)

    upload = bulk_subparsers.add_parser("upload", help="Upload paths in concurrent batches.")
    upload.add_argument("paths", nargs="+")
    upload.add_argument("--base-url", default=os.getenv("OPENRAG_URL", "http://localhost:3000"))
    upload.add_argument("--api-key", default=os.getenv("OPENRAG_API_KEY"))
    upload.add_argument(
        "--api-prefix",
        default="/api/v1",
        help="Use /v1 when calling the backend directly (default: /api/v1).",
    )
    upload.add_argument("--batch-size", type=int, default=10)
    upload.add_argument("--max-inflight", type=int, default=1)
    upload.add_argument("--max-submit", type=int, default=None)
    upload.add_argument("--sort", choices=("path", "size-asc", "size-desc"), default="path")
    upload.add_argument("--include", action="append", default=None)
    upload.add_argument("--exclude", action="append", default=None)
    upload.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True)
    upload.add_argument("--settings-json", default=None, help="JSON object or @path to JSON.")
    upload.add_argument("--tweaks-json", default=None, help="JSON object or @path to JSON.")
    upload.add_argument(
        "--replace-duplicates",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    upload.add_argument("--task-timeout", type=float, default=1800.0)
    upload.add_argument("--request-timeout", type=float, default=300.0)
    upload.add_argument("--poll-request-timeout", type=float, default=10.0)
    upload.add_argument("--poll-interval", type=float, default=1.0)
    upload.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True)
    upload.add_argument("--progress-interval", type=float, default=5.0)
    upload.add_argument("--summary-interval", type=float, default=60.0)
    upload.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    upload.add_argument("--output-dir", default=None)
    upload.add_argument("--run-id", default=None)

    list_parser = bulk_subparsers.add_parser("list", help="List locally recorded bulk runs.")
    list_parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    list_parser.add_argument("--limit", type=int, default=20)

    summary = bulk_subparsers.add_parser("summary", help="Show a locally recorded run.")
    summary.add_argument("run", nargs="?", default=None)
    summary.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR))
    summary.add_argument("--detail", action="store_true")

    bench = subparsers.add_parser("bench", help="Run repeatable ingestion benchmarks.")
    bench_subparsers = bench.add_subparsers(dest="benchmark", required=True)
    arxiv = bench_subparsers.add_parser(
        "arxiv",
        help="Download arXiv PDFs and optionally bulk-ingest them.",
    )
    _add_arxiv_args(arxiv)
    arxiv_actions = arxiv.add_subparsers(dest="benchmark_action")
    arxiv_list = arxiv_actions.add_parser("list", help="List arXiv benchmark runs.")
    arxiv_list.add_argument("--runs-dir", default=str(DEFAULT_ARXIV_DIR / "runs"))
    arxiv_list.add_argument("--limit", type=int, default=20)
    arxiv_summary = arxiv_actions.add_parser("summary", help="Show an arXiv benchmark run.")
    arxiv_summary.add_argument("run", nargs="?", default=None)
    arxiv_summary.add_argument("--runs-dir", default=str(DEFAULT_ARXIV_DIR / "runs"))
    arxiv_summary.add_argument("--detail", action="store_true")
    return parser


def _add_arxiv_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source",
        choices=("s3", "atom"),
        default=DEFAULT_ARXIV_SOURCE,
        help="Use the S3 bulk PDF tarball (default) or the arXiv Atom API.",
    )
    parser.add_argument(
        "--query", default=None, help="Raw Atom API query; overrides category/dates."
    )
    parser.add_argument("--category", default=DEFAULT_ARXIV_CATEGORY)
    parser.add_argument("--date-from", default=DEFAULT_ARXIV_DATE_FROM)
    parser.add_argument("--date-to", default=DEFAULT_ARXIV_DATE_TO)
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument(
        "--sort-by",
        choices=("relevance", "lastUpdatedDate", "submittedDate"),
        default="submittedDate",
    )
    parser.add_argument(
        "--sort-order",
        choices=("ascending", "descending"),
        default="descending",
    )
    parser.add_argument("--s3-uri", default=DEFAULT_ARXIV_S3_URI)
    parser.add_argument("--s3-cache-dir", default=None)
    parser.add_argument("--aws-cli", default="aws")
    parser.add_argument("--s3-request-payer", default="requester")
    parser.add_argument("--pdf-cache-dir", default=None)
    parser.add_argument("--failed-download-cache", default=None)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--retry-failed-downloads", action="store_true")
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    parser.add_argument("--max-pdf-mb", type=int, default=50)
    parser.add_argument("--user-agent", default="openrag-arxiv-benchmark/0.1")
    parser.add_argument("--base-url", default=os.getenv("OPENRAG_URL", "http://localhost:3000"))
    parser.add_argument("--api-key", default=os.getenv("OPENRAG_API_KEY"))
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument(
        "--upload-sort",
        choices=("path", "size-asc", "size-desc"),
        default="path",
    )
    parser.add_argument("--max-inflight", type=int, default=1)
    parser.add_argument("--max-submit", type=int, default=None)
    parser.add_argument("--task-timeout", type=float, default=1800.0)
    parser.add_argument("--request-timeout", type=float, default=60.0)
    parser.add_argument("--poll-request-timeout", type=float, default=10.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--progress-interval", type=float, default=5.0)
    parser.add_argument("--summary-interval", type=float, default=60.0)
    parser.add_argument("--settings-json", default=None, help="JSON object or @path to JSON.")
    parser.add_argument("--tweaks-json", default=None, help="JSON object or @path to JSON.")
    parser.add_argument(
        "--replace-duplicates",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--runs-dir", default=str(DEFAULT_ARXIV_DIR / "runs"))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--run-id", default=None)


async def _upload_main(args: argparse.Namespace) -> int:
    if not args.api_key:
        raise ValueError("an API key is required; set OPENRAG_API_KEY or pass --api-key")
    settings_json = _json_argument(args.settings_json, "settings")
    tweaks_json = _json_argument(args.tweaks_json, "tweaks")
    items = collect_upload_items(
        args.paths,
        include=args.include,
        exclude=args.exclude,
        recursive=args.recursive,
    )
    items = sort_upload_items(items, args.sort)
    if not items:
        raise ValueError("no files matched")

    started = time.monotonic()
    run_id = args.run_id or _new_run_id()
    runs_dir = Path(args.runs_dir).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve() if args.output_dir else runs_dir / run_id
    )
    progress = ProgressReporter(enabled=args.progress, started=started)

    def save(summary: dict[str, Any]) -> dict[str, Any]:
        return persist_summary(
            summary,
            output_dir=output_dir,
            run_id=run_id,
            started=started,
        )

    options = BulkUploadOptions(
        batch_size=args.batch_size,
        max_inflight=args.max_inflight,
        max_submit=args.max_submit,
        request_timeout=args.request_timeout,
        poll_request_timeout=args.poll_request_timeout,
        task_timeout=args.task_timeout,
        poll_interval=args.poll_interval,
        progress_interval=args.progress_interval,
        summary_interval=args.summary_interval,
        input_sort=args.sort,
        settings_json=settings_json,
        tweaks_json=tweaks_json,
        replace_duplicates=args.replace_duplicates,
    )
    async with OpenRAGApiClient(
        base_url=args.base_url,
        api_key=args.api_key,
        api_prefix=args.api_prefix,
    ) as client:
        result = await upload_bulk_items(
            client=client,
            items=items,
            options=options,
            progress=progress,
            summary_callback=save,
        )
    result = save(result)
    progress.log(f"complete summary={result['summary_path']}")
    _print_json(result)
    return 1 if bulk_failed(result) else 0


def _validate_arxiv_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    positive = {
        "--max-results": args.max_results,
        "--batch-size": args.batch_size,
        "--max-inflight": args.max_inflight,
        "--request-timeout": args.request_timeout,
        "--poll-request-timeout": args.poll_request_timeout,
        "--task-timeout": args.task_timeout,
        "--max-pdf-mb": args.max_pdf_mb,
    }
    for name, value in positive.items():
        if value <= 0:
            parser.error(f"{name} must be positive")
    if args.max_submit is not None and args.max_submit <= 0:
        parser.error("--max-submit must be positive")
    if args.start < 0:
        parser.error("--start must be non-negative")
    for name in ("poll_interval", "progress_interval", "summary_interval", "delay_seconds"):
        if getattr(args, name) < 0:
            parser.error(f"--{name.replace('_', '-')} must be non-negative")
    try:
        if args.query is None:
            args.query = build_arxiv_query(
                category=args.category,
                date_from=args.date_from,
                date_to=args.date_to,
            )
    except ValueError as exc:
        parser.error(str(exc))
    if args.source == "s3" and not str(args.s3_uri or "").strip():
        parser.error("--s3-uri is required when --source=s3")


async def _arxiv_main(args: argparse.Namespace) -> int:
    if not args.download_only and not args.api_key:
        raise ValueError(
            "an API key is required unless --download-only is used; "
            "set OPENRAG_API_KEY or pass --api-key"
        )

    started = time.monotonic()
    run_id = args.run_id or _new_run_id()
    runs_dir = Path(args.runs_dir).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve() if args.output_dir else runs_dir / run_id
    )
    base_dir = runs_dir.parent
    pdf_dir = (
        Path(args.pdf_cache_dir).expanduser().resolve() if args.pdf_cache_dir else base_dir / "pdfs"
    )
    failure_cache_path = (
        Path(args.failed_download_cache).expanduser().resolve()
        if args.failed_download_cache
        else pdf_dir / "_failed_downloads.json"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    progress = ProgressReporter(
        enabled=args.progress,
        started=started,
        prefix="openrag bench arxiv",
    )
    progress.log(f"run_id={run_id} output_dir={output_dir} pdf_cache_dir={pdf_dir}")

    rate = RateLimiter(args.delay_seconds)
    source_ref = str(args.query)
    source_details: dict[str, Any] = {}
    if args.source == "s3":
        s3_cache_dir = (
            Path(args.s3_cache_dir).expanduser().resolve() if args.s3_cache_dir else base_dir / "s3"
        )
        source_ref = str(args.s3_uri)
        progress.log(
            f"staging S3 tarball uri={args.s3_uri} start={args.start} "
            f"max_results={args.max_results}"
        )
        downloads, download_errors, skipped_failures, source_details = stage_s3_papers(
            s3_uri=args.s3_uri,
            s3_cache_dir=s3_cache_dir,
            pdf_dir=pdf_dir,
            aws_cli=args.aws_cli,
            request_payer=args.s3_request_payer,
            start=args.start,
            max_results=args.max_results,
            max_pdf_bytes=args.max_pdf_mb * 1024 * 1024,
            skip_existing=args.skip_existing,
            progress=progress,
        )
        matched_papers = int(source_details.get("selected_pdf_members") or len(downloads))
    else:
        progress.log(
            f"fetching Atom metadata query={args.query!r} start={args.start} "
            f"max_results={args.max_results} sort={args.sort_by}:{args.sort_order}"
        )
        papers = fetch_arxiv_papers(
            query=args.query,
            start=args.start,
            max_results=args.max_results,
            sort_by=args.sort_by,
            sort_order=args.sort_order,
            rate=rate,
            user_agent=args.user_agent,
            timeout=args.request_timeout,
        )
        progress.log(f"metadata fetched matched_papers={len(papers)}")
        failure_cache = load_failed_download_cache(failure_cache_path)
        seeded = seed_failed_download_cache_from_summaries(runs_dir, source_ref=source_ref)
        for key, record in seeded.items():
            failure_cache.setdefault(key, record)
        if seeded:
            save_failed_download_cache(failure_cache_path, failure_cache)
        downloads, download_errors, skipped_failures = download_papers(
            papers,
            pdf_dir=pdf_dir,
            rate=rate,
            user_agent=args.user_agent,
            timeout=args.request_timeout,
            max_pdf_bytes=args.max_pdf_mb * 1024 * 1024,
            skip_existing=args.skip_existing,
            failure_cache=failure_cache,
            failure_cache_path=failure_cache_path,
            retry_failed=args.retry_failed_downloads,
            progress=progress,
        )
        matched_papers = len(papers)

    cached_papers = sum(item.cached for item in downloads)
    downloaded_papers = len(downloads) - cached_papers
    progress.log(
        f"PDF stage complete ready={len(downloads)} cached={cached_papers} "
        f"downloaded={downloaded_papers} skipped_failed={len(skipped_failures)} "
        f"errors={len(download_errors)}"
    )
    summary: dict[str, Any] = {
        "run_id": run_id,
        "source": args.source,
        "source_ref": source_ref,
        "output_dir": str(output_dir),
        "pdf_cache_dir": str(pdf_dir),
        "failed_download_cache_path": str(failure_cache_path),
        "download_only": args.download_only,
        "requested_papers": args.max_results,
        "matched_papers": matched_papers,
        "ready_papers": len(downloads),
        "downloaded_papers": downloaded_papers,
        "network_downloaded_papers": downloaded_papers,
        "cached_papers": cached_papers,
        "download_errors": download_errors,
        "skipped_failed_papers": len(skipped_failures),
        "skipped_failed_downloads": skipped_failures,
        "concurrency": {"client": _arxiv_concurrency_settings(args)},
        "batches": [],
        "state": "downloaded",
    }
    if source_details:
        summary["source_details"] = source_details
    persist_arxiv_summary(summary, output_dir=output_dir, started=started)

    if not args.download_only and downloads:
        settings_json = _json_argument(args.settings_json, "settings")
        tweaks_json = _json_argument(args.tweaks_json, "tweaks")
        items = sort_upload_items(
            [
                BulkUploadItem(
                    path=item.path,
                    content_type="application/pdf",
                )
                for item in downloads
            ],
            args.upload_sort,
        )
        summary["state"] = "uploading"

        def save_bulk(bulk_summary: dict[str, Any]) -> None:
            summary["bulk"] = {
                key: value for key, value in bulk_summary.items() if key != "batches"
            }
            summary["batches"] = bulk_summary.get("batches", [])
            persist_arxiv_summary(summary, output_dir=output_dir, started=started)

        async with OpenRAGApiClient(
            base_url=args.base_url,
            api_key=args.api_key,
            api_prefix=args.api_prefix,
        ) as client:
            bulk_summary = await upload_bulk_items(
                client=client,
                items=items,
                options=BulkUploadOptions(
                    batch_size=args.batch_size,
                    max_inflight=args.max_inflight,
                    max_submit=args.max_submit,
                    request_timeout=args.request_timeout,
                    poll_request_timeout=args.poll_request_timeout,
                    task_timeout=args.task_timeout,
                    poll_interval=args.poll_interval,
                    progress_interval=args.progress_interval,
                    summary_interval=args.summary_interval,
                    input_sort=args.upload_sort,
                    settings_json=settings_json,
                    tweaks_json=tweaks_json,
                    replace_duplicates=args.replace_duplicates,
                ),
                progress=progress,
                summary_callback=save_bulk,
            )
        save_bulk(bulk_summary)

    failed = (
        not downloads
        or bool(download_errors)
        or (not args.download_only and bool(downloads) and bulk_failed(summary))
    )
    summary["state"] = "failed" if failed else "completed"
    result = persist_arxiv_summary(summary, output_dir=output_dir, started=started)
    progress.log(f"complete summary={result['summary_path']}")
    _print_json(result)
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "bulk":
            if args.bulk_action == "list":
                _print_json(
                    list_runs(
                        Path(args.runs_dir).expanduser().resolve(),
                        limit=args.limit,
                    )
                )
                return 0
            if args.bulk_action == "summary":
                _print_json(
                    load_summary_reference(
                        Path(args.runs_dir).expanduser().resolve(),
                        args.run,
                        detail=args.detail,
                    )
                )
                return 0
            return asyncio.run(_upload_main(args))
        if args.command == "bench" and args.benchmark == "arxiv":
            runs_dir = Path(args.runs_dir).expanduser().resolve()
            if args.benchmark_action == "list":
                _print_json(list_runs(runs_dir, limit=args.limit))
                return 0
            if args.benchmark_action == "summary":
                _print_json(
                    load_summary_reference(
                        runs_dir,
                        args.run,
                        detail=args.detail,
                    )
                )
                return 0
            _validate_arxiv_args(parser, args)
            return asyncio.run(_arxiv_main(args))
        parser.error(f"unsupported command: {args.command}")
    except (
        ApiError,
        ArxivBenchmarkError,
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        tarfile.TarError,
    ) as exc:
        print(f"openrag bulk: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("openrag bulk: interrupted", file=sys.stderr)
        return 130


def build_arxiv_query(*, category: str, date_from: str, date_to: str) -> str:
    category = category.strip()
    if not category:
        raise ValueError("--category must not be empty")
    start = arxiv_date_bound(date_from, end=False)
    stop = arxiv_date_bound(date_to, end=True)
    if start > stop:
        raise ValueError("--date-from must be before --date-to")
    return f"cat:{category} AND submittedDate:[{start} TO {stop}]"


def arxiv_date_bound(value: str, *, end: bool) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{12}", value):
        return value
    if re.fullmatch(r"\d{8}", value):
        return value + ("2359" if end else "0000")
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        return "".join(match.groups()) + ("2359" if end else "0000")
    raise ValueError("arXiv dates must use YYYY-MM-DD, YYYYMMDD, or YYYYMMDDHHMM")


def stage_s3_papers(
    *,
    s3_uri: str,
    s3_cache_dir: Path,
    pdf_dir: Path,
    aws_cli: str,
    request_payer: str,
    start: int,
    max_results: int,
    max_pdf_bytes: int,
    skip_existing: bool,
    progress: ProgressReporter,
) -> tuple[list[DownloadedPaper], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    tarball, tarball_downloaded = ensure_s3_tarball(
        s3_uri=s3_uri,
        cache_dir=s3_cache_dir,
        aws_cli=aws_cli,
        request_payer=request_payer,
        skip_existing=skip_existing,
        progress=progress,
    )
    downloads, errors = extract_s3_tarball_papers(
        tarball,
        pdf_dir=pdf_dir,
        start=start,
        max_results=max_results,
        max_pdf_bytes=max_pdf_bytes,
        skip_existing=skip_existing,
        progress=progress,
    )
    details = {
        "s3_uri": s3_uri,
        "tarball_path": str(tarball),
        "tarball_bytes": tarball.stat().st_size,
        "tarball_downloaded": tarball_downloaded,
        "s3_cache_dir": str(s3_cache_dir),
        "selected_pdf_members": len(downloads) + len(errors),
        "ready_pdf_members": len(downloads),
        "failed_pdf_members": len(errors),
    }
    return downloads, errors, [], details


def ensure_s3_tarball(
    *,
    s3_uri: str,
    cache_dir: Path,
    aws_cli: str,
    request_payer: str,
    skip_existing: bool,
    progress: ProgressReporter,
) -> tuple[Path, bool]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / tarball_cache_filename(s3_uri)
    if skip_existing and target.is_file() and target.stat().st_size > 0:
        progress.log(f"S3 tarball cached path={target} bytes={target.stat().st_size}")
        return target, False

    temporary = target.with_name(target.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    parsed = urlparse(s3_uri)
    progress.log(f"S3 tarball downloading source={s3_uri} target={target}")
    if parsed.scheme == "s3":
        command = [aws_cli, "s3", "cp", s3_uri, str(temporary)]
        if request_payer:
            command.extend(["--request-payer", request_payer])
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise ArxivBenchmarkError(
                f"failed to download arXiv S3 tarball {s3_uri}: {detail or command!r}"
            )
    elif parsed.scheme == "file":
        shutil.copyfile(Path(unquote(parsed.path)).expanduser(), temporary)
    elif parsed.scheme:
        raise ArxivBenchmarkError(f"unsupported arXiv S3 URI scheme: {parsed.scheme}")
    else:
        shutil.copyfile(Path(s3_uri).expanduser(), temporary)
    temporary.replace(target)
    progress.log(f"S3 tarball downloaded path={target} bytes={target.stat().st_size}")
    return target, True


def extract_s3_tarball_papers(
    tarball: Path,
    *,
    pdf_dir: Path,
    start: int,
    max_results: int,
    max_pdf_bytes: int,
    skip_existing: bool,
    progress: ProgressReporter,
) -> tuple[list[DownloadedPaper], list[dict[str, Any]]]:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    downloads: list[DownloadedPaper] = []
    errors: list[dict[str, Any]] = []
    used_filenames: set[str] = set()
    seen_pdf_members = 0
    selected_members = 0
    with tarfile.open(tarball, mode="r:*") as archive:
        for member in archive:
            if not member.isfile() or not member.name.lower().endswith(".pdf"):
                continue
            seen_pdf_members += 1
            if seen_pdf_members <= start:
                continue
            if selected_members >= max_results:
                break
            selected_members += 1
            paper = s3_member_paper(member.name)
            filename = unique_filename(
                pdf_dir,
                pdf_filename(paper),
                used_filenames,
                allow_existing=skip_existing,
            )
            path = pdf_dir / filename
            cached = skip_existing and path.is_file()
            try:
                if not cached:
                    if member.size > max_pdf_bytes:
                        raise ValueError(f"PDF is larger than limit: {member.size} bytes")
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("tar member has no file content")
                    with source, path.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    if path.stat().st_size > max_pdf_bytes:
                        raise ValueError(f"PDF exceeded limit: {max_pdf_bytes} bytes")
                    progress.log(
                        f"S3 PDF {selected_members}/{max_results}: extracted "
                        f"arxiv_id={paper.arxiv_id} bytes={path.stat().st_size}"
                    )
                else:
                    progress.log(
                        f"S3 PDF {selected_members}/{max_results}: cached "
                        f"arxiv_id={paper.arxiv_id} path={path}"
                    )
                downloads.append(
                    DownloadedPaper(
                        paper=paper,
                        path=path,
                        size=path.stat().st_size,
                        sha256=sha256_file(path),
                        cached=cached,
                    )
                )
            except Exception as exc:
                if not cached and path.exists():
                    path.unlink()
                progress.log(
                    f"S3 PDF {selected_members}/{max_results}: failed member={member.name} "
                    f"error={_error_text(exc)}"
                )
                errors.append(
                    {
                        "arxiv_id": paper.arxiv_id,
                        "pdf_url": paper.pdf_url,
                        "error": _error_text(exc),
                        "tar_member": member.name,
                    }
                )
    progress.log(
        f"S3 tarball scan complete pdf_members_seen={seen_pdf_members} "
        f"selected={selected_members} ready={len(downloads)} errors={len(errors)}"
    )
    return downloads, errors


def s3_member_paper(member_name: str) -> ArxivPaper:
    arxiv_id = arxiv_id_from_pdf_member(member_name)
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=arxiv_id,
        summary="",
        authors=(),
        published=None,
        updated=None,
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


def arxiv_id_from_pdf_member(member_name: str) -> str:
    filename = Path(member_name).name
    stem = filename[:-4] if filename.lower().endswith(".pdf") else Path(filename).stem
    stem = stem.strip()
    return stem or hashlib.sha256(member_name.encode()).hexdigest()[:16]


def tarball_cache_filename(uri: str) -> str:
    parsed = urlparse(uri)
    name = Path(unquote(parsed.path)).name if parsed.path else Path(uri).name
    name = safe_slug(name, 160)
    digest = hashlib.sha256(uri.encode()).hexdigest()[:12]
    suffix = "".join(Path(name).suffixes)
    stem = name[: -len(suffix)] if suffix else name
    return f"{stem}-{digest}{suffix or '.tar'}"


def fetch_arxiv_papers(
    *,
    query: str,
    start: int,
    max_results: int,
    sort_by: str,
    sort_order: str,
    rate: RateLimiter,
    user_agent: str,
    timeout: float,
) -> list[ArxivPaper]:
    url = f"{ARXIV_API_URL}?" + urlencode(
        {
            "search_query": query,
            "start": str(start),
            "max_results": str(max_results),
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
    )
    rate.wait()
    try:
        payload = read_url(
            url,
            user_agent=user_agent,
            timeout=timeout,
            accept="application/atom+xml",
        )
    except HTTPError as exc:
        if exc.code == 429:
            raise ArxivBenchmarkError(
                "arXiv returned HTTP 429 for metadata; wait before retrying, or ingest "
                "already-cached PDFs with "
                "`openrag_bulk.py bulk upload <pdf-cache> --include '*.pdf'`"
            ) from exc
        raise
    return parse_arxiv_feed(payload)


def parse_arxiv_feed(payload: bytes) -> list[ArxivPaper]:
    root = ET.fromstring(payload)
    papers: list[ArxivPaper] = []
    for entry in root.findall(f"{ATOM}entry"):
        abs_url = _atom_text(entry, "id")
        title = collapse_ws(_atom_text(entry, "title"))
        summary = collapse_ws(_atom_text(entry, "summary"))
        authors = tuple(
            collapse_ws(_atom_text(author, "name"))
            for author in entry.findall(f"{ATOM}author")
            if collapse_ws(_atom_text(author, "name"))
        )
        pdf_url = ""
        for link in entry.findall(f"{ATOM}link"):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href", "")
                break
        if not abs_url or not pdf_url:
            continue
        papers.append(
            ArxivPaper(
                arxiv_id=arxiv_id_from_abs_url(abs_url),
                title=title,
                summary=summary,
                authors=authors,
                published=_atom_text(entry, "published") or None,
                updated=_atom_text(entry, "updated") or None,
                abs_url=https_url(abs_url),
                pdf_url=https_url(pdf_url),
            )
        )
    return papers


def download_papers(
    papers: list[ArxivPaper],
    *,
    pdf_dir: Path,
    rate: RateLimiter,
    user_agent: str,
    timeout: float,
    max_pdf_bytes: int,
    skip_existing: bool,
    failure_cache: dict[str, dict[str, Any]] | None = None,
    failure_cache_path: Path | None = None,
    retry_failed: bool = False,
    progress: ProgressReporter,
) -> tuple[list[DownloadedPaper], list[dict[str, Any]], list[dict[str, Any]]]:
    downloads: list[DownloadedPaper] = []
    errors: list[dict[str, Any]] = []
    skipped_failures: list[dict[str, Any]] = []
    failure_cache = failure_cache if failure_cache is not None else {}
    used_filenames: set[str] = set()
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for index, paper in enumerate(papers, start=1):
        failure_key = failed_download_cache_key(paper)
        filename = unique_filename(
            pdf_dir,
            pdf_filename(paper),
            used_filenames,
            allow_existing=skip_existing,
        )
        path = pdf_dir / filename
        cached = skip_existing and path.is_file()
        cached_failure = failure_cache.get(failure_key)
        if cached_failure and not retry_failed and not cached:
            skipped = public_failed_download_record(cached_failure)
            progress.log(
                f"PDF {index}/{len(papers)}: skipped known failed "
                f"arxiv_id={paper.arxiv_id} error={skipped['error']}"
            )
            skipped_failures.append(skipped)
            continue
        try:
            if not cached:
                progress.log(
                    f"PDF {index}/{len(papers)}: downloading "
                    f"arxiv_id={paper.arxiv_id} url={paper.pdf_url}"
                )
                rate.wait()
                download_pdf(
                    paper.pdf_url,
                    path=path,
                    user_agent=user_agent,
                    timeout=timeout,
                    max_pdf_bytes=max_pdf_bytes,
                )
            else:
                progress.log(
                    f"PDF {index}/{len(papers)}: cached arxiv_id={paper.arxiv_id} path={path}"
                )
            downloads.append(
                DownloadedPaper(
                    paper=paper,
                    path=path,
                    size=path.stat().st_size,
                    sha256=sha256_file(path),
                    cached=cached,
                )
            )
            if failure_key in failure_cache:
                failure_cache.pop(failure_key, None)
                save_failed_download_cache(failure_cache_path, failure_cache)
        except Exception as exc:
            progress.log(
                f"PDF {index}/{len(papers)}: failed arxiv_id={paper.arxiv_id} "
                f"error={_error_text(exc)}"
            )
            record = failed_download_record(paper, exc, previous=failure_cache.get(failure_key))
            failure_cache[failure_key] = record
            save_failed_download_cache(failure_cache_path, failure_cache)
            errors.append(public_failed_download_record(record))
    return downloads, errors, skipped_failures


def download_pdf(
    url: str,
    *,
    path: Path,
    user_agent: str,
    timeout: float,
    max_pdf_bytes: int,
) -> None:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/pdf"})
    total = 0
    try:
        with urlopen(request, timeout=timeout) as response, path.open("wb") as output:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_pdf_bytes:
                raise ValueError(f"PDF is larger than limit: {int(length)} bytes")
            while chunk := response.read(128 * 1024):
                total += len(chunk)
                if total > max_pdf_bytes:
                    raise ValueError(f"PDF exceeded limit: {max_pdf_bytes} bytes")
                output.write(chunk)
    except Exception:
        if path.exists():
            path.unlink()
        raise


def read_url(url: str, *, user_agent: str, timeout: float, accept: str) -> bytes:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": accept})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def load_failed_download_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    failures = parsed.get("failures") if isinstance(parsed, dict) else None
    if not isinstance(failures, dict):
        return {}
    return {str(key): value for key, value in failures.items() if isinstance(value, dict)}


def seed_failed_download_cache_from_summaries(
    runs_dir: Path,
    *,
    source_ref: str,
) -> dict[str, dict[str, Any]]:
    if not runs_dir.is_dir():
        return {}
    seeded: dict[str, dict[str, Any]] = {}
    for summary_path in sorted(runs_dir.glob("*/summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(summary, dict) or summary.get("source_ref") != source_ref:
            continue
        for record in summary_download_failure_records(summary):
            arxiv_id = str(record.get("arxiv_id") or "")
            if arxiv_id:
                seeded[arxiv_id] = {
                    "arxiv_id": arxiv_id,
                    "pdf_url": str(record.get("pdf_url") or ""),
                    "error": str(record.get("error") or "previous benchmark download failure"),
                    "first_failed_at": str(record.get("first_failed_at") or ""),
                    "last_failed_at": str(record.get("last_failed_at") or ""),
                    "attempts": record.get("attempts") or 1,
                    "seeded_from_summary": str(summary_path),
                }
    return seeded


def summary_download_failure_records(summary: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in ("download_errors", "skipped_failed_downloads"):
        value = summary.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    return records


def save_failed_download_cache(
    path: Path | None,
    failures: dict[str, dict[str, Any]],
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "failures": failures}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def failed_download_cache_key(paper: ArxivPaper) -> str:
    return paper.arxiv_id or hashlib.sha256(paper.pdf_url.encode()).hexdigest()


def failed_download_record(
    paper: ArxivPaper,
    exc: Exception,
    *,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    first_failed_at = str((previous or {}).get("first_failed_at") or now)
    try:
        attempts = int((previous or {}).get("attempts") or 0) + 1
    except (TypeError, ValueError):
        attempts = 1
    return {
        "arxiv_id": paper.arxiv_id,
        "abs_url": paper.abs_url,
        "pdf_url": paper.pdf_url,
        "title": paper.title,
        "error_type": type(exc).__name__,
        "error": _error_text(exc),
        "first_failed_at": first_failed_at,
        "last_failed_at": now,
        "attempts": attempts,
    }


def public_failed_download_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "arxiv_id": str(record.get("arxiv_id") or ""),
        "pdf_url": str(record.get("pdf_url") or ""),
        "error": str(record.get("error") or "unknown download error"),
        "first_failed_at": str(record.get("first_failed_at") or ""),
        "last_failed_at": str(record.get("last_failed_at") or ""),
        "attempts": record.get("attempts") or None,
    }


def persist_arxiv_summary(
    summary: dict[str, Any],
    *,
    output_dir: Path,
    started: float,
) -> dict[str, Any]:
    summary_path = output_dir / "summary.json"
    summary["summary_path"] = str(summary_path)
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    ordered = _ordered_arxiv_summary(summary)
    temporary = output_dir / ".summary.json.tmp"
    temporary.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
    temporary.replace(summary_path)
    return ordered


def _ordered_arxiv_summary(summary: dict[str, Any]) -> dict[str, Any]:
    preferred = (
        "run_id",
        "summary_path",
        "output_dir",
        "pdf_cache_dir",
        "failed_download_cache_path",
        "source",
        "source_ref",
        "download_only",
        "requested_papers",
        "matched_papers",
        "ready_papers",
        "downloaded_papers",
        "network_downloaded_papers",
        "cached_papers",
        "download_errors",
        "skipped_failed_papers",
        "skipped_failed_downloads",
        "elapsed_seconds",
        "state",
        "concurrency",
        "bulk",
    )
    ordered = {key: summary[key] for key in preferred if key in summary}
    ordered.update(
        {key: value for key, value in summary.items() if key not in ordered and key != "batches"}
    )
    if "batches" in summary:
        ordered["batches"] = summary["batches"]
    return ordered


def _arxiv_concurrency_settings(args: argparse.Namespace) -> dict[str, Any]:
    source: dict[str, Any] = {
        "source": args.source,
        "max_inflight_requests": 1,
        "request_timeout_seconds": args.request_timeout,
        "skip_existing": args.skip_existing,
    }
    if args.source == "s3":
        source.update(s3_uri=args.s3_uri, s3_request_payer=args.s3_request_payer or None)
    else:
        source.update(
            delay_seconds=args.delay_seconds,
            retry_failed_downloads=args.retry_failed_downloads,
        )
    return {
        "pdf_source": source,
        "upload": {
            "batch_size": args.batch_size,
            "max_inflight_upload_tasks": args.max_inflight,
            "max_inflight_submit_requests": args.max_submit or args.max_inflight,
            "input_sort": args.upload_sort,
            "request_timeout_seconds": args.request_timeout,
            "poll_request_timeout_seconds": args.poll_request_timeout,
            "task_timeout_seconds": args.task_timeout,
            "poll_interval_seconds": args.poll_interval,
        },
    }


def _atom_text(entry: ET.Element, name: str) -> str:
    child = entry.find(f"{ATOM}{name}")
    return child.text.strip() if child is not None and child.text else ""


def collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def arxiv_id_from_abs_url(abs_url: str) -> str:
    return urlparse(abs_url).path.rstrip("/").rsplit("/", 1)[-1]


def https_url(value: str) -> str:
    parsed = urlparse(value)
    return urlunparse(parsed._replace(scheme="https")) if parsed.scheme == "http" else value


def pdf_filename(paper: ArxivPaper) -> str:
    return f"{safe_slug(paper.arxiv_id, 120)}.pdf"


def safe_slug(value: str, max_length: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_length].strip(".-_") or "paper"


def unique_filename(
    directory: Path,
    filename: str,
    used: set[str],
    *,
    allow_existing: bool = False,
) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = filename
    index = 2
    while candidate in used or ((directory / candidate).exists() and not allow_existing):
        candidate = f"{stem}-{index}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _response_json(response: httpx.Response) -> dict[str, Any]:
    if response.is_error:
        try:
            payload = response.json()
            message = payload.get("error") or payload.get("detail") or response.text
        except (ValueError, TypeError):
            message = response.text
        raise ApiError(str(message or f"HTTP {response.status_code}"), response.status_code)
    try:
        payload = response.json()
    except ValueError as exc:
        raise ApiError("OpenRAG returned a non-JSON response", response.status_code) from exc
    if not isinstance(payload, dict):
        raise ApiError("OpenRAG returned a non-object JSON response", response.status_code)
    return payload


def _new_batch_result(batch: Sequence[BulkUploadItem], *, batch_index: int) -> dict[str, Any]:
    byte_count = sum(item.path.stat().st_size for item in batch)
    return {
        "batch_index": batch_index,
        "file_count": len(batch),
        "files": [str(item.path) for item in batch],
        "input_bytes": byte_count,
        "input_mb": round(_mb(byte_count), 3),
        "status": "queued",
        "phase": "queued",
    }


def _update_batch_from_status(result: dict[str, Any], status: dict[str, Any]) -> None:
    result.update(
        status=str(status.get("status") or "unknown"),
        phase=_task_phase(status),
        duration_seconds=status.get("duration_seconds"),
        processed_files=status.get("processed_files"),
        successful_files=status.get("successful_files"),
        failed_files=status.get("failed_files"),
        running_files=status.get("running_files"),
        pending_files=status.get("pending_files"),
        error=_task_error(status) or None,
    )


def _task_phase(status: dict[str, Any]) -> str:
    if status.get("phase"):
        return str(status["phase"])
    phases = {
        str(file_status.get("phase"))
        for file_status in (status.get("files") or {}).values()
        if isinstance(file_status, dict) and file_status.get("phase")
    }
    if len(phases) == 1:
        return phases.pop()
    if phases:
        return "mixed"
    return "complete" if status.get("status") in TERMINAL_TASK_STATUSES else "task_poll"


def _task_error(status: dict[str, Any]) -> str:
    if status.get("error"):
        return _summarize_error(status["error"])
    errors = [
        file_status.get("error")
        for file_status in (status.get("files") or {}).values()
        if isinstance(file_status, dict) and file_status.get("error")
    ]
    if not errors:
        return ""
    first = _summarize_error(errors[0])
    return first if len(errors) == 1 else f"{first} (+{len(errors) - 1} more)"


def _status_snapshot(status: dict[str, Any]) -> tuple[Any, ...]:
    return (
        status.get("status"),
        _task_phase(status),
        status.get("processed_files"),
        status.get("successful_files"),
        status.get("failed_files"),
        status.get("running_files"),
        status.get("pending_files"),
        _task_error(status),
    )


def _update_summary_totals(summary: dict[str, Any]) -> None:
    batches = summary.get("batches") or []
    summary["successful_files"] = sum(_int_value(item.get("successful_files")) for item in batches)
    summary["failed_files"] = sum(_int_value(item.get("failed_files")) for item in batches)
    summary["completed_batches"] = sum(item.get("status") == "completed" for item in batches)
    summary["failed_batches"] = sum(item.get("status") != "completed" for item in batches)


def _run_overview(summary: dict[str, Any], path: Path) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    for batch in summary.get("batches") or []:
        status = str(batch.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    if summary.get("state"):
        state = str(summary["state"])
    elif not statuses:
        state = "unknown"
    elif any(status not in TERMINAL_TASK_STATUSES for status in statuses):
        state = "running"
    elif any(status != "completed" for status in statuses):
        state = "failed"
    else:
        state = "completed"
    return {
        "run_id": str(summary.get("run_id") or path.parent.name),
        "state": state,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
        "summary_path": str(path),
        "elapsed_seconds": summary.get("elapsed_seconds"),
        "total_files": summary.get("total_files", summary.get("ready_papers")),
        "batch_count": len(summary.get("batches") or []),
        "batch_status_counts": statuses,
    }


def _load_summary(path: Path) -> dict[str, Any]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError(f"summary is not a JSON object: {path}")
    return summary


def _json_argument(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    raw = (
        Path(value[1:]).expanduser().read_text(encoding="utf-8") if value.startswith("@") else value
    )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} JSON must be an object")
    return json.dumps(parsed, separators=(",", ":"))


def _ordered_summary(summary: dict[str, Any]) -> dict[str, Any]:
    preferred = (
        "run_id",
        "summary_path",
        "output_dir",
        "elapsed_seconds",
        "total_files",
        "successful_files",
        "failed_files",
        "completed_batches",
        "failed_batches",
        "batch_size",
        "max_inflight",
        "max_submit",
        "client_concurrency",
    )
    ordered = {key: summary[key] for key in preferred if key in summary}
    ordered.update(
        {key: value for key, value in summary.items() if key not in ordered and key != "batches"}
    )
    if "batches" in summary:
        ordered["batches"] = summary["batches"]
    return ordered


def _notify(callback: SummaryCallback | None, summary: dict[str, Any]) -> None:
    if callback:
        callback(summary)


def _matches(relative: str, name: str, patterns: Sequence[str]) -> bool:
    return any(
        fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(name, pattern) for pattern in patterns
    )


def _chunks(items: list[BulkUploadItem], size: int) -> list[list[BulkUploadItem]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _should_log(now: float, last_log: float, interval: float) -> bool:
    return interval == 0 or now - last_log >= interval


def _is_transient_error(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.TransportError, TimeoutError)) or (
        isinstance(exc, ApiError) and exc.status_code in TRANSIENT_HTTP_STATUSES
    )


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {_summarize_error(exc)}"


def _summarize_error(value: Any) -> str:
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    text = lines[-1] if lines else str(value).strip()
    return text if len(text) <= 320 else text[:317] + "..."


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _mb(value: int | float) -> float:
    return float(value) / 1_000_000


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
