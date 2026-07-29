#!/usr/bin/env python3
"""FileNet P8 — GraphQL coverage sampler.

Companion to `filenet-p8-mcp-feature-assessment.md` §4.c-3 #1c / recipe Step 4.
Produces the four measurements Step 4 owes, in one pass:

    (i)   CBR-index rate        — findable by CONTAINS()
    (ii)  TXE-annotation rate   — fetchable by get_document_text_extract
    (iii) the GAP: (i) minus (ii) — "Mode A at corpus scale": findable, unfetchable,
          silently dropped by src/agent.py:645. The most decision-relevant number.
    (iv)  document shape + extract quality — narrative vs figure/table-driven,
          plus the U+FFFD / ligature / run-on corruption rates.

...plus the extract-size distribution (min / median / p95) that sets the
windowing caps in §1.b.2.

The annotation filter here deliberately mirrors the UPSTREAM logic in
`cs_mcp_server/utils/utils.py` (className match + `annotatedContentElement is not
None` + non-empty `downloadUrl`), so what this reports is what the MCP tool will
actually see — not what is theoretically present in the repository.

Credentials are read from the environment only; nothing is persisted.

Usage:
    export CPE_URL='https://<cpe-host>/content-services-graphql/graphql'
    export CPE_USER='<least-privilege-service-account>'
    export CPE_PASSWORD='<account password>'   # NOT a Zen apikey — see §4.c-3 #3
    export OBJECT_STORE='FNOS1DS'

    uv run python filenet-p8-graphql-sampler.py --sample 40
    uv run python filenet-p8-graphql-sampler.py --ids-file guids.txt --json report.json

    # Latency, Tiers 1 and 2 of the §4.c-3 #4 plan (CPE floor only — see run_latency)
    uv run python filenet-p8-graphql-sampler.py --latency --sample 30 --reps 5 \
        --term report --concurrent 5
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field

import httpx

TEXT_EXTRACT_ANNOTATION_CLASS = "TxeTextExtractAnnotation"
MODE_B_SENTINEL = "Error: Failed to download text content"

# Mirrors _escape_special_characters in cs_mcp_server/tools/documents.py.
CBR_ESCAPE = re.compile(r"([\*\@\[\]\{\}\\\^\:\=\!\/\>\<\-\%\+\?\;\'\~\|])")

# Ligatures that survive extraction as single code points (recoverable via NFKC).
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}

# Two pools — OLDEST-first and NEWEST-first — merged and stride-sampled across the
# date range. A single ASC query plus a head-slice is NOT a sample: on a test
# cluster it returns nothing but the oldest seed/junk data and silently excludes
# the corpus you actually care about. (Learned the hard way, 2026-07-24.)
ENUM_SQL_ASC = """
SELECT d.Id, d.Name, d.DateCreated, d.ContentSize, d.MimeType,
       d.IndexationId, d.CmIndexingFailureCode
FROM Document d
WHERE d.VersionStatus = 1 AND d.IsCurrentVersion = TRUE
ORDER BY d.DateCreated ASC
"""

ENUM_SQL_DESC = ENUM_SQL_ASC.replace("ORDER BY d.DateCreated ASC", "ORDER BY d.DateCreated DESC")

# Records below this size, or with these MIME types, are counted separately rather
# than diluting the coverage rates. A 4-byte text/plain file has no extract because
# there is nothing to extract; scoring it as a coverage miss is meaningless.
JUNK_MIN_BYTES = 1024
JUNK_MIME_PREFIXES = ("application/java-archive", "application/octet-stream", "application/zip")

ENUM_GQL = """
query ($repo: String!, $sql: String!) {
  repositoryRows(repositoryIdentifier: $repo, sql: $sql) {
    repositoryRows { properties { id type value } }
  }
}
"""

# Same query shape the server runs (utils/utils.py:106) — a pass here means the
# tool gets at least this far.
ANNOTATIONS_GQL = """
query ($repo: String!, $id: String!) {
  document(repositoryIdentifier: $repo, identifier: $id) {
    id
    annotations {
      annotations {
        id className annotatedContentElement
        contentElements { ... on ContentTransfer { downloadUrl retrievalName contentSize } }
      }
    }
  }
}
"""

CBR_PROBE_GQL = """
query ($repo: String!, $sql: String!) {
  repositoryRows(repositoryIdentifier: $repo, sql: $sql) {
    repositoryRows { properties { id type value } }
  }
}
"""


@dataclass
class DocRecord:
    doc_id: str
    name: str = ""
    date_created: str = ""
    content_size: float | None = None  # SOURCE FILE bytes — not extract length
    mime_type: str = ""
    indexation_id: str | None = None
    indexing_failure: int | None = None
    # (ii)
    has_txe_annotation: bool = False
    has_download_url: bool = False
    annotation_content_size: float | None = None
    # extract
    extract_chars: int | None = None
    extract_error: str = ""
    mode_b: bool = False
    # (i) ground truth
    cbr_probe: str = "not-run"  # found | not-found | no-clean-phrase | error
    # (iv)
    quality: dict = field(default_factory=dict)


def gql(client: httpx.Client, url: str, query: str, variables: dict) -> dict:
    r = client.post(url, json={"query": query, "variables": variables})
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(json.dumps(body["errors"])[:400])
    return body.get("data") or {}


def props_to_dict(row: dict) -> dict:
    """Flatten a repositoryRows row. Read properties[], never a flattened view —
    upstream's flattened mapping has two confirmed bugs (see §4.a)."""
    return {p["id"]: p.get("value") for p in row.get("properties", [])}


