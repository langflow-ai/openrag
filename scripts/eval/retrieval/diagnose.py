"""Turn retrieval scores into reasons: why each question missed, and how clean its context is.

Everything here works from what a run already records per question
(``ranked_files``, ``chunk_scores``, ``passage_rank``), so it can diagnose an old
results file as well as a fresh run. No search, no LLM.

The diagnosis looks at the top ``k`` chunks, the context a chat answer is built
from, where file metrics look at the top ``k`` unique files. A second file whose
first chunk is #9 still counts toward recall@5 when it is the second unique file,
but the chat model may never see it; the diagnosis calls that out.

Standard library only, so it can be unit-tested without the SDK or a stack.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

# Most severe first. Each expected file gets a class and the question takes the
# most severe one; a file is ``paragraph_missed`` when it is in the top k but its
# own chunk holding the answer is not.
NEVER_RETRIEVED = "never_retrieved"
RANKED_LOW = "ranked_low"
CROWDED_OUT = "crowded_out"
PARAGRAPH_MISSED = "paragraph_missed"
MISS_CLASSES: tuple[str, ...] = (NEVER_RETRIEVED, RANKED_LOW, CROWDED_OUT, PARAGRAPH_MISSED)

MISS_LABELS = {
    NEVER_RETRIEVED: "Never retrieved",
    RANKED_LOW: "Ranked low",
    CROWDED_OUT: "Crowded out",
    PARAGRAPH_MISSED: "File found, paragraph missed",
}
MISS_MEANINGS = {
    NEVER_RETRIEVED: "No chunk of an expected file came back at all: a recall problem.",
    RANKED_LOW: "An expected file came back, but its first chunk is below the top k: "
    "a ranking problem.",
    CROWDED_OUT: "An expected file's first chunk is below the top k, behind mostly one "
    "other file's chunks: a diversity problem.",
    PARAGRAPH_MISSED: "An expected file is in the top k chunks, but its chunk holding "
    "the answer is not: a chunking problem.",
}

# The chunks ahead of a missed file count as crowding when more than this share
# of them come from a single other file.
CROWDED_SHARE = 0.5


def chunk_files(record: Mapping[str, Any]) -> list[str]:
    """The corpus filename of every returned chunk of this run's files, in search order."""
    by_rank = {item["rank"]: item["filename"] for item in record.get("ranked_files", [])}
    return [by_rank[int(rank)] for rank, _score in record.get("chunk_scores", [])]


def _relevant_files(record: Mapping[str, Any]) -> set[str]:
    # The same relevance rule as the file metrics: an expected file counts when
    # it came back and, for a question with an expected_text, held the snippet.
    expected = set(record["expected_files"])
    return {
        item["filename"]
        for item in record.get("ranked_files", [])
        if item["filename"] in expected and item.get("snippet_found") is not False
    }


def context_scores(record: Mapping[str, Any], k_values: Sequence[int]) -> dict[str, float]:
    """Precision and noise of the top chunks, and recall capped at what k allows.

    - ``context_precision@k``: rank-weighted precision of the top k chunks, the
      mean of precision@i over the positions i holding a chunk of an expected
      file (0 when none does). Rewards putting relevant chunks first.
    - ``noise@k``: share of the top k chunks that come from files nobody
      expected. The chat answer is built from these chunks.
    - ``capped_recall@k``: relevant files in the top k / min(expected files, k),
      so a two-document question can still score 1 at k=1.
    """
    files = chunk_files(record)
    expected = set(record["expected_files"])
    ranks = {item["filename"]: item["rank"] for item in record.get("ranked_files", [])}
    relevant = _relevant_files(record)
    scores: dict[str, float] = {}
    for k in k_values:
        top = files[:k]
        hits = 0
        precision_sum = 0.0
        for position, name in enumerate(top, start=1):
            if name in expected:
                hits += 1
                precision_sum += hits / position
        scores[f"context_precision@{k}"] = precision_sum / hits if hits else 0.0
        scores[f"noise@{k}"] = (len(top) - hits) / len(top) if top else 0.0
        found = sum(1 for name in relevant if ranks[name] <= k)
        scores[f"capped_recall@{k}"] = found / min(len(expected), k)
    return scores


