"""Unit tests for the pure modules of the retrieval evaluation harness.

The harness lives in scripts/eval/retrieval/. Its scoring, dataset and report
modules use only the standard library, so they are tested here without the
OpenRAG SDK or a running stack.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts.eval.retrieval import answers, dataset, metrics, report, scores

PREFIX = "eval-abc12345-"
CORPUS = frozenset({"a.md", "b.md", "c.md", "d.md"})


def chunk(name: str, text: str = "", score: float = 1.0, prefix: str = PREFIX) -> metrics.Chunk:
    return metrics.Chunk(filename=f"{prefix}{name}", text=text, score=score)


def ranked(*names: str) -> list[metrics.RankedFile]:
    return metrics.rank_files([chunk(name) for name in names], PREFIX, CORPUS)


# --- ranking ---------------------------------------------------------------


def test_rank_files_deduplicates_in_first_occurrence_order() -> None:
    chunks = [
        chunk("b.md", score=0.9),
        chunk("a.md", score=0.8),
        chunk("b.md", score=0.7),
        chunk("c.md", score=0.6),
        chunk("a.md", score=0.5),
    ]

    result = metrics.rank_files(chunks, PREFIX, CORPUS)

    assert [(item.filename, item.rank, item.score) for item in result] == [
        ("b.md", 1, 0.9),
        ("a.md", 2, 0.8),
        ("c.md", 3, 0.6),
    ]
    assert all(item.snippet_found is None for item in result)


def test_rank_files_ignores_files_this_run_did_not_upload() -> None:
    chunks = [
        metrics.Chunk("a.md", "", 0.9),  # same name, no run prefix
        chunk("a.md", prefix="eval-other999-"),  # another run's copy
        chunk("unknown.md"),  # right prefix, not a corpus file
        chunk("c.md", score=0.4),
    ]

    result = metrics.rank_files(chunks, PREFIX, CORPUS)

    assert [(item.filename, item.rank) for item in result] == [("c.md", 1)]


def test_canonical_name_strips_only_the_run_prefix() -> None:
    assert metrics.canonical_name(f"{PREFIX}a.md", PREFIX, CORPUS) == "a.md"
    assert metrics.canonical_name("a.md", PREFIX, CORPUS) is None
    assert metrics.canonical_name(f"{PREFIX}{PREFIX}a.md", PREFIX, CORPUS) is None


def test_expected_ranks_reports_missing_files_as_none() -> None:
    assert metrics.expected_ranks(ranked("c.md", "a.md"), ["a.md", "b.md"]) == {
        "a.md": 2,
        "b.md": None,
    }


# --- metrics ---------------------------------------------------------------


def test_score_query_single_expected_file_at_rank_two() -> None:
    scores = metrics.score_query(ranked("b.md", "a.md", "c.md"), ["a.md"], [1, 3])

    assert scores["recall@1"] == 0.0
    assert scores["recall@3"] == 1.0
    assert scores["reciprocal_rank"] == 0.5
    assert scores["ndcg@1"] == 0.0
    assert scores["ndcg@3"] == pytest.approx(1 / math.log2(3))


def test_score_query_perfect_ranking_scores_one() -> None:
    scores = metrics.score_query(ranked("a.md", "b.md", "c.md"), ["a.md", "b.md"], [1, 3, 5])

    assert scores["recall@1"] == 0.5
    assert scores["recall@3"] == 1.0
    assert scores["reciprocal_rank"] == 1.0
    # At k=1 only one of the two expected files can fit, so rank 1 is ideal.
    assert scores["ndcg@1"] == 1.0
    assert scores["ndcg@3"] == pytest.approx(1.0)
    assert scores["ndcg@5"] == pytest.approx(1.0)


def test_score_query_multi_file_partial_hit() -> None:
    # Expected a.md and b.md; a.md comes back third, b.md not at all.
    scores = metrics.score_query(ranked("c.md", "d.md", "a.md"), ["a.md", "b.md"], [3])

    assert scores["recall@3"] == 0.5
    assert scores["reciprocal_rank"] == pytest.approx(1 / 3)
    ideal = 1 / math.log2(2) + 1 / math.log2(3)
    assert scores["ndcg@3"] == pytest.approx((1 / math.log2(4)) / ideal)


def test_score_query_no_hit_scores_zero() -> None:
    scores = metrics.score_query(ranked("c.md", "d.md"), ["a.md"], [1, 5])

    assert scores == {
        "recall@1": 0.0,
        "ndcg@1": 0.0,
        "recall@5": 0.0,
        "ndcg@5": 0.0,
        "reciprocal_rank": 0.0,
    }


def test_score_query_handles_fewer_results_than_k() -> None:
    scores = metrics.score_query(ranked("a.md"), ["a.md"], [10])

    assert scores["recall@10"] == 1.0
    assert scores["ndcg@10"] == 1.0
    assert metrics.score_query([], ["a.md"], [10])["recall@10"] == 0.0


def test_score_query_rejects_empty_expected_files() -> None:
    with pytest.raises(ValueError):
        metrics.score_query(ranked("a.md"), [], [5])


def test_expected_text_gates_relevance_but_keeps_first_chunk_rank() -> None:
    chunks = [
        chunk("a.md", "Unrelated introduction."),
        chunk("b.md", "Nothing useful here."),
        chunk("a.md", "To ROTATE   a key,\nopen the console."),
    ]

    result = metrics.rank_files(chunks, PREFIX, CORPUS, expected_text="rotate a key, open")

    # The snippet is in a.md's second chunk, yet a.md keeps rank 1.
    assert [(item.filename, item.rank, item.snippet_found) for item in result] == [
        ("a.md", 1, True),
        ("b.md", 2, False),
    ]
    assert metrics.score_query(result, ["a.md"], [1])["recall@1"] == 1.0


def test_expected_file_without_the_snippet_is_not_relevant() -> None:
    chunks = [chunk("a.md", "A chunk that never mentions it."), chunk("b.md", "rotate")]

    result = metrics.rank_files(chunks, PREFIX, CORPUS, expected_text="rotate")
    scores = metrics.score_query(result, ["a.md"], [5])

    assert result[0].snippet_found is False
    assert scores["recall@5"] == 0.0
    assert scores["reciprocal_rank"] == 0.0


def test_passage_rank_finds_the_answer_chunk_below_the_files_first_chunk() -> None:
    chunks = [
        chunk("a.md", "Introduction to keys."),
        chunk("b.md", "Signing secrets also rotate."),
        chunk("a.md", "Keep the OVERLAP\n window short."),
    ]

    rank = metrics.passage_rank(chunks, PREFIX, CORPUS, ["a.md"], "overlap window")

    # File recall gives a.md full marks at rank 1; the answer itself is chunk 3.
    assert rank == 3
    assert metrics.score_passage(rank, [1, 3, 5]) == {
        "passage_hit@1": 0.0,
        "passage_hit@3": 1.0,
        "passage_hit@5": 1.0,
        "passage_rr": pytest.approx(1 / 3),
    }


def test_passage_rank_ignores_the_text_in_files_that_are_not_expected() -> None:
    chunks = [chunk("b.md", "overlap window"), chunk("a.md", "Nothing here.")]

    rank = metrics.passage_rank(chunks, PREFIX, CORPUS, ["a.md"], "overlap window")

    assert rank is None
    assert metrics.score_passage(rank, [5]) == {"passage_hit@5": 0.0, "passage_rr": 0.0}


def test_passage_rank_does_not_count_chunks_from_other_documents() -> None:
    chunks = [
        chunk("a.md", "overlap window", prefix="eval-other123-"),
        chunk("stray.md", "overlap window"),
        chunk("a.md", "overlap window"),
    ]

    assert metrics.passage_rank(chunks, PREFIX, CORPUS, ["a.md"], "overlap window") == 1


def test_aggregate_averages_passage_scores_over_questions_that_have_them() -> None:
    per_query = [
        {"recall@5": 1.0, "passage_hit@5": 1.0, "passage_rr": 0.5},
        {"recall@5": 0.0, "passage_hit@5": 0.0, "passage_rr": 0.0},
        {"recall@5": 1.0},
    ]
    tags = [["semantic"], ["semantic"], ["semantic"]]

    result: Any = metrics.aggregate(per_query, tags)

    assert result["overall"] == {
        "recall@5": pytest.approx(2 / 3),
        "passage_hit@5": 0.5,
        "passage_mrr": 0.25,
    }
    assert result["by_tag"]["semantic"]["count"] == 3
    assert result["by_tag"]["semantic"]["passage_count"] == 2


def test_primary_k_prefers_five_then_largest() -> None:
    assert metrics.primary_k([1, 3, 5, 10]) == 5
    assert metrics.primary_k([1, 3]) == 3


def test_aggregate_means_overall_and_per_tag() -> None:
    per_query = [
        {"recall@5": 1.0, "ndcg@5": 1.0, "reciprocal_rank": 1.0},
        {"recall@5": 0.0, "ndcg@5": 0.0, "reciprocal_rank": 0.0},
        {"recall@5": 0.5, "ndcg@5": 0.4, "reciprocal_rank": 0.5},
    ]
    tags = [["semantic"], ["semantic", "exact-token"], []]

    result: Any = metrics.aggregate(per_query, tags)

    assert result["overall"] == {
        "recall@5": pytest.approx(0.5),
        "ndcg@5": pytest.approx(1.4 / 3),
        "mrr": pytest.approx(0.5),
    }
    assert list(result["by_tag"]) == ["exact-token", "semantic"]
    assert result["by_tag"]["semantic"] == {
        "count": 2,
        "recall@5": 0.5,
        "ndcg@5": 0.5,
        "mrr": 0.5,
    }
    assert result["by_tag"]["exact-token"]["count"] == 1
    assert metrics.aggregate([], []) == {"overall": {}, "by_tag": {}}


# --- dataset ---------------------------------------------------------------


def write_dataset(tmp_path: Path, rows: list[Any]) -> tuple[Path, Path]:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for name in ("a.md", "b.md"):
        (corpus / name).write_text(f"# {name}\n", encoding="utf-8")
    (corpus / ".DS_Store").write_text("", encoding="utf-8")
    queries = tmp_path / "queries.jsonl"
    queries.write_text(
        "\n".join(row if isinstance(row, str) else json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return corpus, queries


def test_load_queries_accepts_valid_rows_and_fills_defaults(tmp_path: Path) -> None:
    corpus, queries_path = write_dataset(
        tmp_path,
        [
            {"query": "how do I rotate a key", "expected_files": ["a.md"]},
            "",
            {
                "id": "q-multi",
                "query": " which docs cover billing ",
                "expected_files": ["a.md", "b.md"],
                "expected_text": "invoice",
                "tags": ["multi-doc"],
            },
        ],
    )
    names = dataset.list_corpus(corpus)

    queries = dataset.load_queries(queries_path, names)

    assert names == ["a.md", "b.md"]  # hidden files are not corpus documents
    assert queries == [
        dataset.Query(
            id="how do I rotate a key",  # falls back to the query text
            query="how do I rotate a key",
            expected_files=("a.md",),
        ),
        dataset.Query(
            id="q-multi",
            query="which docs cover billing",
            expected_files=("a.md", "b.md"),
            expected_text="invoice",
            tags=("multi-doc",),
        ),
    ]


def test_load_queries_reports_every_problem_with_its_line_number(tmp_path: Path) -> None:
    corpus, queries_path = write_dataset(
        tmp_path,
        [
            {"id": "q1", "query": "fine", "expected_files": ["a.md"]},
            "{not json",
            {"query": "   ", "expected_files": ["a.md"]},
            {"query": "no files", "expected_files": []},
            {"query": "typo", "expected_files": ["missing.md"]},
            {"id": "q1", "query": "same id", "expected_files": ["b.md"]},
            {"query": "bad field", "expected_file": ["a.md"]},
            ["not", "an", "object"],
            {"query": "bad tags", "expected_files": ["a.md"], "tags": "semantic"},
            {"query": "bad snippet", "expected_files": ["a.md"], "expected_text": ""},
        ],
    )

    with pytest.raises(dataset.DatasetError) as excinfo:
        dataset.load_queries(queries_path, dataset.list_corpus(corpus))

    message = str(excinfo.value)
    for expected in (
        "queries.jsonl:2: invalid JSON",
        "queries.jsonl:3: 'query' must be a non-empty string",
        "queries.jsonl:4: 'expected_files' must be a non-empty list of filenames",
        "queries.jsonl:5: expected file not in corpus: missing.md",
        "queries.jsonl:6: duplicate id 'q1' (first used on line 1)",
        "queries.jsonl:7: unknown field(s): expected_file",
        "queries.jsonl:7: 'expected_files' must be a non-empty list of filenames",
        "queries.jsonl:8: row must be a JSON object",
        "queries.jsonl:9: 'tags' must be a list of non-empty strings",
        "queries.jsonl:10: 'expected_text' must be a non-empty string",
    ):
        assert expected in message
    assert "queries.jsonl:1:" not in message


def test_load_queries_checks_expected_text_against_the_corpus(tmp_path: Path) -> None:
    corpus, queries_path = write_dataset(
        tmp_path,
        [
            {"query": "ok", "expected_files": ["a.md"], "expected_text": "#  A.MD"},
            {"query": "typo", "expected_files": ["a.md", "b.md"], "expected_text": "# a.md"},
        ],
    )
    names = dataset.list_corpus(corpus)

    # Without the corpus directory the snippets are not checked.
    assert len(dataset.load_queries(queries_path, names)) == 2

    with pytest.raises(dataset.DatasetError) as excinfo:
        dataset.load_queries(queries_path, names, corpus)

    assert str(excinfo.value) == (
        "queries.jsonl:2: 'expected_text' '# a.md' does not appear in b.md"
    )


def test_load_queries_rejects_missing_or_empty_inputs(tmp_path: Path) -> None:
    corpus, queries_path = write_dataset(tmp_path, [""])
    names = dataset.list_corpus(corpus)

    with pytest.raises(dataset.DatasetError, match="no questions found"):
        dataset.load_queries(queries_path, names)
    with pytest.raises(dataset.DatasetError, match="question file not found"):
        dataset.load_queries(tmp_path / "nope.jsonl", names)
    with pytest.raises(dataset.DatasetError, match="corpus directory not found"):
        dataset.list_corpus(tmp_path / "nope")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(dataset.DatasetError, match="corpus directory is empty"):
        dataset.list_corpus(empty)


def test_hash_corpus_changes_with_content_and_with_filenames(tmp_path: Path) -> None:
    corpus, _ = write_dataset(tmp_path, [""])
    names = dataset.list_corpus(corpus)
    original = dataset.hash_corpus(corpus, names)

    assert dataset.hash_corpus(corpus, list(reversed(names))) == original

    (corpus / "a.md").write_text("# a.md, edited\n", encoding="utf-8")
    edited = dataset.hash_corpus(corpus, names)
    assert edited != original

    (corpus / "a.md").rename(corpus / "z.md")
    assert dataset.hash_corpus(corpus, dataset.list_corpus(corpus)) != edited


# --- report ----------------------------------------------------------------


def make_query(
    query_id: str, recall: float, rr: float, ndcg: float, rank: int | None
) -> dict[str, Any]:
    return {
        "id": query_id,
        "query": f"question {query_id}",
        "tags": ["semantic"],
        "expected_files": ["a.md"],
        "expected_text": None,
        "chunks_returned": 3,
        "unique_files_returned": 2,
        "ranked_files": [{"filename": "b.md", "rank": 1, "score": 0.9, "snippet_found": None}],
        "expected_ranks": {"a.md": rank},
        "snippet_found": None,
        "metrics": {"recall@5": recall, "reciprocal_rank": rr, "ndcg@5": ndcg},
    }


def make_results(queries: list[dict[str, Any]], **run_overrides: Any) -> dict[str, Any]:
    scores = [q["metrics"] for q in queries]
    run = {
        "run_id": "eval-11111111",
        "timestamp": "2026-10-12T00:00:00Z",
        "target_url": "http://localhost:3000",
        "sdk_version": "0.4.0",
        "git_commit": "abc123",
        "corpus_files": 2,
        "corpus_hash": "c" * 64,
        "query_count": len(queries),
        "queries_hash": "d" * 64,
        "k_values": [1, 3, 5, 10],
        "primary_k": 5,
        "fetch_limit": 50,
        "score_threshold": 0.0,
    }
    run.update(run_overrides)
    return {
        "schema_version": report.SCHEMA_VERSION,
        "run": run,
        "settings": {"embedding_model": "model-a", "chunk_size": 1000, "chunk_overlap": 200},
        "settings_note": None,
        "metrics": metrics.aggregate(scores, [q["tags"] for q in queries]),
        "queries": queries,
    }


def test_diff_classifies_each_question_and_lists_added_and_removed() -> None:
    baseline = make_results(
        [
            make_query("worse", 1.0, 1.0, 1.0, 1),
            make_query("better", 0.0, 0.0, 0.0, None),
            make_query("same", 1.0, 0.5, 0.63, 2),
            make_query("rank-only", 1.0, 1.0, 1.0, 1),
            make_query("gone", 1.0, 1.0, 1.0, 1),
        ]
    )
    current = make_results(
        [
            make_query("worse", 0.0, 0.0, 0.0, None),
            make_query("better", 1.0, 1.0, 1.0, 1),
            make_query("same", 1.0, 0.5, 0.63, 2),
            # Still inside the top 5, so recall holds; the lower rank decides.
            make_query("rank-only", 1.0, 0.25, 0.43, 4),
            make_query("new", 1.0, 1.0, 1.0, 1),
        ],
        run_id="eval-22222222",
    )

    diff = report.diff_results(baseline, current)

    assert [entry["id"] for entry in diff["regressed"]] == ["worse", "rank-only"]
    assert [entry["id"] for entry in diff["improved"]] == ["better"]
    assert diff["unchanged"] == 1
    assert diff["added"] == ["new"]
    assert diff["removed"] == ["gone"]
    worse = diff["regressed"][0]
    assert worse["metrics"]["recall@5"] == {"baseline": 1.0, "current": 0.0, "delta": -1.0}
    assert worse["expected_ranks"] == {"baseline": {"a.md": 1}, "current": {"a.md": None}}
    assert diff["aggregate"]["recall@5"]["delta"] == pytest.approx(0.0)
    assert any("do not cover the same questions" in w for w in diff["warnings"])


def test_diff_ignores_changes_within_epsilon() -> None:
    baseline = make_results([make_query("q", 1.0, 0.5, 0.63, 2)])
    current = make_results([make_query("q", 1.0, 0.5 + 1e-12, 0.63, 2)])

    diff = report.diff_results(baseline, current)

    assert diff["regressed"] == []
    assert diff["improved"] == []
    assert diff["unchanged"] == 1
    assert diff["warnings"] == []


def test_diff_warns_when_runs_are_not_comparable() -> None:
    baseline = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])
    current = make_results(
        [make_query("q", 1.0, 1.0, 1.0, 1)],
        corpus_hash="e" * 64,
        queries_hash="f" * 64,
        k_values=[1, 5],
        fetch_limit=20,
        score_threshold=0.2,
    )
    current["settings"]["chunk_size"] = 500

    warnings = "\n".join(report.diff_results(baseline, current)["warnings"])

    for expected in (
        "The corpus differs",
        "The question file differs",
        "The k values differ",
        "The fetch limit differs",
        "The score threshold differs",
        "Setting 'chunk_size' differs between the runs (baseline 1000, current 500)",
    ):
        assert expected in warnings
    assert "embedding_model" not in warnings

    current["settings"] = None
    warnings = "\n".join(report.diff_results(baseline, current)["warnings"])
    assert "Only one run recorded the stack settings" in warnings


def test_summary_lists_regressions_before_improvements() -> None:
    baseline = make_results(
        [make_query("worse", 1.0, 1.0, 1.0, 1), make_query("better", 0.0, 0.0, 0.0, None)]
    )
    current = make_results(
        [make_query("worse", 0.0, 0.0, 0.0, None), make_query("better", 1.0, 1.0, 1.0, 1)]
    )

    summary = report.render_summary(current, report.diff_results(baseline, current))

    assert "| recall@5 | 0.500 |" in summary
    assert "| semantic | 2 | 0.500 | 0.500 | 0.500 |" in summary
    assert "## Questions below full recall@5 (1)" in summary
    assert summary.index("### Regressed (1)") < summary.index("### Improved (1)")
    assert "a.md: #1 → a.md: not returned" in summary
    assert "1 regressed, 1 improved, 0 unchanged" in summary


def test_diff_explains_a_drop_caused_by_a_missing_snippet() -> None:
    # Same rank in both runs, but the current run no longer returns a chunk
    # holding the expected text, so the file stops counting as relevant.
    before = make_query("q", 1.0, 1.0, 1.0, 1)
    before["ranked_files"] = [{"filename": "a.md", "rank": 1, "score": 0.9, "snippet_found": True}]
    after = make_query("q", 0.0, 0.0, 0.0, 1)
    after["ranked_files"] = [{"filename": "a.md", "rank": 1, "score": 0.9, "snippet_found": False}]

    diff = report.diff_results(make_results([before]), make_results([after]))

    assert diff["regressed"][0]["snippet_missing"] == {"baseline": [], "current": ["a.md"]}
    assert "a.md: #1 → a.md: #1 (snippet not found)" in report.render_diff(diff)


def with_passage(query: dict[str, Any], rank: int | None) -> dict[str, Any]:
    query["expected_text"] = "overlap window"
    query["passage_rank"] = rank
    query["metrics"].update(metrics.score_passage(rank, [5]))
    return query


def test_summary_and_diff_show_the_answer_chunk_rank() -> None:
    baseline = make_results([with_passage(make_query("q", 1.0, 1.0, 1.0, 1), 2)])
    current = make_results(
        [with_passage(make_query("q", 0.0, 0.0, 0.0, None), None)], passage_questions=1
    )

    summary = report.render_summary(current, report.diff_results(baseline, current))

    assert "| Passage MRR | 0.000 |" in summary
    assert "| passage hit@5 | 0.000 |" in summary
    assert "cover the 1 of 1 questions that have an expected_text" in summary
    assert "| semantic | 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |" in summary
    # The questions-below-recall table and the regressed table both show it.
    assert "| n/a | not returned |" in summary
    assert "| #2 → not returned |" in summary


def test_diff_with_an_old_baseline_compares_file_scores_and_says_why() -> None:
    baseline = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])
    current = make_results([with_passage(make_query("q", 1.0, 1.0, 1.0, 1), 3)])

    diff = report.diff_results(baseline, current)

    assert diff["unchanged"] == 1
    assert "passage_mrr" not in diff["aggregate"]
    assert diff["warnings"] == []
    assert any("baseline has no passage scores" in note for note in diff["notes"])
    assert "> **Note:** The baseline has no passage scores" in report.render_diff(diff)


def test_an_old_baseline_still_passes_the_gate_and_allows_promotion() -> None:
    old = _results_with_recall(0.5)
    same = make_results([with_passage(make_query("q", 0.5, 0.5, 0.5, 1), 1)])
    better = make_results([with_passage(make_query("q", 1.0, 1.0, 1.0, 1), 1)])

    assert report.recall_gate_failure(report.diff_results(old, same), 0.02) is None
    promoted, reason = report.promotion_decision(old, better)
    assert promoted, reason


def test_render_diff_says_so_when_nothing_changed() -> None:
    results = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])

    text = report.render_diff(report.diff_results(results, results))

    assert "No question regressed." in text
    assert "No question improved." in text


def test_write_results_writes_latest_and_timestamped_copies(tmp_path: Path) -> None:
    results = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])
    started_at = datetime(2026, 10, 12, 9, 30, 5, tzinfo=UTC)

    written = report.write_results(results, "# summary\n", tmp_path / "results", started_at)

    assert [path.name for path in written] == [
        "results.json",
        "results_20261012_093005.json",
        "summary.md",
        "summary_20261012_093005.md",
    ]
    assert report.load_results(written[0]) == results
    assert written[1].read_text(encoding="utf-8") == written[0].read_text(encoding="utf-8")
    assert written[3].read_text(encoding="utf-8") == "# summary\n"


def test_load_results_rejects_files_that_are_not_harness_output(tmp_path: Path) -> None:
    path = tmp_path / "results.json"

    with pytest.raises(report.ResultsError, match="cannot read results file"):
        report.load_results(path)

    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(report.ResultsError, match="is not valid JSON"):
        report.load_results(path)

    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(report.ResultsError, match="not a retrieval evaluation results file"):
        report.load_results(path)

    stale = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])
    stale["schema_version"] = 0
    path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(report.ResultsError, match="schema version 0"):
        report.load_results(path)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:3000", "http://localhost:3000"),
        ("http://[::1]:3000/", "http://[::1]:3000"),
        ("http://user:secret@[2001:db8::1]/base", "http://[2001:db8::1]/base"),
        (
            "https://user:secret@rag.example.com:8443/base/?token=abc#frag",
            "https://rag.example.com:8443/base",
        ),
    ],
)
def test_redact_url_drops_credentials_and_query(url: str, expected: str) -> None:
    assert report.redact_url(url) == expected


def test_diff_falls_back_to_a_cutoff_both_runs_have() -> None:
    before = make_query("q", 1.0, 1.0, 1.0, 1)
    before["metrics"].update({"recall@3": 1.0, "ndcg@3": 1.0})
    after = make_query("q", 1.0, 1.0, 1.0, 1)
    after["metrics"] = {"recall@3": 0.0, "recall@4": 1.0, "reciprocal_rank": 1.0, "ndcg@3": 0.0}

    diff = report.diff_results(
        make_results([before]), make_results([after], k_values=[3, 4], primary_k=4)
    )

    assert diff["compare_metrics"] == ["recall@3", "reciprocal_rank", "ndcg@3"]
    assert [entry["id"] for entry in diff["regressed"]] == ["q"]
    assert "compared on recall@3" in "\n".join(diff["warnings"])


def test_diff_rejects_runs_without_a_shared_cutoff() -> None:
    baseline = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])
    current = make_results([make_query("q", 1.0, 1.0, 1.0, 1)], k_values=[2, 4], primary_k=4)

    with pytest.raises(report.ResultsError, match="share no k value"):
        report.diff_results(baseline, current)


@pytest.mark.parametrize("fetch_limit", ["0", "-1", "4"])
def test_run_rejects_a_fetch_limit_below_the_largest_cutoff(fetch_limit: str) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/eval/retrieval/run_eval.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "run",
            "--validate-only",
            "--k",
            "1,5",
            "--fetch-limit",
            fetch_limit,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "--fetch-limit must be at least the largest --k value (5)" in completed.stderr


# --- recall-drop gate --------------------------------------------------------


@pytest.mark.parametrize(
    ("current_recall", "expected_drop"),
    [(0.0, 1.0), (1.0, 0.0)],
)
def test_recall_drop_reports_a_fall_and_ignores_a_gain(
    current_recall: float, expected_drop: float
) -> None:
    baseline = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])
    current = make_results([make_query("q", current_recall, 1.0, 1.0, 1)])

    assert report.recall_drop(report.diff_results(baseline, current)) == pytest.approx(
        expected_drop
    )

    improved = make_results([make_query("q", 0.0, 0.0, 0.0, None)])
    gain = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])
    assert report.recall_drop(report.diff_results(improved, gain)) == 0.0


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        (["--max-recall-drop", "0.02"], "--max-recall-drop needs --baseline"),
        (["--max-recall-drop", "-0.1", "--baseline", "b.json"], "must not be negative"),
    ],
)
def test_run_rejects_an_unusable_max_recall_drop(extra_args: list[str], message: str) -> None:
    script = Path(__file__).resolve().parents[2] / "scripts/eval/retrieval/run_eval.py"
    completed = subprocess.run(
        [sys.executable, str(script), "run", "--validate-only", *extra_args],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert message in completed.stderr


# --- baseline promotion ----------------------------------------------------


def _results_with_recall(recall: float, **run_overrides: Any) -> dict[str, Any]:
    return make_results([make_query("q", recall, recall, recall, 1)], **run_overrides)


def test_promotion_accepts_the_first_baseline() -> None:
    promoted, reason = report.promotion_decision(None, _results_with_recall(0.5))

    assert promoted
    assert "no baseline" in reason


@pytest.mark.parametrize(
    ("baseline_recall", "current_recall", "min_gain", "expected"),
    [
        (0.5, 0.75, 0.0, True),
        (0.5, 0.5, 0.0, False),
        (0.75, 0.5, 0.0, False),
        (0.5, 0.55, 0.1, False),
        (0.5, 0.75, 0.1, True),
    ],
)
def test_promotion_requires_a_gain_above_the_minimum(
    baseline_recall: float, current_recall: float, min_gain: float, expected: bool
) -> None:
    promoted, _ = report.promotion_decision(
        _results_with_recall(baseline_recall), _results_with_recall(current_recall), min_gain
    )

    assert promoted is expected


def test_promotion_refuses_runs_that_are_not_comparable() -> None:
    promoted, reason = report.promotion_decision(
        _results_with_recall(0.5), _results_with_recall(1.0, corpus_hash="e" * 64)
    )

    assert not promoted
    assert "not comparable" in reason


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[2] / "scripts/eval/retrieval/run_eval.py"
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, check=False
    )


def test_promote_writes_the_baseline_only_on_improvement(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    low, high = tmp_path / "low.json", tmp_path / "high.json"
    low.write_text(json.dumps(_results_with_recall(0.5)), encoding="utf-8")
    high.write_text(json.dumps(_results_with_recall(1.0)), encoding="utf-8")

    first = _run_cli("promote", str(low), str(baseline))
    assert first.returncode == 0
    assert json.loads(baseline.read_text(encoding="utf-8")) == json.loads(low.read_text())

    same = _run_cli("promote", str(low), str(baseline))
    assert same.returncode == 3
    assert "Baseline not updated" in same.stdout

    better = _run_cli("promote", str(high), str(baseline))
    assert better.returncode == 0
    assert json.loads(baseline.read_text(encoding="utf-8")) == json.loads(high.read_text())

    worse = _run_cli("promote", str(low), str(baseline))
    assert worse.returncode == 3
    assert json.loads(baseline.read_text(encoding="utf-8")) == json.loads(high.read_text())


# --- review follow-ups -------------------------------------------------------


def test_recall_gate_fails_when_the_runs_are_not_comparable() -> None:
    baseline = _results_with_recall(0.5)
    current = _results_with_recall(0.5, corpus_hash="e" * 64)

    failure = report.recall_gate_failure(report.diff_results(baseline, current), 0.02)

    assert failure is not None
    assert "not comparable" in failure


@pytest.mark.parametrize(
    ("current_recall", "fails"),
    [(0.5, False), (0.49, False), (0.45, True), (1.0, False)],
)
def test_recall_gate_fails_only_on_a_drop_above_the_limit(
    current_recall: float, fails: bool
) -> None:
    diff = report.diff_results(_results_with_recall(0.5), _results_with_recall(current_recall))

    assert (report.recall_gate_failure(diff, 0.02) is not None) is fails


@pytest.mark.parametrize("missing", ["current", "baseline"])
def test_promotion_refuses_a_run_without_recorded_settings(missing: str) -> None:
    baseline, current = _results_with_recall(0.5), _results_with_recall(1.0)
    (current if missing == "current" else baseline)["settings"] = None

    promoted, reason = report.promotion_decision(baseline, current)

    assert not promoted
    assert "settings" in reason


def test_promotion_refuses_a_first_baseline_without_recorded_settings() -> None:
    current = _results_with_recall(0.5)
    current["settings"] = None

    promoted, reason = report.promotion_decision(None, current)

    assert not promoted
    assert "settings" in reason


def test_promote_rejects_a_negative_min_gain(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text(json.dumps(_results_with_recall(0.5)), encoding="utf-8")

    completed = _run_cli("promote", str(results), str(tmp_path / "b.json"), "--min-gain", "-0.1")

    assert completed.returncode == 2
    assert "--min-gain must not be negative" in completed.stderr


# --- hosted environments: leftovers and preflight --------------------------


def test_find_leftovers_matches_only_run_uploads_of_corpus_files() -> None:
    files = [
        ("eval-abc12345-b.md", "2026-11-03T10:00:00Z"),
        ("eval-abc12345-a.md", "2026-11-03T10:00:00"),
        ("eval-0000ffff-c.md", None),
        ("eval-abc12345-notes.md", "2026-11-03T10:00:00Z"),  # not a corpus file
        ("eval-plan-a.md", "2026-11-03T10:00:00Z"),  # a user's document
        ("EVAL-abc12345-a.md", "2026-11-03T10:00:00Z"),
        ("my-eval-abc12345-a.md", "2026-11-03T10:00:00Z"),
    ]

    leftovers = dataset.find_leftovers(files, CORPUS)

    assert [(item.run_id, item.filename) for item in leftovers] == [
        ("eval-0000ffff", "eval-0000ffff-c.md"),
        ("eval-abc12345", "eval-abc12345-a.md"),
        ("eval-abc12345", "eval-abc12345-b.md"),
    ]
    # A timestamp without a zone is read as UTC; a missing one stays unknown.
    assert leftovers[1].indexed_time == datetime(2026, 11, 3, 10, tzinfo=UTC)
    assert leftovers[0].indexed_time is None


@pytest.mark.parametrize(
    ("indexed_time", "expected"),
    [
        ("2026-11-03T09:00:00Z", True),  # exactly the minimum age
        ("2026-11-03T08:00:00+00:00", True),
        ("2026-11-03T09:30:00Z", False),  # may belong to a run still going
        (None, False),
        ("not a time", False),
    ],
)
def test_old_enough_keeps_recent_and_undated_uploads(
    indexed_time: str | None, expected: bool
) -> None:
    (leftover,) = dataset.find_leftovers([("eval-abc12345-a.md", indexed_time)], CORPUS)
    now = datetime(2026, 11, 3, 10, tzinfo=UTC)

    assert dataset.old_enough(leftover, now, timedelta(minutes=60)) is expected


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["check"], "no API key"),
        (["cleanup"], "no API key"),
        (["cleanup", "--min-age", "-5", "--api-key", "x"], "--min-age must not be negative"),
    ],
)
def test_check_and_cleanup_reject_unusable_arguments_before_contacting_a_stack(
    argv: list[str], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENRAG_API_KEY", raising=False)
    completed = _run_cli(*argv)

    assert completed.returncode != 0
    assert message in completed.stderr


# --- answer quality --------------------------------------------------------


def test_answer_cited_rank_ignores_strays() -> None:
    sources = [
        {"filename": "a.md"},
        {"filename": PREFIX + "unknown.md"},
        {"filename": PREFIX + "b.md"},
        {"filename": PREFIX + "a.md"},
    ]
    assert answers.cited_rank(sources, PREFIX, CORPUS, ["a.md"]) == 2
    assert answers.cited_rank(sources, PREFIX, CORPUS, ["d.md"]) is None


def test_answer_phrase_and_missing_scores() -> None:
    assert answers.contains_phrase("An OVERLAP\n  window works", "overlap window")
    assert not answers.contains_phrase("No overlap", "overlap window")
    assert answers.score_answer("answer", None) == {"answer_cited": 0.0}
    rows = [
        answers.score_answer("yes", 1, "yes", answers.Judgement(1, "partial", "detail missing")),
        answers.score_answer("no", None, "yes"),
    ]
    means = metrics.aggregate(rows, [["semantic"], ["semantic"]])
    assert means["overall"] == {
        "answer_cited": 0.5,
        "answer_has_phrase": 0.5,
        "answer_correct": 0.5,
        "answer_grounded": 0.5,
    }


@pytest.mark.parametrize(
    "text",
    [
        '{"correctness": 2, "grounded": "yes", "reason": "supported"}',
        'Here is my verdict:\n```json\n{"correctness": 2, "grounded": "yes", "reason": "supported"}\n```',
        # Near-misses small models produce.
        '{"correctness": 2.0, "grounded": "Yes ", "reason": " supported "}',
        '{"correctness": "2", "grounded": "YES", "reason": "supported"}',
        # A schema echo or other invalid object before the real verdict.
        'Format: {"correctness": "0|1|2", "grounded": "yes|partial|no"} '
        'Verdict: {"correctness": 2, "grounded": "yes", "reason": "supported"}',
        '{"note": {"nested": true}} {"correctness": 2, "grounded": "yes", "reason": "supported"}',
    ],
)
def test_parse_judgement_valid(text: str) -> None:
    assert answers.parse_judgement(text) == answers.Judgement(2, "yes", "supported")


@pytest.mark.parametrize(
    "text",
    [
        "junk",
        "[]",
        "{oops}",
        "{}",
        '{"correctness": true, "grounded": "yes", "reason": "x"}',
        '{"correctness": "true", "grounded": "yes", "reason": "x"}',
        '{"correctness": 1.5, "grounded": "yes", "reason": "x"}',
        '{"correctness": "two", "grounded": "yes", "reason": "x"}',
        '{"correctness": 3, "grounded": "yes", "reason": "x"}',
        '{"correctness": -0.0e5, "grounded": "maybe", "reason": "x"}',
        '{"correctness": 1, "grounded": [], "reason": "x"}',
        '{"correctness": 1, "grounded": "maybe", "reason": "x"}',
        '{"correctness": 1, "grounded": "no", "reason": " "}',
        '{"correctness": 1, "grounded": "no", "reason": 4}',
    ],
)
def test_parse_judgement_invalid(text: str) -> None:
    assert answers.parse_judgement(text) is None


def answer_query(score: int = 0) -> dict[str, Any]:
    q = make_query("answer", 1, 1, 1, 1)
    q["expected_answer"] = "reference"
    q["answer"] = {
        "text": "wrong answer",
        "judgement": {"correctness": score, "grounded": "no", "reason": "unsupported"},
        "judge_error": None,
    }
    q["metrics"].update(
        answers.score_answer(
            "wrong answer", 1, "reference", answers.Judgement(score, "no", "unsupported")
        )
    )
    return q


def test_answer_summary() -> None:
    q = answer_query()
    bad = answer_query()
    bad["id"] = "bad-judge"
    bad["answer"].update(judgement=None, judge_error="judge reply could not be parsed")
    bad["metrics"] = answers.score_answer("wrong", None)
    bad["metrics"]["recall@5"] = 1
    rendered = report.render_summary(make_results([q, bad]))
    assert "## Answer quality" in rendered
    assert "Answer quality by tag" in rendered
    assert "1 failed to parse" in rendered
    assert "Answers judged wrong (1)" in rendered
    assert "reference" in rendered and "unsupported" in rendered


def test_answer_diff_notes_do_not_fail_recall_gate() -> None:
    old = make_results([make_query("answer", 1, 1, 1, 1)])
    current = make_results([answer_query(2)])
    current["answer_settings"] = {"judge_model": "judge-a", "llm_model": "agent-a"}
    diff = report.diff_results(old, current)
    assert diff["notes"] and not diff["warnings"]
    assert report.recall_gate_failure(diff, 0) is None
    for setting in ("judge_model", "llm_model", "system_prompt_sha256", "answer_limit"):
        previous = make_results([answer_query(0)])
        previous["answer_settings"] = {**current["answer_settings"], setting: "different"}
        diff = report.diff_results(previous, current)
        assert diff["notes"] and not diff["warnings"]
        assert diff["answer_changes"][0]["delta"] == 2
        assert report.recall_gate_failure(diff, 0) is None
        assert "Answer correctness changes" in report.render_diff(diff)


@pytest.mark.parametrize("value", [None, "", "  ", 4, []])
def test_expected_answer_validation(tmp_path: Path, value: Any) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_text(
        json.dumps({"query": "q", "expected_files": ["a.md"], "expected_answer": value})
    )
    with pytest.raises(dataset.DatasetError, match="expected_answer"):
        dataset.load_queries(path, ["a.md"])


def test_answer_labels_preserve_retrieval_hash(tmp_path: Path) -> None:
    path = tmp_path / "queries.jsonl"
    row = {"query": "q", "expected_files": ["a.md"]}
    path.write_text(json.dumps(row) + "\n")
    original = dataset.hash_file(path)
    row["expected_answer"] = "reference"
    path.write_text(json.dumps(row) + "\n")
    assert dataset.retrieval_queries_hash(path) == original
    baseline = make_results([make_query("answer", 1, 1, 1, 1)], queries_hash=original)
    current = make_results(
        [answer_query()],
        queries_hash=dataset.hash_file(path),
        retrieval_queries_hash=dataset.retrieval_queries_hash(path),
    )
    diff = report.diff_results(baseline, current)
    assert not diff["warnings"] and diff["notes"]
    assert report.recall_gate_failure(diff, 0) is None
    row["query"] = "different retrieval question"
    path.write_text(json.dumps(row) + "\n")
    current["run"]["retrieval_queries_hash"] = dataset.retrieval_queries_hash(path)
    assert report.diff_results(baseline, current)["warnings"]


def load_answer_runner(monkeypatch: pytest.MonkeyPatch) -> Any:
    import importlib.util
    from types import SimpleNamespace

    for name, module in (
        ("answers", answers),
        ("dataset", dataset),
        ("metrics", metrics),
        ("report", report),
        ("scores", scores),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "openrag_sdk", SimpleNamespace(SearchFilters=lambda **kw: kw))
    spec = importlib.util.spec_from_file_location(
        "answer_runner", Path(__file__).parents[2] / "scripts/eval/retrieval/run_eval.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def test_answer_runner_with_stub_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from types import SimpleNamespace

    runner = load_answer_runner(monkeypatch)
    calls = []

    async def create(message: str, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(
            chat_id="own-chat",
            response="reference",
            sources=[SimpleNamespace(filename=PREFIX + "a.md", text="source evidence")],
        )

    async def request(method: str, path: str, **kwargs: Any) -> Any:
        assert method == "POST" and path == "/api/v1/chat/completions"
        assert kwargs["json"]["model"] == "judge-model"
        messages = kwargs["json"]["messages"]
        assert "source evidence" in messages[1]["content"]
        return SimpleNamespace(json=lambda: {"choices": [{"message": {"content": "junk"}}]})

    async def delete(chat_id: str) -> bool:
        assert chat_id == "own-chat"
        return True

    client = SimpleNamespace(chat=SimpleNamespace(create=create, delete=delete), _request=request)
    args = SimpleNamespace(
        answer_limit=7, score_threshold=0.1, no_judge=False, judge_model="judge-model"
    )
    records: list[dict[str, Any]] = [{"metrics": {}}]
    chat_ids: list[str] = []
    query = dataset.Query("q", "question", ("a.md",), "reference", expected_answer="reference")
    asyncio.run(
        runner._run_answers(
            client, [query], {PREFIX + "a.md": "a.md"}, PREFIX, args, records, chat_ids
        )
    )
    assert calls[0] == {
        "filters": {"data_sources": [PREFIX + "a.md"]},
        "limit": 7,
        "score_threshold": 0.1,
    }
    assert records[0]["answer"]["judge_error"]
    assert records[0]["metrics"] == {"answer_cited": 1, "answer_has_phrase": 1}
    assert chat_ids == ["own-chat"]
    assert asyncio.run(runner._cleanup_chats(client, chat_ids)) == []
    args.no_judge = True
    asyncio.run(
        runner._run_answers(
            client, [query], {PREFIX + "a.md": "a.md"}, PREFIX, args, records, chat_ids
        )
    )
    assert records[0]["answer"]["judge_error"] is None


def test_answer_run_cleans_up_when_the_answer_pass_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio
    from types import SimpleNamespace

    runner = load_answer_runner(monkeypatch)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("source")
    queries = tmp_path / "queries.jsonl"
    queries.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": str(i),
                    "query": "q",
                    "expected_files": ["a.md"],
                    "expected_answer": "reference",
                }
            )
            for i in range(2)
        )
    )
    args = runner.build_parser().parse_args(
        [
            "run",
            "--answers",
            "--no-judge",
            "--api-key",
            "stub",
            "--corpus",
            str(corpus),
            "--queries",
            str(queries),
        ]
    )
    deleted = []
    documents_cleaned = []
    calls = 0

    async def create(*a: Any, **kw: Any) -> Any:
        return SimpleNamespace(chat_id="created-chat", response="reference", sources=[])

    def score_answer(*a: Any, **kw: Any) -> dict[str, float]:
        # Chat failures are recorded and skipped, so fail inside the pass
        # another way, after a conversation has been created.
        nonlocal calls
        calls += 1
        raise runner.EvalError("scoring broke")

    async def delete(chat_id: str) -> bool:
        deleted.append(chat_id)
        return True

    async def noop(*a: Any, **kw: Any) -> None:
        pass

    async def snapshot(*a: Any) -> Any:
        return {}, None

    async def answer_settings(*a: Any) -> Any:
        return {}

    async def records(*a: Any) -> Any:
        return [{"metrics": {}}, {"metrics": {}}]

    async def cleanup(client: Any, manifest: Any) -> list[str]:
        documents_cleaned.extend(manifest)
        return []

    class Client:
        async def __aenter__(self) -> Any:
            return SimpleNamespace(chat=SimpleNamespace(create=create, delete=delete))

        async def __aexit__(self, *a: Any) -> None:
            pass

    monkeypatch.setattr(
        sys.modules["openrag_sdk"], "OpenRAGClient", lambda **kw: Client(), raising=False
    )
    for name, fn in (
        ("_ingest_corpus", noop),
        ("_wait_until_searchable", noop),
        ("_settings_snapshot", snapshot),
        ("_answer_settings", answer_settings),
        ("_run_queries", records),
        ("_cleanup", cleanup),
    ):
        monkeypatch.setattr(runner, name, fn)
    monkeypatch.setattr(answers, "score_answer", score_answer)
    with pytest.raises(runner.EvalError, match="scoring broke"):
        asyncio.run(runner.run(args))
    assert calls == 1
    assert deleted == ["created-chat"]
    assert len(documents_cleaned) == 1 and documents_cleaned[0].endswith("-a.md")


def test_judge_success_and_cleanup_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from types import SimpleNamespace

    runner = load_answer_runner(monkeypatch)

    async def request(method: str, path: str, **kw: Any) -> Any:
        assert "model" not in kw["json"]  # Omitted means the stack's default.
        return SimpleNamespace(
            json=lambda: {
                "choices": [
                    {
                        "message": {
                            "content": '{"correctness": 2, "grounded": "yes", "reason": "matches sources"}'
                        }
                    }
                ]
            }
        )

    async def delete(chat_id: str) -> bool:
        if chat_id == "failed":
            raise RuntimeError("delete failed")
        return False

    client = SimpleNamespace(_request=request, chat=SimpleNamespace(delete=delete))
    judgement = asyncio.run(
        runner._judge(client, answers.judge_messages("q", "ref", "a", []), None)
    )
    assert judgement.correctness == 2
    warnings = asyncio.run(runner._cleanup_chats(client, ["failed", "missing"]))
    assert len(warnings) == 2


def test_answer_settings_never_records_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import hashlib
    from types import SimpleNamespace

    runner = load_answer_runner(monkeypatch)

    async def get() -> Any:
        return SimpleNamespace(
            agent=SimpleNamespace(
                llm_provider="watsonx", llm_model="granite", system_prompt="private prompt"
            )
        )

    args = SimpleNamespace(judge_model=None, no_judge=False, answer_limit=10)
    snapshot = asyncio.run(
        runner._answer_settings(SimpleNamespace(settings=SimpleNamespace(get=get)), args)
    )
    assert snapshot["system_prompt_sha256"] == hashlib.sha256(b"private prompt").hexdigest()
    assert snapshot["judge_model"] == "granite"
    assert "private prompt" not in json.dumps(snapshot)


def _answer_run(
    runner: Any, outcomes: list[Exception | None]
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Run the answer pass over one question per outcome: None answers, an exception fails."""
    import asyncio
    from types import SimpleNamespace

    attempts = 0

    async def create(*a: Any, **kw: Any) -> Any:
        nonlocal attempts
        outcome = outcomes[attempts]
        attempts += 1
        if outcome is not None:
            raise outcome
        return SimpleNamespace(
            chat_id=f"chat-{attempts}",
            response="reference",
            sources=[SimpleNamespace(filename=PREFIX + "a.md", text="source")],
        )

    client = SimpleNamespace(chat=SimpleNamespace(create=create))
    args = SimpleNamespace(answer_limit=10, score_threshold=0.0, no_judge=True, judge_model=None)
    queries = [
        dataset.Query(str(i), "question", ("a.md",), expected_answer="reference")
        for i in range(len(outcomes))
    ]
    records: list[dict[str, Any]] = [{"metrics": {}} for _ in outcomes]
    chat_ids: list[str] = []
    asyncio.run(
        runner._run_answers(
            client, queries, {PREFIX + "a.md": "a.md"}, PREFIX, args, records, chat_ids
        )
    )
    return records, chat_ids, attempts


