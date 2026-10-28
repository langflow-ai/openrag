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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts.eval.retrieval import dataset, metrics, report

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
