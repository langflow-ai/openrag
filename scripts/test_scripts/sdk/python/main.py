"""OpenRAG Python SDK smoke tests against a remote (IBM SaaS) deployment.

Exercises every SDK functionality (settings, models, documents, search, chat,
knowledge filters, error handling) and writes a pass/fail report to reports/.

Configuration (CLI flags override environment, which overrides .env):
    OPENRAG_URL       base URL of the deployment
    OPENRAG_USERNAME  sent as the X-Username header (IBM SaaS auth)
    OPENRAG_API_KEY   sent as the X-Api-Key header (IBM SaaS auth)

Usage:
    uv run python main.py
    uv run python main.py --url https://... --username u --api-key k
    uv run python main.py --only search,chat
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from openrag_sdk import OpenRAGClient

from checks import ALL_SUITES, SUITE_NAMES
from harness import (
    Config,
    Context,
    mask_api_key,
    mask_username,
    run_suites,
    summarize,
    write_reports,
)

HERE = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, never overrides real env vars."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def parse_config(argv: list[str]) -> Config:
    parser = argparse.ArgumentParser(
        description="Smoke-test the OpenRAG Python SDK against a remote deployment."
    )
    parser.add_argument("--url", help="Base URL (env: OPENRAG_URL)")
    parser.add_argument("--username", help="SaaS username (env: OPENRAG_USERNAME)")
    parser.add_argument("--api-key", help="SaaS API key (env: OPENRAG_API_KEY)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-request timeout in seconds (default: 120; streaming chat "
        "routinely exceeds the SDK's 30s default)",
    )
    parser.add_argument(
        "--only",
        help=f"Comma-separated suites to run (choices: {','.join(SUITE_NAMES)})",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=HERE / "reports",
        help="Directory for report.md / report.json (default: ./reports)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=HERE / ".env",
        help="Path to a .env file (default: ./.env)",
    )
    args = parser.parse_args(argv)

    load_dotenv(args.env_file)

    url = args.url or os.environ.get("OPENRAG_URL", "")
    username = args.username or os.environ.get("OPENRAG_USERNAME", "")
    api_key = args.api_key or os.environ.get("OPENRAG_API_KEY", "")

    missing = [
        name
        for name, value in [
            ("--url / OPENRAG_URL", url),
            ("--username / OPENRAG_USERNAME", username),
            ("--api-key / OPENRAG_API_KEY", api_key),
        ]
        if not value
    ]
    if missing:
        parser.error(f"missing required configuration: {', '.join(missing)}")

    only = None
    if args.only:
        only = [s.strip() for s in args.only.split(",") if s.strip()]
        unknown = [s for s in only if s not in SUITE_NAMES]
        if unknown:
            parser.error(
                f"unknown suite(s): {', '.join(unknown)} "
                f"(choices: {', '.join(SUITE_NAMES)})"
            )

    return Config(
        url=url.rstrip("/"),
        username=username,
        api_key=api_key,
        timeout=args.timeout,
        only=only,
        report_dir=args.report_dir,
    )


async def amain(cfg: Config) -> int:
    client = OpenRAGClient(
        base_url=cfg.url,
        extra_headers={"X-Username": cfg.username, "X-Api-Key": cfg.api_key},
        timeout=cfg.timeout,
    )
    try:
        print(
            f"Target: {cfg.url}  "
            f"(user: {mask_username(cfg.username)}, key: {mask_api_key(cfg.api_key)})"
        )

        try:
            await client.settings.get()
        except Exception as e:
            print(f"\nPreflight failed — cannot reach {cfg.url}: {e}", file=sys.stderr)
            print("Check the URL, username, and API key.", file=sys.stderr)
            return 2
        print("Preflight OK — instance reachable and credentials accepted.")

        suites = [
            (name, checks)
            for name, checks in ALL_SUITES
            if cfg.only is None or name in cfg.only
        ]

        started_at = datetime.now(timezone.utc)
        start = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="openrag-sdk-smoke-") as tmpdir:
            ctx = Context(client=client, cfg=cfg, shared={"tmpdir": tmpdir})
            results = await run_suites(suites, ctx)
        total_duration = time.perf_counter() - start

        written = write_reports(results, cfg, started_at, total_duration)
        totals = summarize(results)
        print(
            f"\n{totals['passed']} passed, {totals['failed']} failed, "
            f"{totals['skipped']} skipped in {total_duration:.1f}s"
        )
        print("Reports written:")
        for path in written:
            print(f"  {path}")
        return 0 if totals["failed"] == 0 else 1
    finally:
        await client.close()


def main() -> None:
    cfg = parse_config(sys.argv[1:])
    try:
        sys.exit(asyncio.run(amain(cfg)))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