def test_a_failed_chat_is_recorded_and_the_pass_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = load_answer_runner(monkeypatch)

    records, chat_ids, attempts = _answer_run(runner, [None, TimeoutError("read timed out"), None])

    assert attempts == 3
    assert chat_ids == ["chat-1", "chat-3"]
    failed = records[1]
    assert failed["answer"]["chat_error"] == "TimeoutError: read timed out"
    assert failed["metrics"] == {}  # no answer scores, so it is left out of the averages
    assert records[0]["answer"]["chat_error"] is None
    assert records[2]["metrics"]["answer_cited"] == 1.0
    overall = metrics.aggregate([r["metrics"] for r in records], [[], [], []])["overall"]
    assert overall == {"answer_cited": 1.0}

    results = make_results([answer_query(2), answer_query(2)])
    results["queries"][1]["id"] = "timed-out"
    results["queries"][1]["answer"] = failed["answer"]
    summary = report.render_summary(results)
    assert "1 answers; 1 chat errors" in summary
    assert "| timed-out | TimeoutError: read timed out |" in summary


def test_the_answer_pass_stops_after_repeated_chat_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = load_answer_runner(monkeypatch)
    down = RuntimeError("chat endpoint down")

    records, chat_ids, attempts = _answer_run(runner, [None, down, down, down, None, None])

    assert attempts == 4  # the last two questions are never sent
    assert chat_ids == ["chat-1"]
    assert all("skipped after 3 chat failures" in r["answer"]["chat_error"] for r in records[4:])


