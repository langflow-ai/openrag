#!/usr/bin/env python3
"""Measure OpenRAG retrieval quality against a fixed corpus and labeled questions.

    uv run run_eval.py run [--baseline results/baseline.json]
    uv run run_eval.py check
    uv run run_eval.py cleanup [--yes]
    uv run run_eval.py compare <baseline.json> <current.json>

``run`` ingests the checked-in corpus under run-unique filenames, sends every
question through ``/v1/search``, scores the ranking by file, writes results and
a summary, and deletes the documents it uploaded. ``check`` confirms a stack is
ready for a run without uploading anything, and ``cleanup`` removes documents
that interrupted runs left behind. ``compare`` diffs two results files offline.
See README.md.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import dataset
import metrics
import report

HERE = Path(__file__).resolve().parent
DEFAULT_URL = "http://localhost:3000"


class EvalError(RuntimeError):
    """The run cannot produce trustworthy scores."""


def _parse_k_values(value: str) -> list[int]:
    try:
        k_values = sorted({int(part) for part in value.split(",") if part.strip()})
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"not a comma-separated list of integers: {value}"
        ) from exc
    if not k_values or k_values[0] < 1:
        raise argparse.ArgumentTypeError("k values must be positive integers")
    return k_values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retrieval-quality evaluation harness for OpenRAG search.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    # Options shared by every command that talks to a stack.
    stack = argparse.ArgumentParser(add_help=False)
    stack.add_argument(
        "--url",
        default=os.environ.get("OPENRAG_URL", DEFAULT_URL),
        help=f"defaults to the OPENRAG_URL environment variable, then {DEFAULT_URL}",
    )
    stack.add_argument(
        "--api-key",
        default=os.environ.get("OPENRAG_API_KEY"),
        help="defaults to the OPENRAG_API_KEY environment variable",
    )
    stack.add_argument(
        "--request-timeout", type=float, default=60.0, help="seconds per HTTP request"
    )
    stack.add_argument("--corpus", type=Path, default=HERE / "corpus")

    run = commands.add_parser(
        "run", parents=[stack], help="ingest the corpus, run every question and score it"
    )
    run.add_argument("--queries", type=Path, default=HERE / "queries.jsonl")
    run.add_argument("--output-dir", type=Path, default=HERE / "results")
    run.add_argument("--baseline", type=Path, help="results file to compare this run against")
    run.add_argument(
        "--max-recall-drop",
        type=float,
        help=(
            "with --baseline, exit with status 1 when the average recall at the compared "
            "cutoff falls by more than this (0.02 = two points). Off by default."
        ),
    )
    run.add_argument(
        "--k",
        dest="k_values",
        type=_parse_k_values,
        default=list(metrics.DEFAULT_K_VALUES),
        help="comma-separated cutoffs (default: 1,3,5,10)",
    )
    run.add_argument(
        "--fetch-limit",
        type=int,
        default=50,
        help="chunks requested per question before deduplicating to files (default: 50)",
    )
    run.add_argument("--score-threshold", type=float, default=0.0)
    run.add_argument("--concurrency", type=int, default=4, help="parallel uploads (default: 4)")
    run.add_argument(
        "--ingest-timeout", type=float, default=300.0, help="seconds per ingestion task"
    )
    run.add_argument(
        "--visibility-timeout",
        type=float,
        default=120.0,
        help="seconds to wait for an ingested file to become searchable",
    )
    run.add_argument(
        "--keep-documents",
        action="store_true",
        help="leave the uploaded documents in the stack for debugging",
    )
    run.add_argument(
        "--validate-only",
        action="store_true",
        help="check the corpus and question file, then exit without contacting a stack",
    )

    check = commands.add_parser(
        "check",
        parents=[stack],
        help="check that a stack is ready for a run, without uploading anything",
    )
    check.add_argument("--queries", type=Path, default=HERE / "queries.jsonl")

    cleanup = commands.add_parser(
        "cleanup",
        parents=[stack],
        help="list, and with --yes delete, documents that interrupted runs left behind",
    )
    cleanup.add_argument(
        "--yes", action="store_true", help="delete the listed documents (default: list only)"
    )
    cleanup.add_argument(
        "--min-age",
        type=float,
        default=60.0,
        help=(
            "only delete documents indexed at least this many minutes ago, so a run "
            "still in progress is left alone (default: 60)"
        ),
    )

    compare = commands.add_parser("compare", help="diff two results files offline")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("current", type=Path)

    promote = commands.add_parser(
        "promote", help="replace the baseline with a results file, only if it improves on it"
    )
    promote.add_argument("current", type=Path, help="results file of the new run")
    promote.add_argument("baseline", type=Path, help="baseline file to update (may not exist yet)")
    promote.add_argument(
        "--min-gain",
        type=float,
        default=0.0,
        help="average recall must rise by more than this (default: 0, any rise)",
    )
    return parser


def _sdk_version() -> str:
    try:
        from importlib.metadata import version

        return version("openrag-sdk")
    except Exception:
        return "unknown"


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=HERE,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _file_failures(status: Any) -> list[str]:
    """Reasons an ingestion task did not index its file, empty when it did.

    The task counters are not enough: a file skipped as a duplicate of content
    already in the stack is counted in ``successful_files`` but is not indexed
    under the name this run uploaded.
    """
    problems: list[str] = []
    if status.status != "completed":
        problems.append(f"task status is {status.status!r}")
    if status.failed_files > 0:
        problems.append(f"{status.failed_files} file(s) failed")
    if status.successful_files < 1:
        problems.append("no file was ingested")
    for name, entry in (status.files or {}).items():
        if not isinstance(entry, dict):
            continue
        file_status = str(entry.get("status", "")).lower()
        if file_status and file_status != "completed":
            detail = entry.get("error") or (entry.get("result") or {}).get("reason") or ""
            problems.append(f"{name}: {file_status} {detail}".strip())
    return problems


async def _ingest_corpus(
    client: Any,
    corpus_dir: Path,
    manifest: dict[str, str],
    run_id: str,
    concurrency: int,
    timeout: float,
) -> None:
    """Upload every corpus file under its run-unique name and require each to succeed."""
    limit = asyncio.Semaphore(max(1, concurrency))
    # Appended to each upload so its content hash is unique to this run. The
    # stack skips content it already holds under another filename, which would
    # otherwise happen whenever an earlier run's cleanup did not finish.
    marker = f"\n\n<!-- openrag retrieval eval run {run_id} -->\n".encode()

    async def upload(uploaded_name: str, canonical: str) -> str | None:
        payload = (corpus_dir / canonical).read_bytes() + marker
        async with limit:
            try:
                status = await client.documents.ingest(
                    file=io.BytesIO(payload),
                    filename=uploaded_name,
                    timeout=timeout,
                )
            except Exception as exc:
                return f"{canonical}: {type(exc).__name__}: {exc}"
        problems = _file_failures(status)
        return f"{canonical}: {'; '.join(problems)}" if problems else None

    outcomes = await asyncio.gather(
        *(upload(uploaded, canonical) for uploaded, canonical in manifest.items())
    )
    failures = [outcome for outcome in outcomes if outcome]
    if failures:
        raise EvalError("ingestion failed:\n  " + "\n  ".join(failures))


async def _wait_until_searchable(
    client: Any,
    manifest: dict[str, str],
    timeout: float,
) -> None:
    """Poll until every uploaded file returns from search.

    A completed task does not prove the chunks are indexed and visible, and a
    question scored against a half-indexed corpus would look like a miss.
    """
    from openrag_sdk import SearchFilters

    pending = set(manifest)
    deadline = time.monotonic() + timeout
    delay = 1.0
    while True:
        for uploaded_name in sorted(pending):
            response = await client.search.query(
                "*",
                filters=SearchFilters(data_sources=[uploaded_name]),
                limit=1,
            )
            if any(result.filename == uploaded_name for result in response.results):
                pending.discard(uploaded_name)
        if not pending:
            return
        if time.monotonic() >= deadline:
            names = ", ".join(sorted(manifest[name] for name in pending))
            raise EvalError(f"not searchable after {timeout:.0f}s: {names}")
        await asyncio.sleep(delay)
        delay = min(delay * 2, 8.0)


async def _settings_snapshot(client: Any) -> tuple[dict[str, Any] | None, str | None]:
    try:
        settings = await client.settings.get()
    except Exception as exc:
        return None, f"could not read /v1/settings: {type(exc).__name__}: {exc}"
    return settings.knowledge.model_dump(), None


async def _run_queries(
    client: Any,
    queries: list[dataset.Query],
    manifest: dict[str, str],
    run_prefix: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    from openrag_sdk import SearchFilters

    corpus_names = frozenset(manifest.values())
    scope = SearchFilters(data_sources=sorted(manifest))
    records: list[dict[str, Any]] = []
    for query in queries:
        response = await client.search.query(
            query.query,
            filters=scope,
            limit=args.fetch_limit,
            score_threshold=args.score_threshold,
        )
        chunks = [metrics.Chunk(r.filename, r.text, r.score) for r in response.results]
        ranked = metrics.rank_files(chunks, run_prefix, corpus_names, query.expected_text)
        scores = metrics.score_query(ranked, query.expected_files, args.k_values)
        snippet_found = None
        passage: dict[str, Any] = {}
        if query.expected_text is not None:
            snippet_found = any(
                item.snippet_found for item in ranked if item.filename in query.expected_files
            )
            rank = metrics.passage_rank(
                chunks, run_prefix, corpus_names, query.expected_files, query.expected_text
            )
            passage = {"passage_rank": rank}
            scores.update(metrics.score_passage(rank, args.k_values))
        records.append(
            {
                "id": query.id,
                "query": query.query,
                "tags": list(query.tags),
                "expected_files": list(query.expected_files),
                "expected_text": query.expected_text,
                "chunks_returned": len(chunks),
                "unique_files_returned": len(ranked),
                "ranked_files": [
                    {
                        "filename": item.filename,
                        "rank": item.rank,
                        "score": item.score,
                        "snippet_found": item.snippet_found,
                    }
                    for item in ranked
                ],
                "expected_ranks": metrics.expected_ranks(ranked, query.expected_files),
                "snippet_found": snippet_found,
                **passage,
                "metrics": scores,
            }
        )
    return records


async def _cleanup(client: Any, manifest: dict[str, str]) -> list[str]:
    """Delete this run's documents by exact filename and confirm they are gone."""
    from openrag_sdk import SearchFilters

    warnings: list[str] = []
    for uploaded_name in manifest:
        try:
            await client.documents.delete(filename=uploaded_name)
        except Exception as exc:
            warnings.append(f"could not delete {uploaded_name}: {type(exc).__name__}: {exc}")
    try:
        response = await client.search.query(
            "*",
            filters=SearchFilters(data_sources=sorted(manifest)),
            limit=len(manifest),
        )
    except Exception as exc:
        warnings.append(f"could not confirm cleanup: {type(exc).__name__}: {exc}")
    else:
        leftover = sorted({r.filename for r in response.results if r.filename in manifest})
        if leftover:
            warnings.append("still searchable after delete: " + ", ".join(leftover))
    return warnings