def _row_to_record(row: dict) -> DocRecord | None:
    p = props_to_dict(row)
    doc_id = p.get("Id") or ""
    if not doc_id:
        return None
    return DocRecord(
        doc_id=doc_id,
        name=p.get("Name") or "",
        date_created=str(p.get("DateCreated") or ""),
        content_size=p.get("ContentSize"),
        mime_type=p.get("MimeType") or "",
        indexation_id=p.get("IndexationId"),
        indexing_failure=p.get("CmIndexingFailureCode"),
    )


def is_junk(rec: DocRecord) -> bool:
    """Seed/scratch objects that cannot have a meaningful extract."""
    if rec.mime_type.startswith(JUNK_MIME_PREFIXES):
        return True
    return (rec.content_size or 0) < JUNK_MIN_BYTES


def enumerate_documents(
    client: httpx.Client, url: str, store: str, limit: int, keep_junk: bool = False
) -> tuple[list[DocRecord], list[DocRecord]]:
    """Stride-sample across the whole date range, not the head of it.

    Returns (sampled, excluded_junk).
    """
    pool: dict[str, DocRecord] = {}
    for sql in (ENUM_SQL_ASC, ENUM_SQL_DESC):
        data = gql(client, url, ENUM_GQL, {"repo": store, "sql": sql.strip()})
        for row in (data.get("repositoryRows") or {}).get("repositoryRows") or []:
            rec = _row_to_record(row)
            if rec:
                pool.setdefault(rec.doc_id, rec)

    everything = sorted(pool.values(), key=lambda r: r.date_created)
    junk = [] if keep_junk else [r for r in everything if is_junk(r)]
    candidates = everything if keep_junk else [r for r in everything if not is_junk(r)]

    if len(candidates) <= limit:
        return candidates, junk

    # Even stride across the date-sorted candidates, so old and recent are both hit.
    step = len(candidates) / limit
    sampled = [candidates[min(len(candidates) - 1, int(i * step))] for i in range(limit)]
    # Always include the true extremes — the oldest is where annotations stop
    # existing, the newest is what the customer is loading today.
    if candidates[0] not in sampled:
        sampled[0] = candidates[0]
    if candidates[-1] not in sampled:
        sampled[-1] = candidates[-1]
    return sampled, junk


def fetch_annotation(client: httpx.Client, url: str, store: str, rec: DocRecord) -> str | None:
    """Return the annotation's relative downloadUrl, applying the upstream filter."""
    data = gql(client, url, ANNOTATIONS_GQL, {"repo": store, "id": rec.doc_id})
    doc = data.get("document") or {}
    anns = ((doc.get("annotations") or {}).get("annotations")) or []
    for ann in anns:
        if ann.get("className") != TEXT_EXTRACT_ANNOTATION_CLASS:
            continue
        # NOTE: `is not None`, NOT truthiness — real data returns 0 and 0 is falsy.
        if ann.get("annotatedContentElement") is None:
            continue
        rec.has_txe_annotation = True
        for el in ann.get("contentElements") or []:
            durl = el.get("downloadUrl")
            if durl:
                rec.has_download_url = True
                rec.annotation_content_size = el.get("contentSize")
                return durl
    return None


def download_extract(client: httpx.Client, graphql_url: str, download_url: str) -> str:
    """Resolve exactly as GraphQLClient._prepare_download_url does (line 1041)."""
    base = graphql_url.removesuffix("/graphql")
    r = client.get(base + download_url)
    r.raise_for_status()
    return r.text