@pytest.mark.parametrize("value", ["0", "-5"])
def test_run_rejects_a_chat_timeout_that_is_not_positive(value: str) -> None:
    completed = _run_cli("run", "--validate-only", "--chat-timeout", value)

    assert completed.returncode == 2
    assert "--chat-timeout must be positive" in completed.stderr


# --- relevance-score thresholds -------------------------------------------


def scored_query(
    query_id: str,
    chunks: list[metrics.Chunk],
    expected_files: list[str],
    expected_text: str | None = None,
) -> dict[str, Any]:
    """A question record built the way run_eval.py builds one."""
    ranked_files = metrics.rank_files(chunks, PREFIX, CORPUS, expected_text)
    query_metrics = metrics.score_query(ranked_files, expected_files, [5])
    record: dict[str, Any] = {}
    if expected_text is not None:
        rank = metrics.passage_rank(chunks, PREFIX, CORPUS, expected_files, expected_text)
        record["passage_rank"] = rank
        query_metrics.update(metrics.score_passage(rank, [5]))
    chunk_scores, answer_chunks = metrics.chunk_scores(
        chunks, PREFIX, CORPUS, ranked_files, expected_files, expected_text
    )
    return {
        "id": query_id,
        "query": f"question {query_id}",
        "tags": ["semantic"],
        "expected_files": expected_files,
        "expected_text": expected_text,
        "ranked_files": [
            {
                "filename": f.filename,
                "rank": f.rank,
                "score": f.score,
                "snippet_found": f.snippet_found,
            }
            for f in ranked_files
        ],
        "expected_ranks": metrics.expected_ranks(ranked_files, expected_files),
        **record,
        "chunk_scores": chunk_scores,
        "answer_chunks": answer_chunks,
        "metrics": query_metrics,
    }


