"""File-level retrieval metrics for the OpenRAG retrieval evaluation harness.

``/v1/search`` returns chunks, but questions are labeled by file because chunk
boundaries move whenever chunking changes. This module turns a ranked chunk
list into a ranked list of unique files and scores it with recall@k,
reciprocal rank and nDCG@k.

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


def _normalize(text: str) -> str:
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
    needle = _normalize(expected_text) if expected_text else None
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
        if needle is not None and not found[name] and needle in _normalize(chunk.text):
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


def _mean_scores(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    means: dict[str, float] = {}
    for key in rows[0]:
        name = "mrr" if key == "reciprocal_rank" else key
        means[name] = sum(row[key] for row in rows) / len(rows)
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
        "by_tag": {
            tag: {"count": len(rows), **_mean_scores(rows)} for tag, rows in sorted(by_tag.items())
        },
    }
