"""Results files, readable summary and baseline diff for the retrieval evaluation harness.

A run produces one results dict (see README.md for the schema). This module
writes it as JSON, renders a Markdown summary, and compares two results dicts
question by question so a small change in the average cannot hide the
questions that broke.

Standard library only, so it can be unit-tested without the SDK or a stack.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SCHEMA_VERSION = 1
EPSILON = 1e-9

# Run parameters that change scores on their own. A diff between two runs that
# disagree on any of them is not measuring the search change alone.
_COMPARABLE_RUN_FIELDS = (
    ("corpus_hash", "corpus"),
    ("queries_hash", "question file"),
    ("k_values", "k values"),
    ("fetch_limit", "fetch limit"),
    ("score_threshold", "score threshold"),
)


class ResultsError(ValueError):
    """A results file could not be read as harness output."""


def redact_url(url: str) -> str:
    """Drop credentials, query string and fragment so the URL is safe to store."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        # urlsplit strips the brackets from an IPv6 host; a URL needs them back.
        host = f"[{host}]"
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))


def load_results(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ResultsError(f"cannot read results file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ResultsError(f"{path} is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict) or not {"run", "metrics", "queries"} <= data.keys():
        raise ResultsError(f"{path} is not a retrieval evaluation results file")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ResultsError(
            f"{path} has schema version {data.get('schema_version')!r}; "
            f"this harness reads version {SCHEMA_VERSION}"
        )
    return data


# A JSON array of numbers that json.dumps(indent=...) spread over several lines.
# JSON strings cannot hold a raw newline, so this never matches inside a string.
# Each part can match only one way: indentation is spaces only, which is all
# json.dumps emits after a newline, and a number is one run of number
# characters. That keeps a failed match linear instead of backtracking.
_NUMBER_ARRAY = re.compile(r"\[\n *([-0-9.eE+]+(?:,\n *[-0-9.eE+]+)*)\n *\]")
_ITEM_BREAK = re.compile(r",\n *")


def dumps(results: Mapping[str, Any]) -> str:
    """Indented JSON with each array of numbers on one line.

    Chunk scores are thousands of short ``[file rank, score]`` pairs, which
    plain indentation would spread over several lines each.
    """
    text = json.dumps(results, indent=2)
    return _NUMBER_ARRAY.sub(lambda m: "[" + _ITEM_BREAK.sub(", ", m.group(1)) + "]", text) + "\n"


def write_results(
    results: Mapping[str, Any],
    summary: str,
    output_dir: Path,
    started_at: datetime,
) -> list[Path]:
    """Write results and summary twice: as the latest run and as a timestamped copy."""
    stamp = started_at.astimezone(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for stem, suffix, content in (
        ("results", ".json", dumps(results)),
        ("summary", ".md", summary),
    ):
        for path in (output_dir / f"{stem}{suffix}", output_dir / f"{stem}_{stamp}{suffix}"):
            path.write_text(content, encoding="utf-8")
            written.append(path)
    return written


def compare_k(baseline_run: Mapping[str, Any], current_run: Mapping[str, Any]) -> int:
    """The cutoff to compare two runs on, which both runs must have evaluated.

    This is the current run's primary cutoff when the baseline has it too.
    Otherwise it is 5 if both runs have it, then the largest shared cutoff.
    Raises ``ResultsError`` when the runs share no cutoff, because recall and
    nDCG could then not be compared and a regression would go unnoticed.
    """
    base_k = set(baseline_run.get("k_values") or [baseline_run["primary_k"]])
    cur_k = set(current_run.get("k_values") or [current_run["primary_k"]])
    shared = base_k & cur_k
    if not shared:
        raise ResultsError(
            f"the runs share no k value (baseline {sorted(base_k)}, "
            f"current {sorted(cur_k)}), so recall@k and nDCG@k cannot be compared"
        )
    if current_run["primary_k"] in shared:
        return int(current_run["primary_k"])
    return 5 if 5 in shared else max(shared)


def _compare_metrics(k: int) -> list[str]:
    return [f"recall@{k}", "reciprocal_rank", f"ndcg@{k}"]


def _snippet_missing(query: Mapping[str, Any]) -> list[str]:
    """Expected files that were returned without the question's expected_text.

    Such a file keeps its rank but does not count as relevant, which would
    otherwise look like a score that dropped for no reason.
    """
    expected = set(query.get("expected_files", []))
    return [
        item["filename"]
        for item in query.get("ranked_files", [])
        if item["filename"] in expected and item.get("snippet_found") is False
    ]


def _mismatch_warnings(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    base_run, cur_run = baseline["run"], current["run"]
    for field, label in _COMPARABLE_RUN_FIELDS:
        base_value = base_run.get(field)
        cur_value = cur_run.get(field)
        if field == "queries_hash":
            base_value = base_run.get("retrieval_queries_hash", base_value)
            cur_value = cur_run.get("retrieval_queries_hash", cur_value)
        if base_value != cur_value:
            warnings.append(
                f"The {label} differs between the runs "
                f"(baseline {_short(base_run.get(field))}, current {_short(cur_run.get(field))})."
            )
    base_settings = baseline.get("settings") or {}
    cur_settings = current.get("settings") or {}
    if not base_settings or not cur_settings:
        if base_settings or cur_settings:
            warnings.append("Only one run recorded the stack settings, so they cannot be compared.")
    else:
        for key in sorted(base_settings.keys() | cur_settings.keys()):
            if base_settings.get(key) != cur_settings.get(key):
                warnings.append(
                    f"Setting '{key}' differs between the runs "
                    f"(baseline {base_settings.get(key)!r}, current {cur_settings.get(key)!r})."
                )
    return warnings


def _short(value: object) -> str:
    text = str(value)
    # Hashes are long; the first 12 characters are enough to tell two apart.
    return text[:12] if isinstance(value, str) and len(text) == 64 else text


def diff_results(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    epsilon: float = EPSILON,
) -> dict[str, Any]:
    """Compare two runs question by question.

    Questions are matched by id. Each is classified on recall@k at the cutoff
    from ``compare_k``, then reciprocal rank, then nDCG@k: the first of those
    that moved by more than ``epsilon`` decides whether the question improved
    or regressed.
    """
    k = compare_k(baseline["run"], current["run"])
    metrics = _compare_metrics(k)
    base_by_id = {q["id"]: q for q in baseline["queries"]}
    cur_by_id = {q["id"]: q for q in current["queries"]}

    regressed: list[dict[str, Any]] = []
    improved: list[dict[str, Any]] = []
    unchanged = 0
    for query_id, cur in cur_by_id.items():
        base = base_by_id.get(query_id)
        if base is None:
            continue
        deltas = {
            name: {
                "baseline": base["metrics"][name],
                "current": cur["metrics"][name],
                "delta": cur["metrics"][name] - base["metrics"][name],
            }
            for name in metrics
            if name in base["metrics"] and name in cur["metrics"]
        }
        direction = next(
            (d["delta"] for d in deltas.values() if abs(d["delta"]) > epsilon),
            0.0,
        )
        if direction == 0.0:
            unchanged += 1
            continue
        entry = {
            "id": query_id,
            "query": cur["query"],
            "metrics": deltas,
            "expected_ranks": {
                "baseline": base.get("expected_ranks", {}),
                "current": cur.get("expected_ranks", {}),
            },
            "snippet_missing": {
                "baseline": _snippet_missing(base),
                "current": _snippet_missing(cur),
            },
            "passage": {"baseline": _passage(base), "current": _passage(cur)},
        }
        (improved if direction > 0 else regressed).append(entry)

    added = [query_id for query_id in cur_by_id if query_id not in base_by_id]
    removed = [query_id for query_id in base_by_id if query_id not in cur_by_id]

    base_overall = baseline["metrics"].get("overall", {})
    cur_overall = current["metrics"].get("overall", {})
    aggregate = {
        name: {
            "baseline": base_overall[name],
            "current": cur_overall[name],
            "delta": cur_overall[name] - base_overall[name],
        }
        for name in cur_overall
        if name in base_overall
    }

    warnings = _mismatch_warnings(baseline, current)
    if k != current["run"]["primary_k"]:
        warnings.append(
            f"The baseline has no recall@{current['run']['primary_k']}, "
            f"so questions are compared on recall@{k}."
        )
    # Notes are informational. Unlike warnings, they do not make the file scores
    # incomparable, so the recall gate and baseline promotion ignore them.
    notes: list[str] = []
    base_label, cur_label = baseline["run"].get("label"), current["run"].get("label")
    if base_label != cur_label:
        notes.append(
            f"The runs are labeled differently (baseline {base_label!r}, current {cur_label!r})."
        )
    if "passage_mrr" in cur_overall and "passage_mrr" not in base_overall:
        notes.append(
            "The baseline has no passage scores, so only file scores are compared. "
            "Rerun the baseline to compare passages."
        )
    answer_changes = []
    base_answers = any("answer" in q for q in baseline["queries"])
    cur_answers = any("answer" in q for q in current["queries"])
    if base_answers != cur_answers:
        notes.append("Only one run has answer scores; answer quality cannot be compared.")
    if base_answers and cur_answers:
        if baseline.get("answer_settings") != current.get("answer_settings"):
            notes.append(
                "Answer settings differ (agent, prompt, judge or retrieval limit); answer scores may not be comparable."
            )
        for query_id, cur in cur_by_id.items():
            base = base_by_id.get(query_id, {})
            before = (base.get("answer", {}).get("judgement") or {}).get("correctness")
            after = (cur.get("answer", {}).get("judgement") or {}).get("correctness")
            if before is not None and after is not None and abs(after - before) >= 1:
                answer_changes.append(
                    {
                        "id": query_id,
                        "query": cur["query"],
                        "baseline": before,
                        "current": after,
                        "delta": after - before,
                    }
                )
    if (base_answers or cur_answers) and baseline["run"].get("queries_hash") != current["run"].get(
        "queries_hash"
    ):
        notes.append("The full question file differs; answer references may have changed.")
    if added or removed:
        warnings.append(
            "The runs do not cover the same questions, so the aggregate deltas "
            "are not a like-for-like comparison."
        )

    return {
        "baseline_run_id": baseline["run"].get("run_id"),
        "current_run_id": current["run"].get("run_id"),
        "compare_metrics": metrics,
        "warnings": warnings,
        "notes": notes,
        "aggregate": aggregate,
        "answer_changes": answer_changes,
        "regressed": regressed,
        "improved": improved,
        "unchanged": unchanged,
        "added": added,
        "removed": removed,
    }


def recall_drop(diff: Mapping[str, Any]) -> float:
    """How far the average recall fell at the compared cutoff; 0 if it held or rose."""
    name = diff["compare_metrics"][0]
    return max(0.0, -diff["aggregate"][name]["delta"])


def recall_gate_failure(diff: Mapping[str, Any], max_drop: float) -> str | None:
    """Why the recall gate fails, or None when it passes.

    The gate fails when the runs are not like for like, because a score that
    held up between two different setups says nothing about the search.
    """
    if diff["warnings"]:
        return "the runs are not comparable, so recall cannot be checked: " + " ".join(
            diff["warnings"]
        )
    drop = recall_drop(diff)
    if drop > max_drop:
        return (
            f"average {diff['compare_metrics'][0]} fell by {drop:.3f}, "
            f"more than the allowed {max_drop:.3f}"
        )
    return None


def promotion_decision(
    baseline: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    min_gain: float = 0.0,
) -> tuple[bool, str]:
    """Whether ``current`` should replace ``baseline`` as the reference.

    Yes when there is no baseline yet, or when average recall at the compared
    cutoff rose by more than ``min_gain``. A pair that is not like for like
    (different corpus, questions, cutoffs or stack settings) is never promoted,
    because the gain would not mean the search got better. A run that did not
    record the stack settings is never promoted either, since later runs could
    not tell whether they match it.
    """
    if not current.get("settings"):
        return False, "this run did not record the stack settings, so it cannot be a baseline"
    if baseline is None:
        return True, "no baseline yet"
    if not baseline.get("settings"):
        return (
            False,
            "the baseline did not record the stack settings, so the runs cannot be compared",
        )
    diff = diff_results(baseline, current)
    if diff["warnings"]:
        return False, "the runs are not comparable: " + " ".join(diff["warnings"])
    name = diff["compare_metrics"][0]
    gain = diff["aggregate"][name]["delta"]
    if gain > min_gain:
        return True, f"average {name} rose by {gain:.3f}"
    return False, f"average {name} changed by {gain:+.3f}, which is not above {min_gain:.3f}"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _label(metric: str) -> str:
    if metric in ("mrr", "reciprocal_rank"):
        return "MRR" if metric == "mrr" else "Reciprocal rank"
    if metric in ("passage_mrr", "passage_rr"):
        return "Passage MRR" if metric == "passage_mrr" else "Passage reciprocal rank"
    answer_labels = {
        "answer_cited": "Cites expected file",
        "answer_has_phrase": "Contains answer phrase",
        "answer_correct": "Answer correctness",
        "answer_grounded": "Answer groundedness",
    }
    if metric in answer_labels:
        return answer_labels[metric]
    return metric.replace("ndcg", "nDCG").replace("passage_hit", "passage hit")


def _passage(query: Mapping[str, Any]) -> str:
    """Where the answer chunk ranked, for a question with an expected_text."""
    if "passage_rank" not in query:
        return "n/a"
    rank = query["passage_rank"]
    return "not returned" if rank is None else f"#{rank}"


def _ranks(ranks: Mapping[str, int | None], snippet_missing: Sequence[str] = ()) -> str:
    if not ranks:
        return "n/a"
    parts = []
    for name, rank in ranks.items():
        position = "not returned" if rank is None else f"#{rank}"
        note = " (snippet not found)" if name in snippet_missing else ""
        parts.append(f"{name}: {position}{note}")
    return ", ".join(parts)


def _changed_table(entries: Sequence[Mapping[str, Any]], metrics: Sequence[str]) -> list[str]:
    lines = [
        "| ID | Query | "
        + " | ".join(_label(m) for m in metrics)
        + " | Expected file ranks | Answer chunk rank |",
        "|---|---|" + "---|" * len(metrics) + "---|---|",
    ]
    for entry in entries:
        cells = []
        for name in metrics:
            delta = entry["metrics"].get(name)
            cells.append(
                f"{delta['baseline']:.3f} → {delta['current']:.3f}" if delta is not None else "n/a"
            )
        ranks = entry["expected_ranks"]
        missing = entry.get("snippet_missing", {})
        before = _ranks(ranks["baseline"], missing.get("baseline", ()))
        after = _ranks(ranks["current"], missing.get("current", ()))
        passage = entry.get("passage", {})
        lines.append(
            f"| {_cell(entry['id'])} | {_cell(entry['query'])} | "
            + " | ".join(cells)
            + f" | {_cell(before)} → {_cell(after)} "
            + f"| {passage.get('baseline', 'n/a')} → {passage.get('current', 'n/a')} |"
        )
    return lines


def render_diff(diff: Mapping[str, Any]) -> str:
    """Markdown section comparing a run with its baseline, regressions first."""
    metrics = diff["compare_metrics"]
    regressed, improved = diff["regressed"], diff["improved"]
    lines = [
        "## Compared with baseline",
        "",
        f"Baseline run `{diff['baseline_run_id']}`, current run `{diff['current_run_id']}`. "
        f"{len(regressed)} regressed, {len(improved)} improved, "
        f"{diff['unchanged']} unchanged, {len(diff['added'])} added, "
        f"{len(diff['removed'])} removed.",
        "",
    ]
    for warning in diff["warnings"]:
        lines.append(f"> **Warning:** {warning}")
    for note in diff.get("notes", ()):
        lines.append(f"> **Note:** {note}")
    if diff["warnings"] or diff.get("notes"):
        lines.append("")

    lines += [f"### Regressed ({len(regressed)})", ""]
    lines += _changed_table(regressed, metrics) if regressed else ["No question regressed."]
    lines += ["", f"### Improved ({len(improved)})", ""]
    lines += _changed_table(improved, metrics) if improved else ["No question improved."]

    if diff.get("answer_changes"):
        lines += [
            "",
            "### Answer correctness changes (0–2)",
            "",
            "| ID | Question | Baseline | Current |",
            "|---|---|---|---|",
        ]
        for entry in sorted(diff["answer_changes"], key=lambda item: item["delta"]):
            lines.append(
                f"| {_cell(entry['id'])} | {_cell(entry['query'])} | {entry['baseline']} | {entry['current']} |"
            )

    if diff["aggregate"]:
        lines += [
            "",
            "### Aggregate change",
            "",
            "| Metric | Baseline | Current | Change |",
            "|---|---|---|---|",
        ]
        for name, delta in diff["aggregate"].items():
            lines.append(
                f"| {_label(name)} | {delta['baseline']:.3f} | {delta['current']:.3f} "
                f"| {delta['delta']:+.3f} |"
            )
    for heading, ids in (
        ("Added questions", diff["added"]),
        ("Removed questions", diff["removed"]),
    ):
        if ids:
            lines += ["", f"### {heading} ({len(ids)})", ""]
            lines += [f"- {_cell(query_id)}" for query_id in ids]
    return "\n".join(lines) + "\n"


def _settings_line(results: Mapping[str, Any]) -> str:
    settings = results.get("settings")
    if not settings:
        return f"not recorded ({results.get('settings_note') or 'unavailable'})"
    return (
        f"embedding {settings.get('embedding_provider')}/{settings.get('embedding_model')}, "
        f"chunk size {settings.get('chunk_size')}, overlap {settings.get('chunk_overlap')}"
    )


def _scores_line(results: Mapping[str, Any]) -> list[str]:
    values = [pair[1] for q in results["queries"] for pair in q.get("chunk_scores") or ()]
    if not values:
        return []
    return [
        f"- **Chunk scores:** {len(values)} recorded, from {min(values):.4f} to "
        f"{max(values):.4f}; `run_eval.py scores` tests thresholds on them"
    ]


def render_summary(results: Mapping[str, Any], diff: Mapping[str, Any] | None = None) -> str:
    """Markdown summary of one run, followed by the baseline comparison if given."""
    run = results["run"]
    k = run["primary_k"]
    overall = results["metrics"].get("overall", {})
    by_tag = results["metrics"].get("by_tag", {})
    headline = [f"recall@{k}", "mrr", f"ndcg@{k}"]

    lines = [
        "# OpenRAG retrieval evaluation",
        "",
        f"- **Run:** `{run['run_id']}` at {run['timestamp']}",
        f"- **Target:** {run['target_url']}",
        f"- **Commit:** {run.get('git_commit') or 'unknown'}",
        f"- **SDK version:** {run.get('sdk_version') or 'unknown'}",
        f"- **Dataset:** {run['corpus_files']} documents (corpus `{_short(run['corpus_hash'])}`), "
        f"{run['query_count']} questions (`{_short(run['queries_hash'])}`)",
        f"- **Search:** fetch limit {run['fetch_limit']}, score threshold {run['score_threshold']}",
        f"- **Settings:** {_settings_line(results)}",
        *([f"- **Label:** {_cell(run['label'])}"] if run.get("label") else []),
        *_scores_line(results),
        "",
        "## Overall",
        "",
        "| Metric | Score |",
        "|---|---|",
    ]
    lines += [
        f"| {_label(name)} | {value:.3f} |"
        for name, value in overall.items()
        if not name.startswith("answer_")
    ]
    if "passage_mrr" in overall:
        lines += [
            "",
            f"Passage scores cover the {run.get('passage_questions', 'n/a')} of "
            f"{run['query_count']} questions that have an expected_text. They rank the "
            "first chunk holding that text among all chunks returned.",
        ]

    if by_tag:
        if f"passage_hit@{k}" in overall:
            headline += [f"passage_hit@{k}", "passage_mrr"]
        lines += [
            "",
            "## By tag",
            "",
            "| Tag | Questions | " + " | ".join(_label(m) for m in headline) + " |",
            "|---|---|" + "---|" * len(headline),
        ]
        for tag, scores in by_tag.items():
            lines.append(
                f"| {_cell(tag)} | {scores['count']} | "
                # A tag whose questions all lack an expected_text has no passage scores.
                + " | ".join(f"{scores[m]:.3f}" if m in scores else "n/a" for m in headline)
                + " |"
            )

    missed = [q for q in results["queries"] if q["metrics"][f"recall@{k}"] < 1 - EPSILON]
    lines += ["", f"## Questions below full recall@{k} ({len(missed)})", ""]
    if missed:
        lines += [
            f"| ID | Query | recall@{k} | Expected file ranks | Snippet found "
            "| Answer chunk rank | Top files returned |",
            "|---|---|---|---|---|---|---|",
        ]
        for q in missed:
            snippet = {True: "yes", False: "no", None: "n/a"}[q.get("snippet_found")]
            top = ", ".join(item["filename"] for item in q["ranked_files"][:3]) or "none"
            lines.append(
                f"| {_cell(q['id'])} | {_cell(q['query'])} | {q['metrics'][f'recall@{k}']:.3f} "
                f"| {_cell(_ranks(q['expected_ranks'], _snippet_missing(q)))} | {snippet} "
                f"| {_passage(q)} | {_cell(top)} |"
            )
    else:
        lines.append(f"Every question reached full recall@{k}.")

    answer_rows = [q for q in results["queries"] if "answer" in q]
    if answer_rows:
        answer_names = [name for name in overall if name.startswith("answer_")]
        errors = [q for q in answer_rows if q["answer"].get("judge_error")]
        parse_errors = sum("could not be parsed" in q["answer"]["judge_error"] for q in errors)
        judged = sum(q["answer"].get("judgement") is not None for q in answer_rows)
        chat_failed = [q for q in answer_rows if q["answer"].get("chat_error")]
        lines += [
            "",
            "## Answer quality",
            "",
            f"{len(answer_rows) - len(chat_failed)} answers; {len(chat_failed)} chat errors; "
            f"{judged} usable judgements; {len(errors)} judge errors "
            f"({parse_errors} failed to parse). Questions without an answer or judgement "
            "are excluded from the averages.",
            "",
            "| Metric | Score |",
            "|---|---|",
        ]
        lines += [f"| {_label(name)} | {overall[name]:.3f} |" for name in answer_names]
        if by_tag:
            lines += [
                "",
                "### Answer quality by tag",
                "",
                "| Tag | " + " | ".join(_label(m) for m in answer_names) + " |",
                "|---|" + "---|" * len(answer_names),
            ]
            for tag, scores in by_tag.items():
                lines.append(
                    f"| {_cell(tag)} | "
                    + " | ".join(f"{scores[m]:.3f}" if m in scores else "n/a" for m in answer_names)
                    + " |"
                )
        wrong = [
            q for q in answer_rows if (q["answer"].get("judgement") or {}).get("correctness") == 0
        ]
        lines += ["", f"### Answers judged wrong ({len(wrong)})", ""]
        if wrong:
            lines += ["| Question | Reference | Answer excerpt | Reason |", "|---|---|---|---|"]
            for q in wrong:
                answer = q["answer"]
                lines.append(
                    "| "
                    + " | ".join(
                        _cell(v)
                        for v in (
                            q["query"],
                            q.get("expected_answer") or "n/a",
                            answer["text"][:240],
                            answer["judgement"]["reason"],
                        )
                    )
                    + " |"
                )
        else:
            lines.append("No answers judged wrong.")
        if chat_failed:
            lines += [
                "",
                f"### Chat errors ({len(chat_failed)})",
                "",
                "| ID | Error |",
                "|---|---|",
            ]
            lines += [
                f"| {_cell(q['id'])} | {_cell(q['answer']['chat_error'])} |" for q in chat_failed
            ]

    text = "\n".join(lines) + "\n"
    if diff is not None:
        text += "\n" + render_diff(diff)
    return text