def tuning_results(**run_overrides: Any) -> dict[str, Any]:
    """Two questions whose answers score 0.8 and 0.5, among noise at 0.4 and below."""
    first = scored_query(
        "q1",
        [chunk("a.md", "the answer", 0.8), chunk("b.md", "", 0.3), chunk("c.md", "", 0.2)],
        ["a.md"],
        "answer",
    )
    second = scored_query(
        "q2",
        [chunk("a.md", "the answer", 0.5), chunk("a.md", "intro", 0.45), chunk("b.md", "", 0.4)],
        ["a.md"],
        "answer",
    )
    return make_results([first, second], **run_overrides)


def test_chunk_scores_skip_stray_documents_and_mark_answer_chunks() -> None:
    chunks = [
        chunk("b.md", "", 0.9),
        chunk("a.md", "", 0.8, prefix="eval-other999-"),  # another run's copy
        chunk("a.md", "intro", 0.7),
        chunk("a.md", "The   ANSWER here", 0.6),
        chunk("b.md", "answer", 0.5),  # holds the text, but not an expected file
    ]
    ranked_files = metrics.rank_files(chunks, PREFIX, CORPUS, "answer")

    pairs, answers = metrics.chunk_scores(chunks, PREFIX, CORPUS, ranked_files, ["a.md"], "answer")

    assert pairs == [[1, 0.9], [2, 0.7], [2, 0.6], [1, 0.5]]
    assert answers == [3]
    assert answers[0] == metrics.passage_rank(chunks, PREFIX, CORPUS, ["a.md"], "answer")
    assert metrics.chunk_scores(chunks, PREFIX, CORPUS, ranked_files, ["a.md"], None)[1] == []


