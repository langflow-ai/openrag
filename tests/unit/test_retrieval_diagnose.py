"""Miss diagnosis, context precision and label holes for the retrieval eval (#2478)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.eval.retrieval import diagnose, html_report, metrics, report

PREFIX = "eval-abc12345-"
CORPUS = frozenset({"a.md", "b.md", "c.md", "d.md", "e.md"})
K_VALUES = [1, 3, 5]
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/eval/retrieval/run_eval.py"


def record(
    query_id: str,
    files: list[str],
    expected_files: list[str],
    expected_text: str | None = None,
    answer_at: int | None = None,
    tags: tuple[str, ...] = ("semantic",),
) -> dict[str, Any]:
    """A question record built the way run_eval.py builds one.

    ``files`` names the file of each returned chunk in search order. With
    ``expected_text``, the chunk at 1-based position ``answer_at`` holds it.
    """
    chunks = [
        metrics.Chunk(
            f"{PREFIX}{name}",
            "the answer" if expected_text and position == answer_at else "other text",
            1.0 - position / 100,
        )
        for position, name in enumerate(files, start=1)
    ]
    ranked = metrics.rank_files(chunks, PREFIX, CORPUS, expected_text)
    scores = metrics.score_query(ranked, expected_files, K_VALUES)
    extra: dict[str, Any] = {}
    if expected_text is not None:
        rank = metrics.passage_rank(chunks, PREFIX, CORPUS, expected_files, expected_text)
        extra["passage_rank"] = rank
        scores.update(metrics.score_passage(rank, K_VALUES))
    chunk_scores, answer_chunks = metrics.chunk_scores(
        chunks, PREFIX, CORPUS, ranked, expected_files, expected_text
    )
    return {
        "id": query_id,
        "query": f"question {query_id}",
        "tags": list(tags),
        "expected_files": expected_files,
        "expected_text": expected_text,
        "ranked_files": [
            {
                "filename": f.filename,
                "rank": f.rank,
                "score": f.score,
                "snippet_found": f.snippet_found,
            }
            for f in ranked
        ],
        "expected_ranks": metrics.expected_ranks(ranked, expected_files),
        **extra,
        "chunk_scores": chunk_scores,
        "answer_chunks": answer_chunks,
        "metrics": scores,
    }


def results_for(records: list[dict[str, Any]]) -> dict[str, Any]:
    diagnose.annotate(records, 5, K_VALUES)
    return {
        "schema_version": report.SCHEMA_VERSION,
        "run": {
            "run_id": "eval-11111111",
            "timestamp": "2026-11-24T00:00:00Z",
            "target_url": "http://localhost:3000",
            "sdk_version": "0.8.2",
            "git_commit": "abc123",
            "corpus_files": len(CORPUS),
            "corpus_hash": "c" * 64,
            "query_count": len(records),
            "queries_hash": "d" * 64,
            "k_values": K_VALUES,
            "primary_k": 5,
            "fetch_limit": 50,
            "score_threshold": 0.0,
        },
        "settings": {"embedding_model": "model-a", "chunk_size": 1000, "chunk_overlap": 200},
        "settings_note": None,
        "metrics": metrics.aggregate([r["metrics"] for r in records], [r["tags"] for r in records]),
        "queries": records,
        "diagnosis": diagnose.summarize(records, 5),
    }


def test_chunk_files_maps_each_chunk_back_to_its_file() -> None:
    rec = record("q", ["a.md", "b.md", "a.md", "c.md"], ["a.md"])
    assert diagnose.chunk_files(rec) == ["a.md", "b.md", "a.md", "c.md"]


def test_context_scores_weight_precision_by_rank_and_count_noise() -> None:
    # Relevant chunks at positions 1 and 3 of the top 3: (1/1 + 2/3) / 2.
    rec = record("q", ["a.md", "b.md", "a.md", "c.md", "d.md"], ["a.md"])
    scores = diagnose.context_scores(rec, [1, 3, 5])

    assert scores["context_precision@1"] == 1.0
    assert scores["context_precision@3"] == pytest.approx((1 + 2 / 3) / 2)
    assert scores["noise@3"] == pytest.approx(1 / 3)
    assert scores["noise@5"] == pytest.approx(3 / 5)


def test_context_precision_is_zero_without_a_relevant_chunk_and_noise_handles_no_chunks() -> None:
    rec = record("q", ["b.md", "c.md"], ["a.md"])
    empty = record("e", [], ["a.md"])

    assert diagnose.context_scores(rec, [5])["context_precision@5"] == 0.0
    assert diagnose.context_scores(rec, [5])["noise@5"] == 1.0
    assert diagnose.context_scores(empty, [5]) == {
        "context_precision@5": 0.0,
        "noise@5": 0.0,
        "capped_recall@5": 0.0,
    }


def test_capped_recall_lets_a_two_document_question_score_one_at_k1() -> None:
    rec = record("q", ["a.md", "b.md"], ["a.md", "b.md"])
    scores = diagnose.context_scores(rec, [1, 3])

    assert rec["metrics"]["recall@1"] == 0.5
    assert scores["capped_recall@1"] == 1.0
    assert scores["capped_recall@3"] == 1.0


def test_capped_recall_uses_the_file_relevance_rule_including_the_snippet() -> None:
    # a.md came back first but without the expected text, so it is not relevant.
    rec = record("q", ["a.md", "b.md"], ["a.md"], expected_text="answer", answer_at=None)
    assert diagnose.context_scores(rec, [1])["capped_recall@1"] == 0.0


@pytest.mark.parametrize(
    ("files", "expected_files", "expected_text", "answer_at", "question_class", "per_file"),
    [
        # Everything in the top 5 chunks, answer chunk included.
        (["a.md", "b.md"], ["a.md"], "answer", 1, None, {"a.md": None}),
        # No chunk of the expected file at all.
        (["b.md", "c.md"], ["a.md"], None, None, "never_retrieved", {"a.md": "never_retrieved"}),
        # First chunk at #6 behind five different files: ranking, not crowding.
        (
            ["b.md", "c.md", "d.md", "e.md", "b.md", "a.md"],
            ["a.md"],
            None,
            None,
            "ranked_low",
            {"a.md": "ranked_low"},
        ),
        # First chunk at #6 behind four chunks of b.md out of five: crowded out.
        (
            ["b.md", "b.md", "c.md", "b.md", "b.md", "a.md"],
            ["a.md"],
            None,
            None,
            "crowded_out",
            {"a.md": "crowded_out"},
        ),
        # The file is in the top 5 but the answer chunk is #7.
        (
            ["a.md", "b.md", "c.md", "a.md", "d.md", "e.md", "a.md"],
            ["a.md"],
            "answer",
            7,
            "paragraph_missed",
            {"a.md": "paragraph_missed"},
        ),
        # The file is in the top 5 but no chunk holds the answer.
        (["a.md", "b.md"], ["a.md"], "answer", None, "paragraph_missed", {"a.md": "paragraph_missed"}),
    ],
)
def test_classify_names_the_cause_of_each_miss(
    files: list[str],
    expected_files: list[str],
    expected_text: str | None,
    answer_at: int | None,
    question_class: str | None,
    per_file: dict[str, str | None],
) -> None:
    rec = record("q", files, expected_files, expected_text, answer_at)
    assert diagnose.classify(rec, 5) == {"class": question_class, "files": per_file}


def test_classify_takes_the_most_severe_cause_across_expected_files() -> None:
    # b.md is crowded out behind a.md; c.md never came back.
    rec = record("q", ["a.md", "a.md", "a.md", "a.md", "d.md", "b.md"], ["a.md", "b.md", "c.md"])
    result = diagnose.classify(rec, 5)

    assert result["files"] == {"a.md": None, "b.md": "crowded_out", "c.md": "never_retrieved"}
    assert result["class"] == "never_retrieved"


def test_a_second_file_counts_for_recall_but_is_crowded_out_of_the_top_chunks() -> None:
    # The two-document case from the roadmap: b.md is the second unique file,
    # so recall@5 is full, but its first chunk is #6 behind a.md's chunks.
    rec = record("q", ["a.md", "a.md", "a.md", "a.md", "a.md", "b.md"], ["a.md", "b.md"])

    assert rec["metrics"]["recall@5"] == 1.0
    assert diagnose.classify(rec, 5)["class"] == "crowded_out"


def test_label_holes_list_unlabeled_files_above_every_expected_file() -> None:
    rec = record("q", ["b.md", "c.md", "a.md", "d.md"], ["a.md"])
    assert diagnose.label_holes(rec, 5) == [
        {"filename": "b.md", "rank": 1},
        {"filename": "c.md", "rank": 2},
    ]
    # Nothing outranks an expected file in first place.
    assert diagnose.label_holes(record("r", ["a.md", "b.md"], ["a.md"]), 5) == []
    # With no expected file returned, every file in the top k is a hole.
    missing = record("m", ["b.md", "c.md", "d.md"], ["a.md"])
    assert [h["filename"] for h in diagnose.label_holes(missing, 2)] == ["b.md", "c.md"]


def test_annotate_skips_records_without_chunk_scores_and_summarize_counts_them() -> None:
    fine = record("fine", ["a.md"], ["a.md"])
    missed = record("missed", ["b.md"], ["a.md"], tags=("semantic", "keyword"))
    old = record("old", ["a.md"], ["a.md"])
    del old["chunk_scores"]
    old_metrics = dict(old["metrics"])

    diagnose.annotate([fine, missed, old], 5, K_VALUES)
    summary = diagnose.summarize([fine, missed, old], 5)

    assert "diagnosis" not in old and old["metrics"] == old_metrics
    assert "context_precision@5" in fine["metrics"]
    assert summary["skipped"] == 1
    assert summary["overall"] == {
        "questions": 2,
        "never_retrieved": 1,
        "ranked_low": 0,
        "crowded_out": 0,
        "paragraph_missed": 0,
    }
    assert summary["by_tag"]["keyword"]["never_retrieved"] == 1
    assert summary["by_tag"]["semantic"]["questions"] == 2
    assert summary["label_holes"] == [{"id": "missed", "files": [{"filename": "b.md", "rank": 1}]}]


def test_markdown_summary_explains_each_miss() -> None:
    results = results_for(
        [
            record("crowded", ["b.md", "b.md", "c.md", "b.md", "b.md", "a.md"], ["a.md"]),
            record("fine", ["a.md"], ["a.md"]),
        ]
    )
    text = report.render_summary(results)

    assert "## Why questions missed (top 5 chunks)" in text
    assert "1 of 2 have every expected file and answer chunk in it" in text
    assert "| Crowded out | 1 |" in text
    assert "| crowded | Crowded out | a.md: first chunk #6 |" in text
    assert "| context precision@5 |" in text


def test_markdown_and_html_leave_out_the_section_for_a_run_without_a_diagnosis() -> None:
    results = results_for([record("fine", ["a.md"], ["a.md"])])
    del results["diagnosis"]

    assert report.render_diagnosis(results) == ""
    assert "Why questions missed" not in html_report.render_html(results)


def test_html_report_shows_causes_questions_and_label_holes() -> None:
    results = results_for(
        [
            record("lost", ["b.md", "c.md"], ["a.md"]),
            record("deep", ["a.md", "b.md"], ["a.md"], expected_text="answer", answer_at=None),
        ]
    )
    page = html_report.render_html(results)

    assert "<h2>Why questions missed</h2>" in page
    assert "Never retrieved" in page and "File found, paragraph missed" in page
    assert "Questions with a cause to fix at the top 5 chunks (2)" in page
    assert "Unlabeled files ranked above every expected file (1)" in page
    assert "b.md (#1), c.md (#2)" in page


def test_diagnose_command_explains_an_existing_results_file(tmp_path: Path) -> None:
    records = [record("lost", ["b.md", "c.md"], ["a.md"]), record("fine", ["a.md"], ["a.md"])]
    results = results_for(records)
    for rec in results["queries"]:  # as an older run wrote it, before the diagnosis
        del rec["diagnosis"]
    del results["diagnosis"]
    path = tmp_path / "results.json"
    path.write_text(json.dumps(results), encoding="utf-8")
    page = tmp_path / "report.html"

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "diagnose", str(path), "--html", str(page)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "| Never retrieved | 1 |" in completed.stdout
    assert "Why questions missed" in page.read_text(encoding="utf-8")


def test_diagnose_command_refuses_a_results_file_without_chunk_scores(tmp_path: Path) -> None:
    results = results_for([record("fine", ["a.md"], ["a.md"])])
    for rec in results["queries"]:
        del rec["chunk_scores"]
    path = tmp_path / "results.json"
    path.write_text(json.dumps(results), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "diagnose", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "no chunk scores" in completed.stderr


def multi_file_record(files: list[str], answers: dict[str, int]) -> dict[str, Any]:
    """A two-file question whose expected_text sits at given positions per file."""
    rec = record("multi", files, ["a.md", "b.md"], expected_text="answer", answer_at=None)
    rec["answer_chunks"] = sorted(answers.values())
    rec["passage_rank"] = min(answers.values(), default=None)
    return rec


def test_each_expected_file_needs_its_own_answer_chunk_in_the_top_k() -> None:
    # Review case: a.md's answer is chunk 1 and both files are in the top 5, but
    # b.md's paragraph never came back. The question-level passage rank (#1)
    # would call this fine.
    missing = multi_file_record(["a.md", "b.md", "c.md"], {"a.md": 1})
    assert diagnose.classify(missing, 5) == {
        "class": "paragraph_missed",
        "files": {"a.md": None, "b.md": "paragraph_missed"},
    }

    # b.md's answer chunk is #6, outside the top 5 the chat model sees.
    deep = multi_file_record(
        ["a.md", "b.md", "c.md", "d.md", "e.md", "b.md"], {"a.md": 1, "b.md": 6}
    )
    assert diagnose.classify(deep, 5)["files"]["b.md"] == "paragraph_missed"

    both = multi_file_record(["a.md", "b.md"], {"a.md": 1, "b.md": 2})
    assert diagnose.classify(both, 5)["class"] is None


def test_paragraph_detail_names_the_file_and_its_answer_chunk() -> None:
    deep = multi_file_record(
        ["a.md", "b.md", "c.md", "d.md", "e.md", "b.md"], {"a.md": 1, "b.md": 6}
    )
    deep["diagnosis"] = diagnose.classify(deep, 5)
    missing = multi_file_record(["a.md", "b.md"], {"a.md": 1})
    missing["diagnosis"] = diagnose.classify(missing, 5)

    assert report._diagnosis_detail(deep) == "b.md: answer chunk #6"
    assert report._diagnosis_detail(missing) == "b.md: answer not returned"


@pytest.mark.parametrize(
    ("metric", "before", "after", "css", "words"),
    [
        # Review case: noise going up is worse, shown red with an up arrow.
        ("noise@5", 0.0, 0.8, "bad", "(up, worse)"),
        ("noise@5", 0.8, 0.0, "good", "(down, better)"),
        ("recall@5", 0.5, 0.9, "good", "(up, better)"),
        ("recall@5", 0.9, 0.5, "bad", "(down, worse)"),
    ],
)
def test_deltas_follow_each_metrics_direction(
    metric: str, before: float, after: float, css: str, words: str
) -> None:
    html = html_report._delta(after, before, noise=0.01, metric=metric)

    assert f'class="delta {css}"' in html
    assert words in html
    assert ("▲" in html) == (after > before)


def test_comparison_table_shows_more_noise_as_a_regression() -> None:
    clean = results_for([record("q", ["a.md", "a.md", "a.md", "a.md", "a.md"], ["a.md"])])
    noisy = results_for([record("q", ["a.md", "b.md", "c.md", "d.md", "e.md"], ["a.md"])])
    diff = report.diff_results(clean, noisy)

    page = html_report.render_html(noisy, diff, clean)
    row = page.split(">noise@5<", 1)[1].split("</tr>", 1)[0]

    assert 'class="delta bad"' in row and "+0.800" in row
