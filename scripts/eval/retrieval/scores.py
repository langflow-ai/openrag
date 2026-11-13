"""Tune relevance-score thresholds offline from one retrieval eval run.

A run records the score of every chunk search returned, in rank order, and
which of those chunks hold the answer. The labels the harness already has then
say what any score cutoff would remove:

- a chunk from an expected file is relevant;
- a relevant chunk that contains the question's ``expected_text`` is an answer
  chunk;
- a chunk from any other file is noise.

So a single run with no threshold scores every possible threshold, without
another run. ``sweep`` cuts at each threshold and re-scores, ``recommend`` picks
the highest threshold that keeps recall, and ``tiers`` checks whether the
High, Medium and Low relevance labels match what the chunks really are.

Standard library only, so it can be unit-tested without the SDK or a stack.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any

# run_eval.py imports this module as a top-level script module, and the tests
# import it from the scripts.eval.retrieval package. A plain "import metrics"
# works only in the first case and "from . import metrics" only in the second.
metrics = importlib.import_module(f"{__package__}.metrics" if __package__ else "metrics")

NORMALIZE_METHODS = ("none", "minmax")
DEFAULT_TIERS = (0.65, 0.35)
DEFAULT_HIDE = 0.1
EPSILON = 1e-9


class ScoresError(ValueError):
    """A results file cannot be used for threshold tuning."""


@dataclass(frozen=True)
class Question:
    """One question's returned chunks, as recorded by a run."""

    id: str
    query: str
    expected_files: frozenset[str]
    files: tuple[str, ...]  # canonical filename of each file rank, rank 1 first
    chunks: tuple[tuple[int, float], ...]  # (file rank, score) of each chunk, in rank order
    answer_positions: frozenset[int] | None  # 1-based chunk positions; None without expected_text

    def file_of(self, position: int) -> str:
        return self.files[self.chunks[position - 1][0] - 1]


def load_questions(results: Mapping[str, Any]) -> list[Question]:
    """Read every question's chunk scores from a results dict."""
    questions: list[Question] = []
    for record in results["queries"]:
        if "chunk_scores" not in record:
            raise ScoresError(
                "this results file has no chunk scores; rerun the eval with this version "
                "of the harness to record them"
            )
        files = tuple(item["filename"] for item in record["ranked_files"])
        chunks = tuple((int(rank), float(score)) for rank, score in record["chunk_scores"])
        has_text = record.get("expected_text") is not None
        questions.append(
            Question(
                id=record["id"],
                query=record["query"],
                expected_files=frozenset(record["expected_files"]),
                files=files,
                chunks=chunks,
                answer_positions=frozenset(record.get("answer_chunks") or ()) if has_text else None,
            )
        )
    return questions


def normalize(questions: Sequence[Question], method: str) -> list[Question]:
    """Rescale each question's chunk scores.

    ``none`` keeps the scores search returned; use it when the backend already
    normalizes them. ``minmax`` maps each question's scores to [0, 1] with
    (score - min) / (max - min), and to 1.0 when they are all equal. That is the
    normalization the hybrid search pipeline uses, applied here to the combined
    score rather than to each sub-query, so it only approximates the pipeline.
    """
    if method == "none":
        return list(questions)
    if method != "minmax":
        raise ValueError(f"unknown normalization {method!r}; use one of {NORMALIZE_METHODS}")
    rescaled: list[Question] = []
    for question in questions:
        scores = [score for _, score in question.chunks]
        if not scores:
            rescaled.append(question)
            continue
        low, high = min(scores), max(scores)
        span = high - low
        chunks = tuple(
            (rank, (score - low) / span if span > 0 else 1.0) for rank, score in question.chunks
        )
        rescaled.append(replace(question, chunks=chunks))
    return rescaled


def finite(text: str) -> float:
    """``text`` as a float, refusing nan and infinity, which would make every comparison wrong."""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text.strip()!r} is not a finite number")
    return value