def clean_phrase(text: str, words: int = 4) -> str | None:
    """Pick a distinctive phrase with no corruption — the fairest CBR probe.

    If a *clean* phrase from a document's own extract does not find that document,
    the document is very likely absent from the CBR index.

    Degrades 4 words -> 3 -> 2 and relaxes the minimum word length, because short
    extracts often have no run of four long clean words (2/28 probes were skipped
    for this reason on the 2026-07-24 run).
    """
    toks = text.split()
    for n, min_len in ((words, 5), (3, 5), (3, 4), (2, 4)):
        run: list[str] = []
        for t in toks:
            ok = (
                t.isalpha()
                and len(t) >= min_len
                and "�" not in t
                and not any(lig in t for lig in LIGATURES)
            )
            if ok:
                run.append(t)
                if len(run) == n:
                    return " ".join(run)
            else:
                run = []
    return None


def cbr_sql(phrase: str, rows_limit: int = 50) -> str:
    """Build the same CBR SQL `cbr_search` builds (tools/documents.py:1301-1326),
    including the identical term escaping, so timings reflect the real query."""
    term = CBR_ESCAPE.sub(r"\\\1", phrase.lower())
    return (
        "SELECT d.This, c.Rank FROM Document d "
        "INNER JOIN ContentSearch c ON d.This = c.QueriedObject "
        f"WHERE CONTAINS(d.*, '{term}') AND d.VersionStatus=1 "
        f"ORDER BY c.Rank DESC OPTIONS (FULLTEXTROWLIMIT {rows_limit})"
    )


def cbr_probe(client: httpx.Client, url: str, store: str, phrase: str, doc_id: str) -> str:
    sql = cbr_sql(phrase, rows_limit=50)
    try:
        data = gql(client, url, CBR_PROBE_GQL, {"repo": store, "sql": sql})
    except Exception:
        return "error"
    rows = (data.get("repositoryRows") or {}).get("repositoryRows") or []
    target = doc_id.strip("{}").upper()
    for row in rows:
        blob = json.dumps(row).upper()
        if target in blob:
            return "found"
    return "not-found"


def analyze_extract(text: str) -> dict:
    """(iv) — extract quality and document shape."""
    toks = text.split()
    n_words = len(toks) or 1
    replacement = text.count("�")
    lig_counts = {name: text.count(ch) for ch, name in LIGATURES.items() if text.count(ch)}
    lig_total = sum(lig_counts.values())
    # Run-ons come in two shapes and they OVERLAP — count the union, not the sum.
    # (a) camelCase joins where a capitalised word was glued on: "ThepopulationofAdams..."
    # (b) long all-lowercase joins with no capital at all: "causesmostofthechanges..."
    run_ons = {w for w in toks if len(w) >= 20 and re.search(r"[a-z][A-Z]", w)} | {
        w for w in toks if len(w) >= 25 and w.isalpha()
    }
    numeric = [t for t in toks if re.fullmatch(r"[\$\(]?[\d,\.]+%?\)?", t)]
    numeric_ratio = len(numeric) / n_words
    figure_refs = len(re.findall(r"\b(plot|chart|figure|graph|diagram)s?\b", text, re.I))
    shown_here = len(re.findall(r"shown here|areshownhere|is shown", text, re.I))
    table_captions = len(re.findall(r"Table \d+:", text))

    # Shape heuristic, in confidence order. STRONG signals are explicit references
    # to figures/tables in the prose; numeric density ALONE is weak — on the
    # 2026-07-24 run it classified a payroll summary and a sports-analytics report
    # as figure-driven with zero figure refs and zero table captions, which may or
    # may not be right. Report that case separately rather than pretending certainty.
    strong = (figure_refs + shown_here) >= 5 or table_captions >= 3
    if strong:
        shape = "figure/table-driven"
    elif numeric_ratio >= 0.15:
        shape = "numeric-dense (unverified)"
    else:
        shape = "narrative"

    nfkc_recoverable = lig_total
    unrecoverable = replacement

    return {
        "chars": len(text),
        "words": len(toks),
        "shape": shape,
        "figure_refs": figure_refs,
        "shown_here": shown_here,
        "table_captions": table_captions,
        "numeric_token_ratio": round(numeric_ratio, 4),
        "replacement_chars_UNRECOVERABLE": unrecoverable,
        "ligatures_nfkc_recoverable": nfkc_recoverable,
        "ligature_breakdown": lig_counts,
        "run_on_tokens": len(run_ons),
        "longest_run_on": max((len(w) for w in run_ons), default=0),
        "corrupted_word_rate": round((replacement + lig_total) / n_words, 4),
        "nfkc_changes_text": unicodedata.normalize("NFKC", text) != text,
    }