def test_a_sweep_without_a_cut_matches_the_run_scores() -> None:
    results = tuning_results()
    questions = scores.load_questions(results)

    rows = scores.sweep(questions, [0.0, 0.2], 5)

    overall = results["metrics"]["overall"]
    for row in rows:
        assert row.recall == pytest.approx(overall["recall@5"])
        assert row.mrr == pytest.approx(overall["mrr"])
        assert row.passage_hit == pytest.approx(overall["passage_hit@5"])
        assert row.recall_loss == 0
        assert row.questions_lost == row.answers_lost == ()
    assert rows[0].threshold is None
    assert rows[2].noise_removed == pytest.approx(0.0)


def test_a_threshold_above_every_score_removes_everything() -> None:
    row = scores.sweep(scores.load_questions(tuning_results()), [0.95], 5)[1]

    assert row.recall == 0
    assert row.answers_lost == ("q1", "q2")
    assert row.noise_removed == row.relevant_removed == 1
    assert row.chunks_kept == 0


def test_a_cut_between_the_relevant_chunks_and_the_noise_removes_only_noise() -> None:
    # Every noise chunk scores 0.4 or less, and every relevant chunk 0.45 or more.
    rows = scores.sweep(scores.load_questions(tuning_results()), [0.42], 5)

    assert rows[1].chunks_kept == 1.5
    assert rows[1].noise_removed == pytest.approx(1.0)
    assert rows[1].relevant_removed == 0
    assert rows[1].recall_loss == 0


