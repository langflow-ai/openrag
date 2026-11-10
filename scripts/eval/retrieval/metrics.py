"""File-level retrieval metrics for the OpenRAG retrieval evaluation harness.

``/v1/search`` returns chunks, but questions are labeled by file because chunk
boundaries move whenever chunking changes. This module turns a ranked chunk
list into a ranked list of unique files and scores it with recall@k,
reciprocal rank and nDCG@k. For questions with an ``expected_text`` it also
scores the rank of the chunk that holds the answer.

Standard library only, so it can be unit-tested without the SDK or a stack.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass

DEFAULT_K_VALUES: tuple[int, ...] = (1, 3, 5, 10)
PREFERRED_PRIMARY_K = 5


@dataclass(frozen=True)
class Chunk:
    """One search hit, as returned by the API."""

    filename: str
    text: str
    score: float


@dataclass(frozen=True)
class RankedFile:
    """One unique corpus file in the order its first chunk was returned."""

    filename: str  # canonical corpus filename, run prefix removed
    rank: int  # 1-based position among unique files
    score: float  # score of the file's first chunk
    snippet_found: bool | None  # None when the question has no expected_text


def canonical_name(filename: str, run_prefix: str, corpus_names: Collection[str]) -> str | None:
    """Map an uploaded filename back to its corpus filename.

    Returns None for anything this run did not upload, so stray documents in
    the stack never count for or against a question.
    """
    if not filename.startswith(run_prefix):
        return None
    name = filename[len(run_prefix) :]
    return name if name in corpus_names else None


def normalize(text: str) -> str:
    # Chunking can re-wrap lines, so compare on case-folded, single-spaced text.
    return " ".join(text.casefold().split())


def rank_files(
    chunks: Iterable[Chunk],
    run_prefix: str,
    corpus_names: Collection[str],
    expected_text: str | None = None,
) -> list[RankedFile]:
    """Deduplicate ranked chunks into ranked files, keeping first-occurrence order.

    With ``expected_text``, each file also records whether any of its fetched
    chunks contains the snippet (case- and whitespace-insensitive).
    """
    needle = normalize(expected_text) if expected_text else None
    order: list[str] = []
    first_score: dict[str, float] = {}
    found: dict[str, bool] = {}
    for chunk in chunks:
        name = canonical_name(chunk.filename, run_prefix, corpus_names)
        if name is None:
            continue
        if name not in first_score:
            order.append(name)
            first_score[name] = chunk.score
            found[name] = False
        if needle is not None and not found[name] and needle in normalize(chunk.text):
            found[name] = True
    return [
        RankedFile(
            filename=name,
            rank=position,
            score=first_score[name],
            snippet_found=found[name] if needle is not None else None,
        )
        for position, name in enumerate(order, start=1)
    ]


def expected_ranks(
    ranked: Sequence[RankedFile], expected_files: Iterable[str]
) -> dict[str, int | None]:
    """Rank of each expected file among the unique files, or None if it was not returned."""
    by_name = {item.filename: item.rank for item in ranked}
    return {name: by_name.get(name) for name in expected_files}


def primary_k(k_values: Sequence[int]) -> int:
    """The cutoff used to compare runs: 5 when it is evaluated, otherwise the largest k."""
    return PREFERRED_PRIMARY_K if PREFERRED_PRIMARY_K in k_values else max(k_values)


def score_query(
    ranked: Sequence[RankedFile],
    expected_files: Collection[str],
    k_values: Sequence[int] = DEFAULT_K_VALUES,
) -> dict[str, float]:
    """Score one question with binary gains.

    An expected file is relevant when it was returned and, if the question has
    an ``expected_text``, one of its chunks contained the snippet.

    - ``recall@k``: relevant files in the top k / number of expected files.
    - ``reciprocal_rank``: 1 / rank of the first relevant file, 0 if none.
    - ``ndcg@k``: DCG over the top k / the best DCG achievable with
      min(expected files, k) relevant files at the top.
    """
    expected = set(expected_files)
    if not expected:
        raise ValueError("expected_files must not be empty")
    relevant_ranks = sorted(
        item.rank
        for item in ranked
        if item.filename in expected and item.snippet_found is not False
    )

    recall: dict[str, float] = {}
    ndcg: dict[str, float] = {}
    for k in k_values:
        hits = [rank for rank in relevant_ranks if rank <= k]
        recall[f"recall@{k}"] = len(hits) / len(expected)
        dcg = sum(1.0 / math.log2(rank + 1) for rank in hits)
        ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(expected), k) + 1))
        ndcg[f"ndcg@{k}"] = dcg / ideal
    reciprocal_rank = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
    return {**recall, "reciprocal_rank": reciprocal_rank, **ndcg}


def passage_rank(
    chunks: Iterable[Chunk],
    run_prefix: str,
    corpus_names: Collection[str],
    expected_files: Collection[str],
    expected_text: str,
) -> int | None:
    """Rank of the first chunk that holds the answer, or None if no chunk does.

    The answer chunk is a chunk of an expected file that contains
    ``expected_text`` (case- and whitespace-insensitive). Ranks count only the
    chunks of files this run uploaded, so stray documents never shift them.
    Matching on text rather than chunk IDs keeps the rank meaningful when the
    chunk size changes.
    """
    needle = normalize(expected_text)
    expected = set(expected_files)
    position = 0
    for chunk in chunks:
        name = canonical_name(chunk.filename, run_prefix, corpus_names)
        if name is None:
            continue
        position += 1
        if name in expected and needle in normalize(chunk.text):
            return position
    return None


def chunk_scores(
    chunks: Iterable[Chunk],
    run_prefix: str,
    corpus_names: Collection[str],
    ranked: Sequence[RankedFile],
    expected_files: Collection[str],
    expected_text: str | None,
) -> tuple[list[list[float]], list[int]]:
    """Every chunk of this run's files as ``[file rank, score]``, and where the answers are.

    The second list holds the 1-based positions, among those chunks, of each
    chunk of an expected file that contains ``expected_text``; it is empty when
    the question has none. Together with ``ranked`` this is enough to re-score
    the question at any score threshold without another search.
    """
    rank_of = {item.filename: item.rank for item in ranked}
    needle = _normalize(expected_text) if expected_text else None
    expected = set(expected_files)
    scores: list[list[float]] = []
    answers: list[int] = []
    for chunk in chunks:
        name = canonical_name(chunk.filename, run_prefix, corpus_names)
        if name is None:
            continue
        scores.append([rank_of[name], round(chunk.score, 6)])
        if needle is not None and name in expected and needle in _normalize(chunk.text):
            answers.append(len(scores))
    return scores, answers


def score_passage(rank: int | None, k_values: Sequence[int] = DEFAULT_K_VALUES) -> dict[str, float]:
    """Score one question on the rank of its answer chunk.

    - ``passage_hit@k``: 1 if the answer chunk is in the top k chunks, else 0.
    - ``passage_rr``: 1 / rank of the answer chunk, 0 if none was returned.
    """
    hits = {f"passage_hit@{k}": 1.0 if rank is not None and rank <= k else 0.0 for k in k_values}
    return {**hits, "passage_rr": 1.0 / rank if rank is not None else 0.0}


_MEAN_NAMES = {"reciprocal_rank": "mrr", "passage_rr": "passage_mrr"}


def _mean_scores(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    # Passage scores exist only for questions with an expected_text, so each
    # metric is averaged over the questions that have it.
    keys = list(dict.fromkeys(key for row in rows for key in row))
    means: dict[str, float] = {}
    for key in keys:
        values = [row[key] for row in rows if key in row]
        means[_MEAN_NAMES.get(key, key)] = sum(values) / len(values)
    return means


def aggregate(
    per_query: Sequence[Mapping[str, float]],
    tags: Sequence[Sequence[str]],
) -> dict[str, object]:
    """Mean of every metric over all questions, and again per tag.

    ``per_query`` and ``tags`` are parallel: ``tags[i]`` holds the tags of the
    question scored in ``per_query[i]``.
    """
    if len(per_query) != len(tags):
        raise ValueError("per_query and tags must have the same length")
    if not per_query:
        return {"overall": {}, "by_tag": {}}

    by_tag: dict[str, list[Mapping[str, float]]] = {}
    for scores, query_tags in zip(per_query, tags, strict=True):
        for tag in query_tags:
            by_tag.setdefault(tag, []).append(scores)
    return {
        "overall": _mean_scores(per_query),
        "by_tag": {tag: _tag_scores(rows) for tag, rows in sorted(by_tag.items())},
    }


def _tag_scores(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    scores: dict[str, float] = {"count": len(rows)}
    passage_count = sum(1 for row in rows if "passage_rr" in row)
    if passage_count:
        scores["passage_count"] = passage_count
    return {**scores, **_mean_scores(rows)}