async def run(args: argparse.Namespace) -> int:
    corpus_names = dataset.list_corpus(args.corpus)
    queries = dataset.load_queries(args.queries, corpus_names, args.corpus)
    if args.validate_only:
        print(f"OK: {len(corpus_names)} documents, {len(queries)} questions")
        return 0
    # Read the baseline before the run so a bad path or an incomparable
    # baseline fails in seconds.
    baseline = report.load_results(args.baseline) if args.baseline else None
    if baseline is not None:
        report.compare_k(
            baseline["run"],
            {"k_values": args.k_values, "primary_k": metrics.primary_k(args.k_values)},
        )
    if not args.api_key:
        raise EvalError("no API key: set OPENRAG_API_KEY or pass --api-key")

    from openrag_sdk import OpenRAGClient

    started_at = datetime.now(UTC)
    started = time.monotonic()
    run_id = f"eval-{uuid.uuid4().hex[:8]}"
    run_prefix = f"{run_id}-"
    manifest = {f"{run_prefix}{name}": name for name in corpus_names}

    target_url = report.redact_url(args.url)
    print(f"Run {run_id}: {len(corpus_names)} documents, {len(queries)} questions → {target_url}")
    async with OpenRAGClient(
        api_key=args.api_key, base_url=args.url, timeout=args.request_timeout
    ) as client:
        try:
            print("Ingesting corpus...")
            await _ingest_corpus(
                client, args.corpus, manifest, run_id, args.concurrency, args.ingest_timeout
            )
            await _wait_until_searchable(client, manifest, args.visibility_timeout)
            settings, settings_note = await _settings_snapshot(client)
            print("Running questions...")
            records = await _run_queries(client, queries, manifest, run_prefix, args)
        finally:
            if args.keep_documents:
                print(f"Kept documents with prefix {run_prefix}")
            else:
                for warning in await _cleanup(client, manifest):
                    print(f"warning: cleanup: {warning}", file=sys.stderr)

    results = {
        "schema_version": report.SCHEMA_VERSION,
        "run": {
            "run_id": run_id,
            "timestamp": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_s": round(time.monotonic() - started, 1),
            "target_url": target_url,
            "sdk_version": _sdk_version(),
            "git_commit": _git_commit(),
            "corpus_files": len(corpus_names),
            "corpus_hash": dataset.hash_corpus(args.corpus, corpus_names),
            "query_count": len(queries),
            "passage_questions": sum(1 for query in queries if query.expected_text is not None),
            "queries_hash": dataset.hash_file(args.queries),
            "k_values": args.k_values,
            "primary_k": metrics.primary_k(args.k_values),
            "fetch_limit": args.fetch_limit,
            "score_threshold": args.score_threshold,
        },
        "settings": settings,
        "settings_note": settings_note,
        "metrics": metrics.aggregate(
            [record["metrics"] for record in records],
            [record["tags"] for record in records],
        ),
        "queries": records,
    }
    diff = report.diff_results(baseline, results) if baseline is not None else None
    summary = report.render_summary(results, diff)
    written = report.write_results(results, summary, args.output_dir, started_at)

    print()
    print(summary)
    print("Wrote:")
    for path in written:
        print(f"  {path}")
    if diff is not None and args.max_recall_drop is not None:
        failure = report.recall_gate_failure(diff, args.max_recall_drop)
        if failure:
            print(f"error: {failure}", file=sys.stderr)
            return 1
    return 0


