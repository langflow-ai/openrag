"""Check harness: dataclasses, sequential runner, and report writers.

Checks are plain async functions taking a Context. A check passes when it
returns, fails when it raises, and is skipped when it raises Skip. Checks can
declare `requires` (names of checks that must have passed first) — unmet
requirements auto-skip instead of producing misleading failures.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

PASS = "pass"
FAIL = "fail"
SKIP = "skip"


class Skip(Exception):
    """Raise inside a check to mark it skipped (with a reason)."""


@dataclass
class Config:
    url: str
    username: str
    api_key: str
    timeout: float
    only: list[str] | None
    report_dir: Path


@dataclass
class Check:
    name: str  # e.g. "documents.ingest_wait"
    fn: Callable[[Context], Awaitable[None]]
    requires: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    name: str
    status: str  # pass | fail | skip
    duration_s: float
    error: str | None = None


@dataclass
class Context:
    client: Any  # OpenRAGClient
    cfg: Config
    shared: dict[str, Any] = field(default_factory=dict)
    # (label, async callable) pairs, run LIFO after all suites
    cleanup: list[tuple[str, Callable[[], Awaitable[Any]]]] = field(default_factory=list)

    def add_cleanup(self, label: str, fn: Callable[[], Awaitable[Any]]) -> None:
        self.cleanup.append((label, fn))


# --- console helpers ---------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()


def _color(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def _status_label(status: str) -> str:
    return {
        PASS: _color("32", "PASS"),
        FAIL: _color("31", "FAIL"),
        SKIP: _color("33", "SKIP"),
    }[status]


# --- runner ------------------------------------------------------------------


async def run_suites(suites: list[tuple[str, list[Check]]], ctx: Context) -> list[CheckResult]:
    """Run all checks sequentially; always run registered cleanups at the end."""
    results: list[CheckResult] = []
    passed: set[str] = set()

    try:
        for suite_name, checks in suites:
            print(f"\n{_color('1', suite_name)}")
            for check in checks:
                missing = [r for r in check.requires if r not in passed]
                if missing:
                    result = CheckResult(check.name, SKIP, 0.0, f"requires {', '.join(missing)}")
                    results.append(result)
                    _print_result(result)
                    continue

                start = time.perf_counter()
                try:
                    await check.fn(ctx)
                    result = CheckResult(check.name, PASS, time.perf_counter() - start)
                    passed.add(check.name)
                except Skip as e:
                    result = CheckResult(check.name, SKIP, time.perf_counter() - start, str(e))
                except Exception:
                    result = CheckResult(
                        check.name,
                        FAIL,
                        time.perf_counter() - start,
                        traceback.format_exc(limit=5),
                    )
                results.append(result)
                _print_result(result)
    finally:
        await _run_cleanup(ctx)

    return results


def _print_result(result: CheckResult) -> None:
    line = f"  {_status_label(result.status)}  {result.name}  ({result.duration_s:.1f}s)"
    if result.status != PASS and result.error:
        first_line = result.error.strip().splitlines()[-1][:120]
        line += f"  — {first_line}"
    print(line, flush=True)


async def _run_cleanup(ctx: Context) -> None:
    if not ctx.cleanup:
        return
    print(f"\n{_color('1', 'cleanup')}")
    for label, fn in reversed(ctx.cleanup):
        try:
            await fn()
            print(f"  {_color('32', 'ok')}    {label}")
        except Exception as e:
            print(f"  {_color('33', 'warn')}  {label} — {e}")


# --- reporting ---------------------------------------------------------------


def mask_api_key(key: str) -> str:
    return "****" + key[-4:] if len(key) >= 8 else "****"


def mask_username(username: str) -> str:
    if "@" in username:
        local, _, domain = username.partition("@")
        return f"{local[:2]}***@{domain}"
    return username[:2] + "***"


def _sdk_version() -> str:
    try:
        from importlib.metadata import version

        return version("openrag-sdk")
    except Exception:
        return "unknown"


def summarize(results: list[CheckResult]) -> dict[str, int]:
    return {
        "passed": sum(1 for r in results if r.status == PASS),
        "failed": sum(1 for r in results if r.status == FAIL),
        "skipped": sum(1 for r in results if r.status == SKIP),
        "total": len(results),
    }


def write_reports(
    results: list[CheckResult],
    cfg: Config,
    started_at: datetime,
    total_duration_s: float,
) -> list[Path]:
    totals = summarize(results)
    timestamp = started_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = started_at.astimezone(UTC).strftime("%Y%m%d_%H%M%S")

    payload = {
        "timestamp": timestamp,
        "target_url": cfg.url,
        "username": mask_username(cfg.username),
        "api_key": mask_api_key(cfg.api_key),
        "sdk_version": _sdk_version(),
        "duration_s": round(total_duration_s, 1),
        "totals": totals,
        "checks": [
            {
                "name": r.name,
                "status": r.status,
                "duration_s": round(r.duration_s, 2),
                "error": r.error,
            }
            for r in results
        ],
    }

    md_lines = [
        "# OpenRAG SDK Smoke-Test Report",
        "",
        f"- **Timestamp:** {timestamp}",
        f"- **Target:** {cfg.url}",
        f"- **Username:** {mask_username(cfg.username)}",
        f"- **API key:** {mask_api_key(cfg.api_key)}",
        f"- **SDK version:** {_sdk_version()}",
        f"- **Result:** {totals['passed']} passed, {totals['failed']} failed, "
        f"{totals['skipped']} skipped ({total_duration_s:.1f}s)",
        "",
        "| Check | Status | Duration | Detail |",
        "|---|---|---|---|",
    ]
    for r in results:
        detail = ""
        if r.status != PASS and r.error:
            detail = r.error.strip().splitlines()[-1][:100].replace("|", "\\|")
        md_lines.append(f"| {r.name} | {r.status.upper()} | {r.duration_s:.1f}s | {detail} |")

    failures = [r for r in results if r.status == FAIL]
    if failures:
        md_lines += ["", "<details>", "<summary>Failure details</summary>", ""]
        for r in failures:
            md_lines += [f"### {r.name}", "", "```", (r.error or "").strip(), "```", ""]
        md_lines += ["</details>", ""]

    cfg.report_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in [
        ("report.json", json.dumps(payload, indent=2) + "\n"),
        ("report.md", "\n".join(md_lines) + "\n"),
    ]:
        latest = cfg.report_dir / name
        stamped = cfg.report_dir / name.replace("report", f"report_{stamp}")
        latest.write_text(content)
        stamped.write_text(content)
        written += [latest, stamped]
    return written