def _decimal(text: str) -> Decimal:
    finite(text)  # same errors as the other numeric options
    try:
        return Decimal(text.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{text.strip()!r} is not a number") from exc


def parse_thresholds(text: str) -> list[float] | None:
    """``auto`` (None), ``start:stop:step``, or a comma-separated list of thresholds.

    Thresholds keep the precision they were given: rounding one would move the
    cut and could keep a chunk the requested threshold drops. A range is built
    in decimal arithmetic from the text, so ``0:0.3:0.1`` gives exactly 0.0,
    0.1, 0.2 and 0.3, and it never goes past ``stop``: with a step that does not
    divide the range evenly, it ends at the last step below ``stop``.
    """
    text = text.strip()
    if text == "auto":
        return None
    if ":" in text:
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError(f"expected start:stop:step, got {text!r}")
        start, stop, step = (_decimal(part) for part in parts)
        if step <= 0 or stop < start:
            raise ValueError("the step must be positive and stop must not be below start")
        count = int((stop - start) // step) + 1
        return [float(start + i * step) for i in range(count)]
    values = sorted({finite(part) for part in text.split(",") if part.strip()})
    if not values:
        raise ValueError("no thresholds given")
    return values


def auto_thresholds(questions: Sequence[Question]) -> list[float]:
    """Steps of 0.05 for scores in [0, 1]; otherwise 20 even steps across the scores seen."""
    scores = [score for question in questions for _, score in question.chunks]
    if not scores:
        return [0.0]
    low, high = min(scores), max(scores)
    if low >= 0 and high <= 1:
        return [round(i * 0.05, 2) for i in range(21)]
    step = (high - low) / 20
    # Rounded for a readable table, except the first: rounding the lowest score
    # up would cut the chunk that has it, and that row should cut nothing.
    return [low] + [float(f"{low + i * step:.4g}") for i in range(1, 21)]


@dataclass(frozen=True)
class QuestionCut:
    """One question re-scored after dropping chunks below a threshold."""

    recall: float
    reciprocal_rank: float
    passage_hit: float | None  # None without expected_text
    answer_kept: bool | None  # None without expected_text
    chunks_kept: int
    noise_kept: int
    relevant_kept: int


def cut(question: Question, threshold: float | None, k: int) -> QuestionCut:
    """Re-score one question keeping only chunks scoring at least ``threshold``.

    ``None`` keeps every chunk. Ranks are recounted among the kept chunks, the
    same way search would return them if it applied the threshold.
    """
    kept = [
        (position, rank)
        for position, (rank, score) in enumerate(question.chunks, start=1)
        if threshold is None or score >= threshold
    ]
    order: list[str] = []
    snippet: dict[str, bool] = {}
    passage: int | None = None
    noise = relevant = 0
    for new_position, (position, rank) in enumerate(kept, start=1):
        name = question.files[rank - 1]
        if name not in snippet:
            order.append(name)
            snippet[name] = False
        if name in question.expected_files:
            relevant += 1
        else:
            noise += 1
        if question.answer_positions is not None and position in question.answer_positions:
            snippet[name] = True
            if passage is None:
                passage = new_position
    has_text = question.answer_positions is not None
    ranked = [
        metrics.RankedFile(
            filename=name,
            rank=file_rank,
            score=0.0,
            snippet_found=snippet[name] if has_text else None,
        )
        for file_rank, name in enumerate(order, start=1)
    ]
    scores = metrics.score_query(ranked, question.expected_files, [k])
    return QuestionCut(
        recall=scores[f"recall@{k}"],
        reciprocal_rank=scores["reciprocal_rank"],
        passage_hit=metrics.score_passage(passage, [k])[f"passage_hit@{k}"] if has_text else None,
        answer_kept=passage is not None if has_text else None,
        chunks_kept=len(kept),
        noise_kept=noise,
        relevant_kept=relevant,
    )


@dataclass(frozen=True)
class SweepRow:
    """Scores at one threshold; ``threshold`` None means no cut."""

    threshold: float | None
    recall: float
    mrr: float
    passage_hit: float | None
    recall_loss: float  # mean recall@k lost against no cut; negative when it rose
    questions_lost: tuple[str, ...]  # ids whose recall@k fell
    answers_lost: tuple[str, ...]  # ids of questions whose every answer chunk was cut
    noise_removed: float  # share of the noise chunks cut
    relevant_removed: float  # share of the relevant chunks cut
    chunks_kept: float  # mean chunks kept per question


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _row(
    questions: Sequence[Question],
    threshold: float | None,
    k: int,
    reference: Sequence[QuestionCut] | None,
) -> tuple[SweepRow, list[QuestionCut]]:
    cuts = [cut(question, threshold, k) for question in questions]
    base = reference if reference is not None else cuts
    noise_total = sum(item.noise_kept for item in base)
    relevant_total = sum(item.relevant_kept for item in base)
    passage = [item.passage_hit for item in cuts if item.passage_hit is not None]
    row = SweepRow(
        threshold=threshold,
        recall=_mean([item.recall for item in cuts]),
        mrr=_mean([item.reciprocal_rank for item in cuts]),
        passage_hit=_mean(passage) if passage else None,
        recall_loss=_mean([b.recall - c.recall for b, c in zip(base, cuts, strict=True)]),
        questions_lost=tuple(
            q.id
            for q, b, c in zip(questions, base, cuts, strict=True)
            if c.recall < b.recall - EPSILON
        ),
        answers_lost=tuple(
            q.id
            for q, b, c in zip(questions, base, cuts, strict=True)
            if b.answer_kept and not c.answer_kept
        ),
        noise_removed=1 - sum(item.noise_kept for item in cuts) / noise_total
        if noise_total
        else 0.0,
        relevant_removed=(
            1 - sum(item.relevant_kept for item in cuts) / relevant_total if relevant_total else 0.0
        ),
        chunks_kept=_mean([float(item.chunks_kept) for item in cuts]),
    )
    return row, cuts


def sweep(questions: Sequence[Question], thresholds: Sequence[float], k: int) -> list[SweepRow]:
    """Score every threshold against no cut. The first row is the no-cut reference."""
    reference, cuts = _row(questions, None, k, None)
    rows = [reference]
    for threshold in sorted(set(thresholds)):
        rows.append(_row(questions, threshold, k, cuts)[0])
    return rows


@dataclass(frozen=True)
class Recommendation:
    keeps_recall: SweepRow | None  # highest threshold with recall loss within the limit
    one_answer: SweepRow | None  # highest threshold where at most one question loses its answer


def recommend(rows: Sequence[SweepRow], max_recall_loss: float = 0.0) -> Recommendation:
    """The highest thresholds that stay within each limit.

    A threshold qualifies only if it and every lower threshold stay within the
    limit, so a recall that recovers at a high cutoff by chance is not picked.
    """

    def highest(ok: Any) -> SweepRow | None:
        best: SweepRow | None = None
        for row in rows:
            if row.threshold is None:
                continue
            if not ok(row):
                break
            best = row
        return best

    return Recommendation(
        keeps_recall=highest(lambda row: row.recall_loss <= max_recall_loss + EPSILON),
        one_answer=highest(lambda row: len(row.answers_lost) <= 1),
    )


SIMULATION_NOTE = (
    "These thresholds are simulated on the score /v1/search returned. A stack can apply "
    "score_threshold to a different score: since #2520, main cuts the hybrid score before "
    "document-level security adds its own score to every hit. A simulated threshold is "
    "then not the same cut as score_threshold set to that value. Rerun with "
    "`run_eval.py run --live-thresholds ...` to measure the cut the stack really makes."
)


def live_rows(results: Mapping[str, Any], k: int) -> list[SweepRow] | None:
    """Scores at each threshold the stack applied itself, or None if none was measured.

    ``run --live-thresholds`` reran every question with the stack applying each
    threshold. Losses are counted against the run's main pass, as in the
    simulated sweep.
    """
    records = results["queries"]
    measured = [record for record in records if "live_cuts" in record]
    if not measured:
        return None
    if len(measured) != len(records):
        raise ScoresError("only some questions have live cuts; rerun with --live-thresholds")
    key, passage_key = f"recall@{k}", f"passage_hit@{k}"
    if any(key not in record["metrics"] for record in records):
        raise ScoresError(
            f"the run did not score recall@{k}, so its live cuts cannot be read at k={k}"
        )
    noise_total = relevant_total = 0
    for record in records:
        files = [item["filename"] for item in record["ranked_files"]]
        for rank, _ in record.get("chunk_scores") or ():
            if files[int(rank) - 1] in record["expected_files"]:
                relevant_total += 1
            else:
                noise_total += 1
    rows: list[SweepRow] = []
    for index, cut_at in enumerate(records[0]["live_cuts"]):
        cuts = [record["live_cuts"][index] for record in records]
        base = [record["metrics"][key] for record in records]
        now = [item["metrics"][key] for item in cuts]
        passage = [item["metrics"][passage_key] for item in cuts if passage_key in item["metrics"]]
        rows.append(
            SweepRow(
                threshold=float(cut_at["threshold"]),
                recall=_mean(now),
                mrr=_mean([item["metrics"]["reciprocal_rank"] for item in cuts]),
                passage_hit=_mean(passage) if passage else None,
                recall_loss=_mean([b - c for b, c in zip(base, now, strict=True)]),
                questions_lost=tuple(
                    record["id"]
                    for record, b, c in zip(records, base, now, strict=True)
                    if c < b - EPSILON
                ),
                answers_lost=tuple(
                    record["id"]
                    for record, item in zip(records, cuts, strict=True)
                    if record.get("passage_rank") is not None and item["answer_kept"] is False
                ),
                noise_removed=(
                    1 - sum(item["noise"] for item in cuts) / noise_total if noise_total else 0.0
                ),
                relevant_removed=(
                    1 - sum(item["relevant"] for item in cuts) / relevant_total
                    if relevant_total
                    else 0.0
                ),
                chunks_kept=_mean([float(item["chunks"]) for item in cuts]),
            )
        )
    return rows


def differing_questions(
    results: Mapping[str, Any],
    questions: Sequence[Question],
    index: int,
    threshold: float,
    k: int,
) -> list[str]:
    """Questions whose live cut at ``live_cuts[index]`` differs from the simulation.

    Each question is compared on its own: recall@k, reciprocal rank, whether an
    answer chunk survived, and how many relevant and noise chunks were kept.
    Totals can agree while two questions trade places, so they are not enough.
    Chunk identities are not recorded, so two different chunks of the same kind
    still count as the same.
    """
    key = f"recall@{k}"
    differing: list[str] = []
    for record, question in zip(results["queries"], questions, strict=True):
        live = record["live_cuts"][index]
        simulated = cut(question, threshold, k)
        same = (
            abs(live["metrics"][key] - simulated.recall) <= EPSILON
            and abs(live["metrics"]["reciprocal_rank"] - simulated.reciprocal_rank) <= EPSILON
            and live["answer_kept"] == simulated.answer_kept
            and live["relevant"] == simulated.relevant_kept
            and live["noise"] == simulated.noise_kept
        )
        if not same:
            differing.append(record["id"])
    return differing


TIER_NAMES = ("High", "Medium", "Low")


def tier_of(score: float, high: float, med: float) -> str:
    if score >= high:
        return "High"
    return "Medium" if score >= med else "Low"


def tiers(
    questions: Sequence[Question],
    high: float = DEFAULT_TIERS[0],
    med: float = DEFAULT_TIERS[1],
    hide: float = DEFAULT_HIDE,
) -> dict[str, Any]:
    """How the relevance tiers split answer, relevant and noise chunks, and files.

    A file's tier comes from its best chunk. ``hide`` is the score below which
    results are hidden; the counts say how many answer chunks and expected files
    that would hide.
    """
    chunk_counts = {name: {"answer": 0, "relevant": 0, "noise": 0} for name in TIER_NAMES}
    file_counts = {name: {"expected": 0, "other": 0} for name in TIER_NAMES}
    hidden_answers = hidden_expected = answer_total = 0
    for question in questions:
        best: dict[str, float] = {}
        for position, (_, score) in enumerate(question.chunks, start=1):
            name = question.file_of(position)
            best[name] = max(score, best.get(name, score))
            if question.answer_positions is not None and position in question.answer_positions:
                kind = "answer"
                answer_total += 1
                hidden_answers += score < hide
            elif name in question.expected_files:
                kind = "relevant"
            else:
                kind = "noise"
            chunk_counts[tier_of(score, high, med)][kind] += 1
        for name, score in best.items():
            expected = name in question.expected_files
            file_counts[tier_of(score, high, med)]["expected" if expected else "other"] += 1
            hidden_expected += expected and score < hide
    high_chunks = sum(chunk_counts["High"].values())
    return {
        "high": high,
        "med": med,
        "hide": hide,
        "chunks": chunk_counts,
        "files": file_counts,
        "high_precision": (
            (chunk_counts["High"]["answer"] + chunk_counts["High"]["relevant"]) / high_chunks
            if high_chunks
            else None
        ),
        "expected_files_low": file_counts["Low"]["expected"],
        "other_files_high": file_counts["High"]["other"],
        "answer_chunks": answer_total,
        "hidden_answers": hidden_answers,
        "hidden_expected_files": hidden_expected,
    }


def analyze(
    results: Mapping[str, Any],
    *,
    method: str = "none",
    k: int | None = None,
    thresholds: Sequence[float] | None = None,
    tier_cutoffs: tuple[float, float] = DEFAULT_TIERS,
    hide: float = DEFAULT_HIDE,
    max_recall_loss: float = 0.0,
    candidate: float | None = None,
) -> dict[str, Any]:
    """Everything the ``scores`` report shows for one results dict."""
    run = results["run"]
    k = k or int(run["primary_k"])
    questions = normalize(load_questions(results), method)
    notes: list[str] = []
    wanted = list(thresholds) if thresholds is not None else auto_thresholds(questions)
    floor = float(run.get("score_threshold") or 0.0)
    if method == "none" and floor > 0:
        # Search never returned chunks below the run's own threshold, so cutting
        # lower would change nothing and would wrongly look free.
        below = [value for value in wanted if value < floor]
        wanted = [value for value in wanted if value >= floor]
        notes.append(
            f"The run used a score threshold of {_value(floor)}, so chunks below it were never "
            "returned and the sweep starts there."
            + (f" Left out: {', '.join(f'{_value(value)}' for value in below)}." if below else "")
        )
    if method == "minmax" and floor > 0:
        notes.append(
            f"The run used a score threshold of {_value(floor)} before normalizing, so the "
            "normalized scores cover only the chunks above it."
        )
    all_scores = [score for question in questions for _, score in question.chunks]
    if all_scores and (min(all_scores) < 0 or max(all_scores) > 1):
        notes.append(
            f"Scores run from {min(all_scores):.4g} to {max(all_scores):.4g}, outside [0, 1], "
            "so the tier cutoffs and hide threshold below do not mean anything for them. "
            "Use --normalize minmax to preview the tiers, or run against a stack that "
            "normalizes scores."
        )
    rows = sweep(questions, wanted, k)
    advice = recommend(rows, max_recall_loss)
    live = live_rows(results, k)
    simulated_at_live: list[SweepRow] = []
    live_differences: list[list[str]] = []
    live_advice: Recommendation | None = None
    if live is None:
        notes.append(SIMULATION_NOTE)
    else:
        # Live thresholds are on the scale search returns, so compare them with
        # a simulation on the unnormalized scores.
        raw = load_questions(results)
        # One simulated row per live row, duplicates included, so the two lists
        # always line up.
        _, reference_cuts = _row(raw, None, k, None)
        simulated_at_live = [_row(raw, row.threshold, k, reference_cuts)[0] for row in live]
        live_advice = recommend(live, max_recall_loss)
        live_differences = [
            differing_questions(results, raw, index, row.threshold or 0.0, k)
            for index, row in enumerate(live)
        ]
        differ = [(row, ids) for row, ids in zip(live, live_differences, strict=True) if ids]
        if differ:
            row, ids = differ[0]
            examples = ", ".join(ids[:3]) + (", …" if len(ids) > 3 else "")
            notes.append(
                f"At {len(differ)} of {len(live)} live thresholds the stack's cut differs from "
                f"the simulation for some questions (at {_value(row.threshold)}: {len(ids)} of "
                f"{len(raw)}, such as {examples}). The stack applies its threshold to a "
                "different score than search returns, so use the live thresholds, not the "
                "simulated ones."
            )
        else:
            notes.append(
                f"The stack's own cut matched the simulation at all {len(live)} live thresholds."
            )
    # The threshold whose lost questions the report lists: the one asked for,
    # otherwise the highest that keeps recall.
    if candidate is not None and method == "none" and 0 < floor and candidate < floor:
        raise ScoresError(
            f"--candidate {_value(candidate)} is below the run's score threshold {_value(floor)}, so "
            f"chunks below {_value(floor)} were never returned and its cost cannot be measured"
        )
    chosen = candidate
    if chosen is None and advice.keeps_recall is not None:
        chosen = advice.keeps_recall.threshold
    candidate_row: SweepRow | None = None
    if chosen is not None:
        candidate_row = next((row for row in rows if row.threshold == chosen), None)
        if candidate_row is None:
            candidate_row = sweep(questions, [chosen], k)[1]
    return {
        "run_id": run.get("run_id"),
        "label": run.get("label"),
        "method": method,
        "k": k,
        "max_recall_loss": max_recall_loss,
        "chunk_count": len(all_scores),
        "score_range": (min(all_scores), max(all_scores)) if all_scores else None,
        "notes": notes,
        "rows": rows,
        "recommendation": advice,
        "candidate": candidate_row,
        "live": live,
        "simulated_at_live": simulated_at_live,
        "live_recommendation": live_advice,
        "live_differences": live_differences,
        "lost": _lost_details(questions, chosen, k) if chosen is not None else [],
        "tiers": tiers(questions, tier_cutoffs[0], tier_cutoffs[1], hide),
    }


def _lost_details(
    questions: Sequence[Question], threshold: float | None, k: int
) -> list[dict[str, Any]]:
    """The questions a threshold costs recall on, with the scores that explain why."""
    lost: list[dict[str, Any]] = []
    for question in questions:
        before, after = cut(question, None, k), cut(question, threshold, k)
        if after.recall >= before.recall - EPSILON:
            continue
        expected_best = [
            score
            for position, (_, score) in enumerate(question.chunks, start=1)
            if question.file_of(position) in question.expected_files
        ]
        answer_best = [
            score
            for position, (_, score) in enumerate(question.chunks, start=1)
            if question.answer_positions is not None and position in question.answer_positions
        ]
        lost.append(
            {
                "id": question.id,
                "query": question.query,
                "recall": (before.recall, after.recall),
                "best_expected": max(expected_best) if expected_best else None,
                "best_answer": max(answer_best) if answer_best else None,
            }
        )
    return lost


# --- rendering ---------------------------------------------------------------


def _num(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _value(value: float) -> str:
    """A threshold or cutoff for display, with enough digits to show what was asked for."""
    return f"{value:.12g}"


def _threshold(row: SweepRow | None) -> str:
    if row is None:
        return "none"
    return "no cut" if row.threshold is None else _value(row.threshold)


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_report(analysis: Mapping[str, Any]) -> str:
    """Markdown report for one run: sweep, recommendation, tiers and lost questions."""
    k = analysis["k"]
    advice: Recommendation = analysis["recommendation"]
    label = f" ({_cell(analysis['label'])})" if analysis.get("label") else ""
    low_high = analysis["score_range"]
    lines = [
        f"# Relevance thresholds for run `{analysis['run_id']}`{label}",
        "",
        f"- **Scores:** {analysis['chunk_count']} chunks, "
        + (f"from {low_high[0]:.4f} to {low_high[1]:.4f}" if low_high else "none returned")
        + f", normalization `{analysis['method']}`",
        f"- **Simulated, keeps recall@{k}:** {_threshold(advice.keeps_recall)}"
        + (
            f" (allowed loss {analysis['max_recall_loss']:g})"
            if analysis["max_recall_loss"]
            else ""
        ),
        f"- **Simulated, at most one question loses its answer:** {_threshold(advice.one_answer)}",
    ]
    live_advice: Recommendation | None = analysis.get("live_recommendation")
    if live_advice is not None:
        lines += [
            f"- **Live, keeps recall@{k}:** {_threshold(live_advice.keeps_recall)}",
            f"- **Live, at most one question loses its answer:** "
            f"{_threshold(live_advice.one_answer)}",
        ]
    lines.append("")
    for note in analysis["notes"]:
        lines.append(f"> **Note:** {note}")
    if analysis["notes"]:
        lines.append("")

    def mark(row: SweepRow) -> str:
        tags = []
        if row is advice.keeps_recall:
            tags.append("keeps recall")
        if row is advice.one_answer:
            tags.append("≤ 1 question loses its answer")
        return ", ".join(tags)

    lines += [
        "## Simulated sweep",
        "",
        "Each row drops every chunk whose returned score is below the threshold and scores "
        "what is left. Losses are counted against no cut.",
        "",
        f"| Threshold | recall@{k} | MRR | passage hit@{k} | Questions lost "
        "| Questions that lost their answer "
        "| Noise removed | Relevant removed | Chunks kept | |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in analysis["rows"]:
        lines.append(
            f"| {_threshold(row)} | {row.recall:.3f} | {row.mrr:.3f} | {_num(row.passage_hit)} "
            f"| {len(row.questions_lost)} | {len(row.answers_lost)} | {_pct(row.noise_removed)} "
            f"| {_pct(row.relevant_removed)} | {row.chunks_kept:.1f} | {mark(row)} |"
        )

    if analysis.get("live"):
        lines += _render_live(analysis, k)

    lines += _render_tiers(analysis["tiers"])

    candidate: SweepRow | None = analysis["candidate"]
    if candidate is not None:
        lost = analysis["lost"]
        lines += [
            "",
            f"## Questions a simulated threshold of {_threshold(candidate)} would cost "
            f"({len(lost)})",
            "",
        ]
        if lost:
            lines += [
                f"| ID | Query | recall@{k} | Best expected-file chunk | Best answer chunk |",
                "|---|---|---|---|---|",
            ]
            for item in lost:
                before, after = item["recall"]
                lines.append(
                    f"| {_cell(item['id'])} | {_cell(item['query'])} | {before:.3f} → {after:.3f} "
                    f"| {_num(item['best_expected'], 4)} | {_num(item['best_answer'], 4)} |"
                )
        else:
            lines.append(f"No question loses recall@{k}.")
    return "\n".join(lines) + "\n"


def _render_live(analysis: Mapping[str, Any], k: int) -> list[str]:
    lines = [
        "",
        "## Live cuts",
        "",
        "Each row reran every question with the stack applying the threshold itself, next to "
        "what the simulation predicts at the same threshold.",
        "",
        f"| Threshold | Live recall@{k} | Simulated recall@{k} "
        "| Live: questions that lost their answer | Simulated: questions that lost their answer "
        "| Live chunks kept | Simulated chunks kept | Questions that differ |",
        "|---|---|---|---|---|---|---|---|",
    ]
    rows = zip(
        analysis["live"], analysis["simulated_at_live"], analysis["live_differences"], strict=True
    )
    for live, sim, ids in rows:
        differ = f"**{len(ids)}**" if ids else "0"
        lines.append(
            f"| {_threshold(live)} | {live.recall:.3f} | {sim.recall:.3f} "
            f"| {len(live.answers_lost)} | {len(sim.answers_lost)} "
            f"| {live.chunks_kept:.1f} | {sim.chunks_kept:.1f} | {differ} |"
        )
    lines += [
        "",
        "A question differs when its live cut and the simulation disagree on recall@k, "
        "reciprocal rank, whether an answer chunk survived, or how many relevant or noise "
        "chunks were kept. Chunk identities are not recorded, so this does not prove the same "
        "chunks were kept. Two searches can also differ by a rank through index noise; rerun "
        "to confirm a small difference.",
    ]
    return lines


def _render_tiers(result: Mapping[str, Any]) -> list[str]:
    chunks, files = result["chunks"], result["files"]
    lines = [
        "",
        f"## Tiers (High ≥ {_value(result['high'])}, Medium ≥ {_value(result['med'])})",
        "",
        "| Tier | Answer chunks | Other relevant chunks | Noise chunks | Expected files | Other files |",
        "|---|---|---|---|---|---|",
    ]
    for name in TIER_NAMES:
        lines.append(
            f"| {name} | {chunks[name]['answer']} | {chunks[name]['relevant']} "
            f"| {chunks[name]['noise']} | {files[name]['expected']} | {files[name]['other']} |"
        )
    lines += [
        "",
        f"- High-tier chunks that are relevant: {_num(result['high_precision'])}",
        f"- Expected files whose best chunk is Low: {result['expected_files_low']}",
        f"- Other files whose best chunk is High: {result['other_files_high']}",
        f"- Hidden below {_value(result['hide'])}: {result['hidden_answers']} of "
        f"{result['answer_chunks']} answer chunks, {result['hidden_expected_files']} expected files",
        "",
        "A file's tier is the tier of its best chunk. Files are counted once per question.",
    ]
    return lines


def render_comparison(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    warnings: Sequence[str] = (),
) -> str:
    """Markdown table comparing two runs' threshold analyses side by side.

    ``warnings`` says why the runs may not be comparable, such as a different
    corpus or question set; each is shown above the table.
    """
    k = current["k"]

    def describe(analysis: Mapping[str, Any]) -> list[str]:
        advice: Recommendation = analysis["recommendation"]
        rows = analysis["rows"]
        candidate: SweepRow | None = analysis["candidate"]
        result = analysis["tiers"]
        return [
            f"`{analysis['run_id']}`",
            _cell(analysis.get("label") or "none"),
            f"{rows[0].recall:.3f}",
            _threshold(advice.keeps_recall),
            _threshold(advice.one_answer),
            (
                _threshold(analysis["live_recommendation"].keeps_recall)
                if analysis.get("live_recommendation")
                else "not measured"
            ),
            _threshold(candidate),
            _pct(candidate.noise_removed) if candidate else "n/a",
            str(len(candidate.answers_lost)) if candidate else "n/a",
            _num(result["high_precision"]),
            str(result["expected_files_low"]),
            str(result["other_files_high"]),
            f"{result['hidden_answers']} of {result['answer_chunks']}",
        ]

    names = [
        "Run",
        "Label",
        f"recall@{k}, no cut",
        "Simulated: keeps recall",
        "Simulated: ≤ 1 question loses its answer",
        "Live: keeps recall",
        "Compared threshold (simulated)",
        "Noise removed there",
        "Questions that lost their answer there",
        "High-tier chunks relevant",
        "Expected files in Low",
        "Other files in High",
        "Answer chunks hidden",
    ]
    lines = ["# Relevance thresholds compared", ""]
    for warning in warnings:
        lines.append(f"> **Warning:** {warning} The two runs did not score the same data.")
    if warnings:
        lines.append("")
    lines += [
        "| | Baseline | Current |",
        "|---|---|---|",
    ]
    for name, before, after in zip(names, describe(baseline), describe(current), strict=True):
        lines.append(f"| {name} | {before} | {after} |")
    if baseline["method"] != current["method"]:
        lines += [
            "",
            f"> **Note:** the runs use different normalization ({baseline['method']} and "
            f"{current['method']}), so their thresholds are on different scales.",
        ]
    return "\n".join(lines) + "\n"