def _explain(exc: Exception, url: str) -> str:
    """A reason for a failed request that says what to fix."""
    status = getattr(exc, "status_code", None)
    text = str(exc)
    if status == 401:
        return "the API key was rejected; create a new one under Settings → API Keys"
    if status == 403:
        return f"the API key lacks a permission this needs ({text})"
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return (
            f"the TLS certificate of {url} is not trusted; point SSL_CERT_FILE at the "
            "CA bundle that signed it"
        )
    if type(exc).__name__ in ("ConnectError", "ConnectTimeout"):
        return f"cannot reach {url}: {text or type(exc).__name__}"
    return f"{type(exc).__name__}: {text}"


async def _list_leftovers(client: Any, corpus_names: list[str]) -> list[dataset.Leftover]:
    """Every document the stack lists for this key that an earlier run uploaded."""
    files: list[tuple[str, str | None]] = []
    after_key: str | None = None
    while True:
        page = await client.documents.list_files(search="eval-", page_size=500, after_key=after_key)
        files += [(record.filename, record.indexed_time) for record in page.files]
        if not page.files or not page.after_key:
            break
        after_key = json.dumps(page.after_key)
    return dataset.find_leftovers(files, corpus_names)


def _describe_runs(leftovers: list[dataset.Leftover]) -> str:
    runs = sorted({item.run_id for item in leftovers})
    noun = "run" if len(runs) == 1 else "runs"
    return f"{len(leftovers)} documents from {len(runs)} earlier {noun}"