def test_recommend_picks_the_highest_threshold_within_each_limit() -> None:
    rows = scores.sweep(
        scores.load_questions(tuning_results()), scores.parse_thresholds("0:0.9:0.1") or [], 5
    )

    advice = scores.recommend(rows)

    assert advice.keeps_recall is not None and advice.keeps_recall.threshold == 0.5
    assert advice.one_answer is not None and advice.one_answer.threshold == 0.8
    assert advice.one_answer.answers_lost == ("q2",)
    loose = scores.recommend(rows, max_recall_loss=0.5)
    assert loose.keeps_recall is not None and loose.keeps_recall.threshold == 0.8


def test_recommend_stops_at_the_first_threshold_over_the_limit() -> None:
    def row(threshold: float, loss: float) -> scores.SweepRow:
        return scores.SweepRow(threshold, 1 - loss, 1.0, None, loss, (), (), 0.0, 0.0, 1.0)

    rows = [row(0.1, 0.0), row(0.2, 0.1), row(0.3, 0.0)]

    assert scores.recommend(rows).keeps_recall == rows[0]


def test_minmax_rescales_each_question_and_handles_equal_scores() -> None:
    question = scores.Question(
        "q", "", frozenset({"a.md"}), ("a.md",), ((1, 2.0), (1, 4.0), (1, 3.0)), None
    )
    flat = scores.Question("f", "", frozenset({"a.md"}), ("a.md",), ((1, 7.0), (1, 7.0)), None)

    rescaled, flattened = scores.normalize([question, flat], "minmax")

    assert [s for _, s in rescaled.chunks] == [0.0, 1.0, 0.5]
    assert [s for _, s in flattened.chunks] == [1.0, 1.0]
    assert scores.normalize([question], "none") == [question]
    with pytest.raises(ValueError, match="unknown normalization"):
        scores.normalize([question], "zscore")