# ---------------------------------------------------------------------------
# Latency mode (Tiers 1 and 2 of the §4.c-3 #4 measurement plan)
#
# SCOPE — read before quoting any number from this mode.
#   This script talks DIRECTLY to the CPE GraphQL API, not through the MCP
#   server. What it measures is therefore the CPE-side FLOOR: the irreducible
#   server cost of the same queries the tool issues. It does NOT include
#   FastMCP/stdio overhead, the MCP server's metadata_cache cold-start, or any
#   agent/LLM turns — those are additive on top, and the agent hops (Tier 3)
#   are expected to dominate the user-visible number.
#   Treat these results as "the best CPE could possibly do", not as chat latency.
# ---------------------------------------------------------------------------


def timed(fn, *args, **kwargs) -> tuple[object, float]:
    """Run fn, return (result, elapsed_ms). Exceptions are returned, not raised,
    so one slow/failing document cannot abort a timing sweep."""
    t0 = time.perf_counter()
    try:
        out = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - deliberate: record and continue
        out = exc
    return out, (time.perf_counter() - t0) * 1000.0


def summarize(name: str, samples: list[float], extra: str = "") -> None:
    if not samples:
        print(f"  {name:<44s} (no samples)")
        return
    s = sorted(samples)
    p50 = s[len(s) // 2]
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    print(
        f"  {name:<44s} n={len(s):3d}  p50={p50:8.1f}ms  p95={p95:8.1f}ms  "
        f"min={s[0]:7.1f}  max={s[-1]:7.1f}  {extra}"
    )


def latency_targets(recs: list[DocRecord]) -> list[tuple[str, DocRecord]]:
    """Pick documents at p50 / p90 / p99 of extract size — the tail is what
    matters, since extract length is skewed ~18x from median to p95."""
    sized = sorted(
        (r for r in recs if r.annotation_content_size and r.has_download_url),
        key=lambda r: r.annotation_content_size or 0,
    )
    if not sized:
        return []
    picks = []
    for label, q in (("p50", 0.50), ("p90", 0.90), ("p99", 0.99)):
        idx = min(len(sized) - 1, int(round(q * (len(sized) - 1))))
        picks.append((label, sized[idx]))
    return picks


def run_latency(client: httpx.Client, url: str, store: str, recs: list[DocRecord], args) -> None:
    reps = args.reps

    print("\n" + "=" * 78)
    print("LATENCY REPORT — Tiers 1 and 2 (CPE floor, direct GraphQL)")
    print("=" * 78)
    print("  NOTE: excludes MCP/FastMCP overhead, metadata_cache cold-start, and all")
    print("        agent/LLM turns. Additive on top; Tier 3 is expected to dominate.")
    print("  NETWORK POSITION MATTERS: run this from where the sidecar will run.")
    print("  A laptop-to-cluster number is not the deployed number (§4.d Phase 3).")

    # ---- Tier 1a: does result count drive search cost? --------------------
    print(f"\nTIER 1a — document_search cost vs max_results   (term={args.term!r})")
    search_p50: dict[int, float] = {}
    for rows_limit in (10, 25, 50):
        sql = cbr_sql(args.term, rows_limit)
        samples = []
        hits = 0
        for _ in range(reps):
            res, ms = timed(gql, client, url, CBR_PROBE_GQL, {"repo": store, "sql": sql})
            if isinstance(res, Exception):
                continue
            hits = len(((res.get("repositoryRows") or {}).get("repositoryRows")) or [])
            samples.append(ms)
        if samples:
            search_p50[rows_limit] = sorted(samples)[len(samples) // 2]
        summarize(f"CONTAINS() FULLTEXTROWLIMIT {rows_limit}", samples, f"hits={hits}")
    if len(search_p50) >= 2:
        lo, hi = min(search_p50), max(search_p50)
        ratio = search_p50[hi] / search_p50[lo] if search_p50[lo] else 0
        verdict = (
            "scales with result count -> cap max_results"
            if ratio > 1.5
            else "flat -> cost is the CBR scan, not the row count"
        )
        print(f"    -> {lo}->{hi} rows costs {ratio:.2f}x : {verdict}")

    # ---- Tier 1b: split the two round trips, across the size distribution --
    print("\nTIER 1b — get_document_text_extract, split by round trip and size")
    print("           (each tool call = 1 annotations POST + 1 download GET)")
    picks = latency_targets(recs)
    if not picks:
        print("  no sized documents available — run without --latency first, or widen --sample")
    for label, rec in picks:
        size = rec.annotation_content_size or 0
        ann_ms, dl_ms, dl_bytes = [], [], 0
        for _ in range(reps):
            durl, ms = timed(fetch_annotation, client, url, store, rec)
            ann_ms.append(ms)
            if isinstance(durl, Exception) or not durl:
                continue
            text, ms2 = timed(download_extract, client, url, durl)
            if isinstance(text, Exception):
                continue
            dl_bytes = len(text)
            dl_ms.append(ms2)
        tag = f"[{label} {size:,.0f} chars] {rec.name[:26]}"
        summarize(f"{tag} annotations POST", ann_ms)
        kb = max(dl_bytes / 1024.0, 0.001)
        per_kb = (sorted(dl_ms)[len(dl_ms) // 2] / kb) if dl_ms else 0
        summarize(f"{tag} download GET", dl_ms, f"{per_kb:.2f}ms/KB")
        if ann_ms and dl_ms:
            a, d = sorted(ann_ms)[len(ann_ms) // 2], sorted(dl_ms)[len(dl_ms) // 2]
            print(
                f"    -> {'download' if d > a else 'annotations query'} dominates "
                f"({max(a, d) / max(min(a, d), 0.001):.1f}x)"
            )

    # ---- Tier 2: realistic shape, serial vs parallel ----------------------
    print("\nTIER 2 — search + K fetches, SERIAL vs PARALLEL")
    print("           (§1.b.2 assumes parallel fetch makes wall time ~max, not sum)")
    p95_par: dict[int, float] = {}
    fetchable = [r for r in recs if r.has_download_url and r.annotation_content_size]
    if not fetchable:
        print("  no fetchable documents available")
    else:

        def one_fetch(rec: DocRecord) -> int:
            durl = fetch_annotation(client, url, store, rec)
            if not durl:
                return 0
            return len(download_extract(client, url, durl))

        for k in (3, 5, 10):
            batch = fetchable[:k]
            if len(batch) < k:
                continue
            ser, par = [], []
            for _ in range(reps):
                _, ms = timed(lambda b=batch: [one_fetch(r) for r in b])
                ser.append(ms)

                def run_parallel(b=batch):
                    with cf.ThreadPoolExecutor(max_workers=len(b)) as ex:
                        return list(ex.map(one_fetch, b))

                _, ms = timed(run_parallel)
                par.append(ms)
            summarize(f"K={k} serial   ({2 * k} round trips)", ser)
            summarize(f"K={k} parallel ({2 * k} round trips)", par)
            if par:
                p95_par[k] = sorted(par)[min(len(par) - 1, int(round(0.95 * (len(par) - 1))))]
            if ser and par:
                sp = sorted(ser)[len(ser) // 2] / max(sorted(par)[len(par) // 2], 0.001)
                if sp < 1.3:
                    print(
                        f"    -> speedup {sp:.2f}x : *** PARALLELISM DOES NOT HOLD *** "
                        "CPE is serialising or throttling; §1.b.2's latency model is wrong."
                    )
                else:
                    print(f"    -> speedup {sp:.2f}x : parallel fetch is effective")

    # ---- optional: concurrent users --------------------------------------
    if args.concurrent > 1:
        print(
            f"\nTIER 2b — {args.concurrent} CONCURRENT queries (CPE queueing under shared identity)"
        )
        sql = cbr_sql(args.term, 10)

        def one_search():
            return gql(client, url, CBR_PROBE_GQL, {"repo": store, "sql": sql})

        for users in (1, args.concurrent):
            samples = []
            for _ in range(reps):
                with cf.ThreadPoolExecutor(max_workers=users) as ex:
                    futs = [ex.submit(lambda: timed(one_search)) for _ in range(users)]
                    for f in futs:
                        _, ms = f.result()
                        samples.append(ms)
            summarize(f"{users} concurrent searcher(s)", samples)

    # ---- verdict against the agreed budget --------------------------------
    print("\n" + "-" * 78)
    print(
        f"BUDGET CHECK — retrieval-only target p95 <= {args.target_ms:.0f}ms "
        "(excludes LLM turns; agree this number before quoting it)"
    )
    search_ms = search_p50.get(10, 0.0)
    if search_ms and 5 in p95_par:
        total = search_ms + p95_par[5]
        verdict = "PASS" if total <= args.target_ms else "FAIL"
        print(
            f"  modelled retrieval @ K=5 = search p50 {search_ms:.0f}ms "
            f"+ parallel-fetch p95 {p95_par[5]:.0f}ms = {total:.0f}ms   ->  {verdict}"
        )
        if verdict == "FAIL":
            print("  Fixes, in leverage order: (1) pre-resolve the prerequisite chain at")
            print("  startup; (2) fetch lazily — rank first, fetch only cited documents;")
            print("  (3) reduce K; (4) if the tail download dominates, the §4.d custom")
            print("      connector can stream-and-abort where the stock server cannot.")
        else:
            headroom = args.target_ms - total
            print(f"  headroom {headroom:.0f}ms for MCP overhead + agent hops — but note the")
            print("  full turn adds ~4 LLM round trips unless the prerequisite chain is")
            print("  pre-resolved at startup, which is the highest-leverage fix.")
    else:
        print("  (insufficient samples to model — need Tier 1a and a K=5 Tier 2 run)")
    print("=" * 78)


def pctl(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    idx = min(len(s) - 1, int(round(q * (len(s) - 1))))
    return s[idx]


def report(recs: list[DocRecord]) -> None:
    n = len(recs)
    if not n:
        print("No documents sampled.")
        return

    proxy_indexed = [r for r in recs if r.indexation_id and not r.indexing_failure]
    annotated = [r for r in recs if r.has_txe_annotation and r.has_download_url]
    fetched = [r for r in recs if r.extract_chars]
    probed = [r for r in recs if r.cbr_probe in ("found", "not-found")]
    probe_found = [r for r in probed if r.cbr_probe == "found"]

    # (iii) THE GAP — findable but unfetchable.
    gap = [r for r in proxy_indexed if not (r.has_txe_annotation and r.has_download_url)]
    reverse_gap = [
        r
        for r in recs
        if (r.has_txe_annotation and r.has_download_url)
        and not (r.indexation_id and not r.indexing_failure)
    ]

    print("=" * 78)
    print(f"STEP 4 COVERAGE REPORT — sample size {n}")
    print("=" * 78)

    # Sampling-validity check FIRST. A coverage number from an unrepresentative
    # sample is worse than no number, because it looks authoritative.
    dates = sorted(r.date_created[:10] for r in recs if r.date_created)
    if dates:
        span_days = 0
        try:
            from datetime import date

            d0 = date.fromisoformat(dates[0])
            d1 = date.fromisoformat(dates[-1])
            span_days = (d1 - d0).days
        except ValueError:
            pass
        print(f"\nSAMPLE VALIDITY  range {dates[0]} -> {dates[-1]}  ({span_days} days)")
        if span_days < 7:
            print("  *** WARNING: the sample spans under a week. TXE annotations are written")
            print("      at INDEX TIME, so a narrow date window cannot measure coverage of an")
            print("      estate loaded over months. Re-run with a larger --sample, or supply")
            print("      --ids-file with GUIDs spanning the real ingest history.")
        mimes: dict[str, int] = {}
        for r in recs:
            mimes[r.mime_type or "(none)"] = mimes.get(r.mime_type or "(none)", 0) + 1
        top = sorted(mimes.items(), key=lambda kv: -kv[1])[:4]
        print("  mime mix: " + ", ".join(f"{m.split('/')[-1][:28]}={c}" for m, c in top))
    print("\n(i)   CBR-index rate (proxy: IndexationId set, no failure code)")
    print(f"      {len(proxy_indexed)}/{n} = {len(proxy_indexed) / n:.1%}")
    if probed:
        print(
            f"      ground-truth CONTAINS() probe: {len(probe_found)}/{len(probed)} = "
            f"{len(probe_found) / len(probed):.1%} of probed documents found by their own text"
        )
        agree = sum(
            1
            for r in probed
            if (r.cbr_probe == "found") == bool(r.indexation_id and not r.indexing_failure)
        )
        print(
            f"      proxy/ground-truth agreement: {agree}/{len(probed)}"
            f"{'  <-- PROXY VALIDATED' if agree == len(probed) else '  <-- PROXY UNRELIABLE, trust the probe'}"
        )

    print("\n(ii)  TXE-annotation rate (upstream filter applied)")
    print(f"      {len(annotated)}/{n} = {len(annotated) / n:.1%}")
    only_ann = sum(1 for r in recs if r.has_txe_annotation and not r.has_download_url)
    if only_ann:
        print(f'      WARNING: {only_ann} have an annotation but NO downloadUrl -> tool returns ""')

    print("\n(iii) THE GAP — CBR-indexed but not fetchable  (Mode A at corpus scale)")
    print(f"      {len(gap)}/{n} = {len(gap) / n:.1%}  <-- the number that decides this feature")
    if gap:
        print('      These are findable by search and return "" on fetch: confident,')
        print("      sourceless answers with nothing in the logs (see §4.a).")
        for r in gap[:5]:
            print(f"        - {r.doc_id} {r.name}")
    print(f"      reverse gap (annotated but not indexed, benign): {len(reverse_gap)}")

    mode_b = [r for r in recs if r.mode_b]
    if mode_b:
        print(f"\n      !! MODE B: {len(mode_b)} extract(s) returned the error sentinel AS CONTENT")
        for r in mode_b[:5]:
            print(f"        - {r.doc_id} {r.name}")

    print(f"\n(iv)  Document shape and extract quality  (n={len(fetched)} extracts fetched)")
    if fetched:
        shapes: dict[str, int] = {}
        for r in fetched:
            shapes[r.quality.get("shape", "?")] = shapes.get(r.quality.get("shape", "?"), 0) + 1
        for shape, count in sorted(shapes.items(), key=lambda kv: -kv[1]):
            print(f"      {shape:22s} {count}/{len(fetched)} = {count / len(fetched):.1%}")
        fig = shapes.get("figure/table-driven", 0)
        if fig:
            print(
                f"      -> {fig / len(fetched):.0%} of fetchable documents carry their information in"
            )
            print("         figures/tables, which the extract does NOT contain. An extract exists,")
            print("         is fetchable, and is still not an answer (§4.a).")

        unrec = sum(r.quality.get("replacement_chars_UNRECOVERABLE", 0) for r in fetched)
        lig = sum(r.quality.get("ligatures_nfkc_recoverable", 0) for r in fetched)
        runon = sum(r.quality.get("run_on_tokens", 0) for r in fetched)
        words = sum(r.quality.get("words", 0) for r in fetched) or 1
        print(f"\n      corruption across {words:,} words:")
        print(f"        U+FFFD (UNRECOVERABLE, breaks exact search):  {unrec:,}")
        print(f"        ligatures (recoverable via NFKC):             {lig:,}")
        print(f"        run-on token groups (break windowing):        {runon:,}")
        print(f"        corrupted-word rate:                          {(unrec + lig) / words:.2%}")
        affected = sum(1 for r in fetched if r.quality.get("replacement_chars_UNRECOVERABLE", 0))
        print(f"        documents with >=1 unrecoverable loss:        {affected}/{len(fetched)}")

    sizes = [float(r.annotation_content_size) for r in recs if r.annotation_content_size]
    if sizes:
        print("\n      extract contentSize distribution (chars) — sets the windowing cap:")
        print(
            f"        n={len(sizes)}  min={min(sizes):,.0f}  median={statistics.median(sizes):,.0f}"
            f"  p95={pctl(sizes, 0.95):,.0f}  max={max(sizes):,.0f}"
        )
        print(
            f"        approx tokens at p95: {pctl(sizes, 0.95) / 4:,.0f}"
            f"   at K=5: {5 * pctl(sizes, 0.95) / 4:,.0f}"
        )

    srcs = [float(r.content_size) for r in recs if r.content_size]
    if srcs and sizes:
        print(
            "\n      reminder: source ContentSize does NOT predict extract length"
            " (measured ~149 bytes/char on one 2.9 MB PDF). Do not pre-filter on it."
        )

    print("\n" + "=" * 78)
    print("DECISION GUIDE")
    print("  (ii) low            -> re-index needed; cost is FileNet-side, not ours.")
    print("  (iii) non-trivial   -> the component MUST surface empty fetches loudly.")
    print("  (iv) figure/table   -> pick a narrative pilot corpus, or reposition as")
    print("                         document discovery rather than data extraction.")
    print("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser(description="FileNet P8 Step 4 coverage sampler")
    ap.add_argument("--sample", type=int, default=40, help="documents to sample (default 40)")
    ap.add_argument(
        "--ids-file", help="file of document GUIDs, one per line (skips SQL enumeration)"
    )
    ap.add_argument(
        "--no-verify-ssl", action="store_true", help="skip TLS verification (spike only)"
    )
    ap.add_argument(
        "--keep-junk",
        action="store_true",
        help=f"include sub-{JUNK_MIN_BYTES}B / archive objects (excluded by default)",
    )
    ap.add_argument(
        "--no-cbr-probe", action="store_true", help="skip the ground-truth CONTAINS() probe"
    )
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--json", help="also write the raw per-document records here")
    ap.add_argument(
        "--latency",
        action="store_true",
        help="run the Tier 1/2 latency sweep instead of the coverage report",
    )
    ap.add_argument("--reps", type=int, default=5, help="repetitions per timing (default 5)")
    ap.add_argument("--term", default="report", help="CBR search term for latency timing")
    ap.add_argument(
        "--concurrent",
        type=int,
        default=1,
        help="also run N concurrent searches (Tier 2b); 1 disables",
    )
    ap.add_argument(
        "--target-ms",
        type=float,
        default=3000.0,
        help="retrieval-only p95 budget to check against (default 3000)",
    )
    args = ap.parse_args()

    url = os.environ.get("CPE_URL", "").strip()
    user = os.environ.get("CPE_USER", "").strip()
    password = os.environ.get("CPE_PASSWORD", "")
    store = os.environ.get("OBJECT_STORE", "").strip()
    missing = [
        k
        for k, v in {
            "CPE_URL": url,
            "CPE_USER": user,
            "CPE_PASSWORD": password,
            "OBJECT_STORE": store,
        }.items()
        if not v
    ]
    if missing:
        print(f"error: missing environment variable(s): {', '.join(missing)}", file=sys.stderr)
        print(__doc__.split("Usage:")[-1], file=sys.stderr)
        return 2
    if url.endswith("/"):
        print(
            "error: CPE_URL must not end with '/' — a trailing slash silently breaks "
            "downloadUrl resolution and produces Mode B errors (§4.a).",
            file=sys.stderr,
        )
        return 2

    client = httpx.Client(
        auth=httpx.BasicAuth(user, password),
        verify=not args.no_verify_ssl,
        timeout=args.timeout,
        headers={"Content-Type": "application/json"},
    )

    with client:
        if args.ids_file:
            with open(args.ids_file, encoding="utf-8") as fh:
                ids = [ln.strip() for ln in fh if ln.strip()]
            recs = [DocRecord(doc_id=i) for i in ids[: args.sample]]
            print(f"Loaded {len(recs)} document id(s) from {args.ids_file}")
        else:
            print(f"Enumerating up to {args.sample} documents from {store} ...")
            try:
                recs, junk = enumerate_documents(client, url, store, args.sample, args.keep_junk)
                if junk:
                    print(
                        f"Excluded {len(junk)} seed/scratch object(s) "
                        f"(<{JUNK_MIN_BYTES}B or archive MIME) — pass --keep-junk to include them."
                    )
                    for j in junk[:5]:
                        print(f"    - {j.name} ({j.mime_type}, {j.content_size:.0f}B)")
            except Exception as exc:
                print(f"error: enumeration failed: {exc}", file=sys.stderr)
                print(
                    "hint: FileNet SQL dialects vary; adjust ENUM_SQL at the top of this "
                    "file, or pass --ids-file with GUIDs exported from ACCE.",
                    file=sys.stderr,
                )
                return 1
            print(f"Enumerated {len(recs)} document(s)")

        if args.latency:
            # Lightweight pass: annotations only. That yields contentSize and
            # downloadUrl, which is all the size-stratification needs — no point
            # downloading and analysing every extract before timing them.
            print(f"Profiling {len(recs)} document(s) for size stratification ...")
            for rec in recs:
                try:
                    fetch_annotation(client, url, store, rec)
                except Exception as exc:
                    rec.extract_error = f"annotations query failed: {exc}"[:200]
            run_latency(client, url, store, recs, args)
            return 0

        for i, rec in enumerate(recs, 1):
            print(f"  [{i}/{len(recs)}] {rec.doc_id} {rec.name}", flush=True)
            try:
                durl = fetch_annotation(client, url, store, rec)
            except Exception as exc:
                rec.extract_error = f"annotations query failed: {exc}"[:200]
                continue
            if not durl:
                continue
            try:
                text = download_extract(client, url, durl)
            except Exception as exc:
                rec.extract_error = f"download failed: {exc}"[:200]
                continue
            if text.startswith(MODE_B_SENTINEL):
                rec.mode_b = True
                rec.extract_error = text[:200]
                continue
            rec.extract_chars = len(text)
            rec.quality = analyze_extract(text)
            if not args.no_cbr_probe:
                phrase = clean_phrase(text)
                rec.cbr_probe = (
                    cbr_probe(client, url, store, phrase, rec.doc_id)
                    if phrase
                    else "no-clean-phrase"
                )

    print()
    report(recs)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([asdict(r) for r in recs], fh, indent=2)
        print(f"\nRaw records written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