async def check(args: argparse.Namespace) -> int:
    """Check that a stack is ready for a run without uploading anything."""
    corpus_names = dataset.list_corpus(args.corpus)
    queries = dataset.load_queries(args.queries, corpus_names, args.corpus)
    if not args.api_key:
        raise EvalError("no API key: set OPENRAG_API_KEY or pass --api-key")

    from openrag_sdk import OpenRAGClient, SearchFilters

    target_url = report.redact_url(args.url)
    print(f"Checking {target_url}")
    print(f"  ok    dataset: {len(corpus_names)} documents, {len(queries)} questions")
    failed = False
    async with OpenRAGClient(
        api_key=args.api_key, base_url=args.url, timeout=args.request_timeout
    ) as client:
        try:
            # Scoped to a name no run uses, so nothing is returned.
            await client.search.query(
                "*", filters=SearchFilters(data_sources=["eval-check-0000"]), limit=1
            )
        except Exception as exc:
            print(f"  FAIL  search: {_explain(exc, target_url)}")
            return 1
        print("  ok    search: the stack answered and accepted the API key")

        settings, settings_note = await _settings_snapshot(client)
        if settings is None:
            failed = True
            print(
                f"  FAIL  settings: {settings_note}. A run would still score, but its "
                "results could not be compared with a baseline or become one; the key "
                "needs providers:read"
            )
        else:
            print(
                f"  ok    settings: {settings.get('embedding_provider')} "
                f"{settings.get('embedding_model')}, chunk size {settings.get('chunk_size')}, "
                f"overlap {settings.get('chunk_overlap')}"
            )

        try:
            leftovers = await _list_leftovers(client, corpus_names)
        except Exception as exc:
            failed = True
            print(f"  FAIL  documents: cannot list documents: {_explain(exc, target_url)}")
        else:
            if leftovers:
                print(
                    f"  note  documents: {_describe_runs(leftovers)} are still in the stack; "
                    "`run_eval.py cleanup` lists them"
                )
            else:
                print("  ok    documents: no earlier run left documents behind")

    print(
        "Not checked: uploading and deleting documents (knowledge:upload, "
        "knowledge:delete:own) need a real run."
    )
    print("Not ready for a run." if failed else "Ready for a run.")
    return 1 if failed else 0