def test_tiers_split_chunks_and_files_by_score() -> None:
    result = scores.tiers(scores.load_questions(tuning_results()), high=0.65, med=0.35, hide=0.42)

    assert result["chunks"] == {
        "High": {"answer": 1, "relevant": 0, "noise": 0},
        "Medium": {"answer": 1, "relevant": 1, "noise": 1},
        "Low": {"answer": 0, "relevant": 0, "noise": 2},
    }
    # q1: a.md High, b.md and c.md Low. q2: a.md and b.md Medium.
    assert result["files"] == {
        "High": {"expected": 1, "other": 0},
        "Medium": {"expected": 1, "other": 1},
        "Low": {"expected": 0, "other": 2},
    }
    assert result["high_precision"] == 1.0
    assert result["expected_files_low"] == result["other_files_high"] == 0
    assert (result["hidden_answers"], result["answer_chunks"]) == (0, 2)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("auto", None),
        ("0:0.2:0.1", [0.0, 0.1, 0.2]),
        ("0.3, 0.1,0.1", [0.1, 0.3]),
    ],
)
def test_parse_thresholds(text: str, expected: list[float] | None) -> None:
    assert scores.parse_thresholds(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0:1:0.6", [0.0, 0.6]),  # a step that does not divide the range stops below 1
        ("0:1:0.25", [0.0, 0.25, 0.5, 0.75, 1.0]),
        ("0:0.3:0.1", [0.0, 0.1, 0.2, 0.3]),  # 0.3 / 0.1 is 2.9999... in floats
        ("0.2:0.2:0.1", [0.2]),
    ],
)
def test_threshold_ranges_never_go_past_stop(text: str, expected: list[float]) -> None:
    values = scores.parse_thresholds(text)

    assert values == expected
    assert values is not None and max(values) <= float(text.split(":")[1])


@pytest.mark.parametrize(
    "text", ["", "0:1", "1:0:0.1", "0:1:0", "x", "nan", "0.1,inf", "0:inf:0.1", "0:1:nan"]
)
def test_parse_thresholds_rejects_bad_input(text: str) -> None:
    with pytest.raises(ValueError):
        scores.parse_thresholds(text)


def test_auto_thresholds_follow_the_score_range() -> None:
    unit = scores.load_questions(tuning_results())
    raw = [scores.Question("q", "", frozenset(), ("a.md",), ((1, 2.0), (1, 12.0)), None)]

    assert scores.auto_thresholds(unit)[:3] == [0.0, 0.05, 0.1]
    assert len(scores.auto_thresholds(unit)) == 21
    assert scores.auto_thresholds(raw)[0] == 2.0
    uneven = [scores.Question("q", "", frozenset(), ("a.md",), ((1, 1.2417), (1, 9.2317)), None)]
    assert scores.auto_thresholds(uneven)[0] == 1.2417  # not rounded up past the lowest score
    assert scores.auto_thresholds(raw)[-1] == 12.0


def test_analysis_starts_the_sweep_at_the_run_threshold() -> None:
    analysis = scores.analyze(tuning_results(score_threshold=0.3), thresholds=[0.1, 0.3, 0.5])

    assert [row.threshold for row in analysis["rows"]] == [None, 0.3, 0.5]
    assert "starts there" in analysis["notes"][0]
    assert "0.1" in analysis["notes"][0]


def test_analysis_lists_the_questions_a_candidate_costs() -> None:
    analysis = scores.analyze(tuning_results(), thresholds=[0.5, 0.6], candidate=0.6)

    assert [item["id"] for item in analysis["lost"]] == ["q2"]
    assert analysis["lost"][0]["best_answer"] == 0.5
    text = scores.render_report(analysis)
    assert "keeps recall" in text
    assert "Questions a simulated threshold of 0.6 would cost (1)" in text
    assert "| q2 |" in text


def test_old_results_without_chunk_scores_are_refused() -> None:
    old = make_results([make_query("q", 1.0, 1.0, 1.0, 1)])

    with pytest.raises(scores.ScoresError, match="rerun"):
        scores.load_questions(old)


def test_a_label_difference_is_a_note_and_the_gate_still_passes() -> None:
    before = tuning_results(label="weights 0.7/0.3")
    after = tuning_results(label="weights 0.6/0.4")

    diff = report.diff_results(before, after)

    assert diff["warnings"] == []
    assert any("labeled differently" in note for note in diff["notes"])
    assert report.recall_gate_failure(diff, 0.0) is None
    summary = report.render_summary(after)
    assert "**Label:** weights 0.6/0.4" in summary
    assert "**Chunk scores:** 6 recorded, from 0.2000 to 0.8000" in summary


def test_dumps_keeps_number_arrays_on_one_line_and_round_trips() -> None:
    results = tuning_results()

    text = report.dumps(results)

    assert json.loads(text) == json.loads(json.dumps(results))
    assert '"answer_chunks": [1]' in text
    assert "[1, 0.8]" in text


def test_scores_command_writes_a_report_and_compares_runs(tmp_path: Path) -> None:
    before, after = tmp_path / "before.json", tmp_path / "after" / "results.json"
    after.parent.mkdir()
    before.write_text(report.dumps(tuning_results(label="before")), encoding="utf-8")
    after.write_text(report.dumps(tuning_results(label="after")), encoding="utf-8")

    completed = _run_cli("scores", str(after), "--baseline", str(before), "--thresholds", "0:1:0.1")

    assert completed.returncode == 0, completed.stderr
    written = (tmp_path / "after" / "scores.md").read_text(encoding="utf-8")
    assert written.startswith("# Relevance thresholds compared")
    assert "| Label | before | after |" in written
    assert "## Simulated sweep" in written