def _crowded(ahead: Sequence[str], name: str) -> bool:
    others = Counter(file for file in ahead if file != name)
    if not ahead or not others:
        return False
    return others.most_common(1)[0][1] / len(ahead) > CROWDED_SHARE


def first_answer_positions(record: Mapping[str, Any], files: Sequence[str]) -> dict[str, int]:
    """Position of each expected file's first chunk holding the expected_text."""
    first: dict[str, int] = {}
    for position in record.get("answer_chunks", []):
        first.setdefault(files[position - 1], position)
    return first


def classify(record: Mapping[str, Any], k: int) -> dict[str, Any]:
    """Why a question missed at the top k chunks.

    Returns ``{"class": <most severe class or None>, "files": {expected file:
    class or None}}``. A class of None means the question has nothing to fix
    at this cutoff. With an ``expected_text``, every expected file must have its
    own answer chunk in the top k, matching how the file scores treat it.
    """
    files = chunk_files(record)
    first_position: dict[str, int] = {}
    for position, name in enumerate(files, start=1):
        first_position.setdefault(name, position)
    has_text = record.get("expected_text") is not None
    answers = first_answer_positions(record, files) if has_text else {}

    per_file: dict[str, str | None] = {}
    for name in record["expected_files"]:
        position = first_position.get(name)
        if position is None:
            per_file[name] = NEVER_RETRIEVED
        elif position > k:
            per_file[name] = CROWDED_OUT if _crowded(files[: position - 1], name) else RANKED_LOW
        elif has_text and answers.get(name, k + 1) > k:
            per_file[name] = PARAGRAPH_MISSED
        else:
            per_file[name] = None

    found = [cls for cls in per_file.values() if cls is not None]
    question_class: str | None = min(found, key=MISS_CLASSES.index) if found else None
    return {"class": question_class, "files": per_file}


def label_holes(record: Mapping[str, Any], k: int) -> list[dict[str, Any]]:
    """Unlabeled files ranked above every expected file, within the top k files.

    These are either confusers the ranking should push down, or relevant files
    the question's labels are missing. A person has to look to tell which, so
    the report lists them instead of scoring them.
    """
    expected = set(record["expected_files"])
    ranked = record.get("ranked_files", [])
    best = min((item["rank"] for item in ranked if item["filename"] in expected), default=None)
    limit = k if best is None else min(k, best - 1)
    return [
        {"filename": item["filename"], "rank": item["rank"]}
        for item in ranked
        if item["rank"] <= limit and item["filename"] not in expected
    ]


def diagnosable(record: Mapping[str, Any]) -> bool:
    """Whether the record holds per-chunk data; results from before it was recorded do not."""
    return "chunk_scores" in record


def annotate(records: Sequence[dict[str, Any]], k: int, k_values: Sequence[int]) -> None:
    """Add context scores to each record's metrics and its diagnosis, in place.

    Records without per-chunk data are left alone rather than misread as misses.
    """
    for record in records:
        if not diagnosable(record):
            continue
        record["metrics"].update(context_scores(record, k_values))
        record["diagnosis"] = {**classify(record, k), "label_holes": label_holes(record, k)}


def summarize(records: Sequence[Mapping[str, Any]], k: int) -> dict[str, Any]:
    """Miss counts overall and per tag, and every question with label holes."""

    def counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        tally = Counter(row["diagnosis"]["class"] for row in rows)
        return {"questions": len(rows), **{cls: tally.get(cls, 0) for cls in MISS_CLASSES}}

    skipped = sum(1 for record in records if "diagnosis" not in record)
    records = [record for record in records if "diagnosis" in record]
    by_tag: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        for tag in record["tags"]:
            by_tag.setdefault(tag, []).append(record)
    return {
        "k": k,
        "skipped": skipped,
        "overall": counts(records),
        "by_tag": {tag: counts(rows) for tag, rows in sorted(by_tag.items())},
        "label_holes": [
            {"id": record["id"], "files": record["diagnosis"]["label_holes"]}
            for record in records
            if record["diagnosis"]["label_holes"]
        ],
    }