async def cleanup(args: argparse.Namespace) -> int:
    """List the documents interrupted runs left behind and, with --yes, delete them."""
    corpus_names = dataset.list_corpus(args.corpus)
    if not args.api_key:
        raise EvalError("no API key: set OPENRAG_API_KEY or pass --api-key")

    from openrag_sdk import OpenRAGClient

    target_url = report.redact_url(args.url)
    min_age = timedelta(minutes=args.min_age)
    now = datetime.now(UTC)
    async with OpenRAGClient(
        api_key=args.api_key, base_url=args.url, timeout=args.request_timeout
    ) as client:
        try:
            leftovers = await _list_leftovers(client, corpus_names)
        except Exception as exc:
            raise EvalError(f"cannot list documents: {_explain(exc, target_url)}") from exc
        if not leftovers:
            print(f"No documents from earlier runs in {target_url}.")
            return 0

        to_delete = [item for item in leftovers if dataset.old_enough(item, now, min_age)]
        kept = len(leftovers) - len(to_delete)
        print(f"{_describe_runs(leftovers)} in {target_url}:")
        for run_id in sorted({item.run_id for item in leftovers}):
            files = [item for item in leftovers if item.run_id == run_id]
            times = [item.indexed_time for item in files if item.indexed_time]
            when = min(times).strftime("%Y-%m-%d %H:%M UTC") if times else "unknown time"
            action = "delete" if all(item in to_delete for item in files) else "keep"
            print(f"  {run_id}  {len(files)} documents, indexed {when}  → {action}")
        if kept:
            print(
                f"Keeping {kept} documents indexed less than {args.min_age:g} minutes ago or "
                "at an unknown time, since their run may still be going. Lower --min-age "
                "to include them."
            )
        if not to_delete:
            return 0
        if not args.yes:
            print(f"Run again with --yes to delete {len(to_delete)} documents.")
            return 0

        failures = []
        for item in to_delete:
            try:
                response = await client.documents.delete(filename=item.filename)
            except Exception as exc:
                failures.append(f"{item.filename}: {_explain(exc, target_url)}")
                continue
            if not response.success:
                failures.append(f"{item.filename}: {response.error or 'not deleted'}")
    print(f"Deleted {len(to_delete) - len(failures)} of {len(to_delete)} documents.")
    for failure in failures:
        print(f"warning: {failure}", file=sys.stderr)
    return 1 if failures else 0


def compare(args: argparse.Namespace) -> int:
    diff = report.diff_results(
        report.load_results(args.baseline),
        report.load_results(args.current),
    )
    print(report.render_diff(diff))
    return 0


NOT_PROMOTED = 3


def promote(args: argparse.Namespace) -> int:
    current = report.load_results(args.current)
    baseline = report.load_results(args.baseline) if args.baseline.exists() else None
    promoted, reason = report.promotion_decision(baseline, current, args.min_gain)
    if not promoted:
        print(f"Baseline not updated: {reason}")
        return NOT_PROMOTED
    args.baseline.parent.mkdir(parents=True, exist_ok=True)
    args.baseline.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline updated ({reason}): {args.baseline}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "promote" and args.min_gain < 0:
        parser.error("--min-gain must not be negative")
    if args.command == "run" and args.max_recall_drop is not None:
        if args.max_recall_drop < 0:
            parser.error("--max-recall-drop must not be negative")
        if args.baseline is None:
            parser.error("--max-recall-drop needs --baseline to compare against")
    if args.command == "run" and args.fetch_limit < max(args.k_values):
        # Fewer chunks than the largest cutoff cannot fill that many file
        # ranks, so recall@k and nDCG@k at that cutoff would be meaningless.
        parser.error(
            f"--fetch-limit must be at least the largest --k value "
            f"({max(args.k_values)}), got {args.fetch_limit}"
        )
    try:
        if args.command == "compare":
            return compare(args)
        if args.command == "promote":
            return promote(args)
        if args.command == "check":
            return asyncio.run(check(args))
        if args.command == "cleanup":
            if args.min_age < 0:
                parser.error("--min-age must not be negative")
            return asyncio.run(cleanup(args))
        return asyncio.run(run(args))
    except (dataset.DatasetError, report.ResultsError, EvalError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