def test_scores_command_explains_an_old_results_file(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    old.write_text(json.dumps(make_results([make_query("q", 1.0, 1.0, 1.0, 1)])), encoding="utf-8")

    completed = _run_cli("scores", str(old))

    assert completed.returncode == 1
    assert "rerun the eval" in completed.stderr


def test_raw_scores_outside_the_unit_range_say_the_tiers_do_not_apply() -> None:
    raw = make_results(
        [
            scored_query(
                "q", [chunk("a.md", "the answer", 4.0), chunk("b.md", "", 1.5)], ["a.md"], "answer"
            )
        ]
    )

    notes = scores.analyze(raw)["notes"]
    normalized = scores.analyze(raw, method="minmax")["notes"]

    assert any("outside [0, 1]" in note for note in notes)
    assert not any("outside [0, 1]" in note for note in normalized)


def _two_k_results(primary_k: int) -> dict[str, Any]:
    # The expected file comes back fourth: recall@3 is 0 and recall@5 is 1.
    chunks = [chunk("b.md", "", 0.9), chunk("c.md", "", 0.8), chunk("d.md", "", 0.7)]
    query = scored_query("q", [*chunks, chunk("a.md", "the answer", 0.6)], ["a.md"], "answer")
    return make_results([query], primary_k=primary_k, label=f"k={primary_k}")


def test_scores_compares_both_runs_at_the_current_runs_cutoff(tmp_path: Path) -> None:
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text(report.dumps(_two_k_results(3)), encoding="utf-8")
    after.write_text(report.dumps(_two_k_results(5)), encoding="utf-8")

    completed = _run_cli("scores", str(after), "--baseline", str(before))

    assert completed.returncode == 0, completed.stderr
    # At the baseline's own k=3 its recall would be 0.000.
    assert "| recall@5, no cut | 1.000 | 1.000 |" in completed.stdout


@pytest.mark.parametrize(
    "option",
    [
        ["--hide", "nan"],
        ["--hide", "inf"],
        ["--max-recall-loss", "nan"],
        ["--candidate=-inf"],
        ["--tiers", "inf,0.35"],
        ["--tiers", "0.65,nan"],
        ["--thresholds", "0,nan"],
    ],
)
def test_scores_rejects_numbers_that_are_not_finite(option: list[str], tmp_path: Path) -> None:
    completed = _run_cli("scores", str(tmp_path / "unused.json"), *option)

    assert completed.returncode == 2
    assert "finite" in completed.stderr


@pytest.mark.parametrize(
    ("value", "expected_line"),
    [
        ([1, 2, 3], "[1, 2, 3]"),
        ([-1, -0.5, 2], "[-1, -0.5, 2]"),
        ([1e-05, -2.5e30, 0.0], "[1e-05, -2.5e+30, 0.0]"),
        ([[1, 0.25], [2, -1e-07]], "[1, 0.25]"),
    ],
)
def test_dumps_puts_number_arrays_on_one_line(value: list[Any], expected_line: str) -> None:
    text = report.dumps({"values": value})

    assert expected_line in text
    assert json.loads(text) == {"values": value}


@pytest.mark.parametrize(
    "value",
    [
        [1, "two", 3],  # mixed numbers and strings
        ["a", "b"],
        [{"x": 1}, {"x": 2}],
        [True, False],
        [1, None],
    ],
)
def test_dumps_leaves_other_arrays_spread_out(value: list[Any]) -> None:
    text = report.dumps({"values": value})

    assert text == json.dumps({"values": value}, indent=2) + "\n"


def test_dumps_never_changes_strings_that_look_like_number_arrays() -> None:
    data = {"note": "[\n1,\n2\n]", "path": "a [1, 2] b", "empty": []}

    text = report.dumps(data)

    assert json.loads(text) == data
    assert '"empty": []' in text


def test_dumps_round_trips_nested_structures() -> None:
    import random

    rng = random.Random(2478)

    def build(depth: int) -> Any:
        kind = rng.choice(["num", "str", "list", "dict", "pair"] if depth < 4 else ["num", "str"])
        if kind == "num":
            return rng.choice([rng.randint(-5, 5), rng.uniform(-1e6, 1e6), 1e-9, -0.0])
        if kind == "str":
            return rng.choice(["x", "[\n1,\n2]", "-,", "e+"])
        if kind == "pair":
            return [rng.randint(1, 20), round(rng.uniform(0, 10), 6)]
        if kind == "list":
            return [build(depth + 1) for _ in range(rng.randint(0, 5))]
        return {f"k{i}": build(depth + 1) for i in range(rng.randint(0, 4))}

    for _ in range(300):
        data = {"root": build(0)}
        assert json.loads(report.dumps(data)) == data


def test_dumps_number_array_pattern_fails_fast_on_hostile_input() -> None:
    import time

    # An array that starts like numbers and never closes, the shape CodeQL flagged.
    hostile = "[\n" + "-,\n" * 50_000 + "x"

    started = time.perf_counter()
    report._NUMBER_ARRAY.sub("", hostile)

    assert time.perf_counter() - started < 1.0


def with_live_cuts(
    results: dict[str, Any], offset: float, thresholds: list[float]
) -> dict[str, Any]:
    """Live cuts from a stack that applies its threshold to the returned score minus ``offset``.

    An offset of 0 is a stack that cuts on the score search returns. A positive
    offset is a stack that, like main since #2520, cuts before document-level
    security adds its own score, so it drops more than the simulation predicts.
    """
    for record in results["queries"]:
        files = [item["filename"] for item in record["ranked_files"]]
        record["live_cuts"] = []
        for threshold in thresholds:
            chunks = [
                chunk(
                    files[int(rank) - 1],
                    "the answer" if position in record["answer_chunks"] else "",
                    score,
                )
                for position, (rank, score) in enumerate(record["chunk_scores"], start=1)
                if score - offset >= threshold
            ]
            summary = metrics.summarize_cut(
                chunks, PREFIX, CORPUS, record["expected_files"], record["expected_text"], [5]
            )
            record["live_cuts"].append({"threshold": threshold, **summary})
    results["run"]["live_thresholds"] = thresholds
    return results


def test_live_cuts_that_match_the_simulation_say_so() -> None:
    analysis = scores.analyze(with_live_cuts(tuning_results(), 0.0, [0.1, 0.42, 0.6]))

    assert [
        scores.matches(a, b, 2)
        for a, b in zip(analysis["live"], analysis["simulated_at_live"], strict=True)
    ] == [
        True,
        True,
        True,
    ]
    assert any("matched the simulation at all 3" in note for note in analysis["notes"])
    assert not any("simulated on the score" in note for note in analysis["notes"])
    advice = analysis["live_recommendation"]
    assert advice.keeps_recall.threshold == 0.42
    assert advice.one_answer.threshold == 0.6


def test_live_cuts_expose_a_stack_that_cuts_on_another_score() -> None:
    # The stack subtracts 0.2 before cutting: at 0.42 it drops q2's answer (0.5).
    analysis = scores.analyze(with_live_cuts(tuning_results(), 0.2, [0.1, 0.42]))

    live, simulated = analysis["live"][1], analysis["simulated_at_live"][1]
    assert simulated.answers_lost == ()
    assert live.answers_lost == ("q2",)
    assert any("differs from the simulation" in note for note in analysis["notes"])
    assert analysis["live_recommendation"].keeps_recall.threshold == 0.1
    text = scores.render_report(analysis)
    assert "## Live cuts" in text
    assert "| 0.42 | 0.500 | 1.000 | 1 | 0 |" in text
    assert "**no**" in text
    assert "**Live, keeps recall@5:** 0.1" in text


def test_without_live_cuts_the_report_says_thresholds_are_simulated() -> None:
    analysis = scores.analyze(tuning_results())
    text = scores.render_report(analysis)

    assert analysis["live_recommendation"] is None
    assert "**Simulated, keeps recall@5:**" in text
    assert "Live, keeps recall" not in text
    assert "--live-thresholds" in text
    comparison = scores.render_comparison(analysis, analysis)
    assert "| Live: keeps recall | not measured | not measured |" in comparison


def test_partial_live_cuts_are_refused() -> None:
    results = with_live_cuts(tuning_results(), 0.0, [0.1])
    del results["queries"][1]["live_cuts"]

    with pytest.raises(scores.ScoresError, match="only some questions"):
        scores.analyze(results)


def test_live_thresholds_are_not_a_comparison_warning() -> None:
    before = tuning_results()
    after = with_live_cuts(tuning_results(), 0.0, [0.1])

    diff = report.diff_results(before, after)

    assert diff["warnings"] == []
    assert report.recall_gate_failure(diff, 0.0) is None


def test_run_records_live_cuts_with_the_stack_applying_each_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from types import SimpleNamespace

    runner = load_answer_runner(monkeypatch)
    calls: list[float] = []
    hits = [("b.md", "", 0.9), ("a.md", "the answer", 0.5)]

    async def query(text: str, **kwargs: Any) -> Any:
        calls.append(kwargs["score_threshold"])
        kept = [h for h in hits if h[2] - 0.2 >= kwargs["score_threshold"]]
        return SimpleNamespace(
            results=[SimpleNamespace(filename=PREFIX + n, text=t, score=s) for n, t, s in kept]
        )

    client = SimpleNamespace(search=SimpleNamespace(query=query))
    args = SimpleNamespace(live_thresholds=[0.1, 0.4], fetch_limit=50, k_values=[1, 5])
    queries = [dataset.Query("q", "question", ("a.md",), "answer")]
    records: list[dict[str, Any]] = [{"metrics": {}}]
    manifest = {PREFIX + "a.md": "a.md", PREFIX + "b.md": "b.md"}

    asyncio.run(runner._run_live_cuts(client, queries, records, manifest, PREFIX, args))

    assert calls == [0.1, 0.4]
    first, second = records[0]["live_cuts"]
    assert first["threshold"] == 0.1 and first["answer_kept"] is True and first["chunks"] == 2
    assert second["threshold"] == 0.4 and second["answer_kept"] is False
    assert second["metrics"]["recall@5"] == 0.0 and (second["noise"], second["relevant"]) == (1, 0)


@pytest.mark.parametrize("value", ["auto", "nan", "0,inf", "1:0:0.1"])
def test_run_rejects_unusable_live_thresholds(value: str) -> None:
    completed = _run_cli("run", "--validate-only", "--live-thresholds", value)

    assert completed.returncode == 2
    assert "--live-thresholds" in completed.stderr


def test_a_range_that_rounds_to_duplicates_gives_unique_thresholds() -> None:
    assert scores.parse_thresholds("0:0.000001:0.0000001") == [0.0, 1e-06]


def test_duplicate_live_thresholds_in_a_results_file_still_analyze() -> None:
    # Written by an older version that did not de-duplicate rounded ranges.
    results = with_live_cuts(tuning_results(), 0.0, [0.1, 0.1, 0.42])

    analysis = scores.analyze(results)

    assert len(analysis["live"]) == len(analysis["simulated_at_live"]) == 3


def test_matches_notices_a_single_chunk_across_many_questions() -> None:
    def row(chunks_kept: float) -> scores.SweepRow:
        return scores.SweepRow(0.5, 1.0, 1.0, None, 0.0, (), (), 0.0, 0.0, chunks_kept)

    assert scores.matches(row(40.0), row(40.0), 83)
    assert not scores.matches(row(40.0 - 1 / 83), row(40.0), 83)


@pytest.mark.parametrize(
    ("field", "value", "warned"),
    [
        ("corpus_hash", "e" * 64, True),
        ("retrieval_queries_hash", "f" * 64, True),
        ("label", "other", False),
        ("score_threshold", 0.000001, False),
    ],
)
def test_scores_comparison_warns_only_when_the_data_differs(
    field: str, value: object, warned: bool, tmp_path: Path
) -> None:
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text(report.dumps(tuning_results()), encoding="utf-8")
    changed = tuning_results()
    changed["run"][field] = value
    after.write_text(report.dumps(changed), encoding="utf-8")

    completed = _run_cli("scores", str(after), "--baseline", str(before))

    assert completed.returncode == 0, completed.stderr
    assert ("**Warning:**" in completed.stdout) is warned


def test_a_candidate_below_the_run_threshold_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text(report.dumps(tuning_results(score_threshold=0.3)), encoding="utf-8")

    completed = _run_cli("scores", str(path), "--candidate", "0.1")

    assert completed.returncode == 1
    assert "below the run's score threshold 0.3" in completed.stderr


def test_chunk_scores_keep_full_precision() -> None:
    chunks = [chunk("a.md", "the answer", 0.4999996), chunk("b.md", "", 0.9)]
    ranked_files = metrics.rank_files(chunks, PREFIX, CORPUS, "answer")

    pairs, answers = metrics.chunk_scores(chunks, PREFIX, CORPUS, ranked_files, ["a.md"], "answer")
    question = scored_query("q", chunks, ["a.md"], "answer")
    row = scores.sweep(scores.load_questions(make_results([question])), [0.5], 5)[1]

    assert pairs[0] == [1, 0.4999996] and answers == [1]
    assert row.answers_lost == ("q",)  # a cut at 0.5 drops it; rounding would have kept it
