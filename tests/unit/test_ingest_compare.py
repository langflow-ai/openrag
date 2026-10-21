from __future__ import annotations

from pathlib import Path

import pytest

from scripts import ingest_compare as compare

REPO = Path(__file__).resolve().parents[2]


def test_every_checked_in_fixture_exists():
    for fixture in compare.FIXTURES:
        if fixture.source is not None:
            assert (REPO / fixture.source).is_file(), fixture.name


def test_fixtures_cover_the_kinds_the_comparison_needs():
    assert {fixture.kind for fixture in compare.FIXTURES} >= {
        "text-heavy pdf",
        "table-heavy pdf",
        "scanned pdf",
        "image-only",
        "docx",
        "markdown",
        "plain text",
        "cjk",
    }


def test_fixture_names_are_unique():
    names = [fixture.name for fixture in compare.FIXTURES]
    assert len(names) == len(set(names))


def test_tokens_split_cjk_into_characters_and_ignore_markup():
    assert compare.tokens("## The **Quick** | fox 42") == ["the", "quick", "fox", "42"]
    assert compare.tokens("東京は晴れ abc") == ["東", "京", "は", "晴", "れ", "abc"]


def test_nothing_is_dropped_when_the_other_path_has_the_same_text_chunked_differently():
    a = ["one two three four five six seven", "eight nine ten eleven twelve"]
    b = ["one two three four five six seven eight nine ten eleven twelve"]

    dropped = compare.dropped_content(a, b)

    # Shingles that spanned a's chunk boundary don't exist in a, so b covers a.
    assert dropped["missing_pct"] == 0.0
    assert dropped["examples"] == []


def test_dropped_content_is_measured_and_shown():
    kept = "alpha beta gamma delta epsilon zeta eta theta"
    lost = "the table of quarterly revenue figures by region"
    a = [kept, lost]
    b = [kept]

    dropped = compare.dropped_content(a, b)

    assert 40 < dropped["missing_pct"] < 60
    assert dropped["examples"] == [lost]


def test_dropped_content_with_no_text_on_one_side():
    assert compare.dropped_content([], ["anything at all here ok"])["missing_pct"] == 0.0
    assert compare.dropped_content(["a b c d e f"], [])["missing_pct"] == 100.0


def test_short_chunks_still_count():
    # Fewer words than a shingle: the chunk is one shingle.
    assert compare.dropped_content(["Total 42"], ["something else"])["missing_pct"] == 100.0
    assert compare.dropped_content(["Total 42"], ["the Total 42 here"])["missing_pct"] == 0.0


def test_table_like_text():
    markdown_table = "| Year | Revenue |\n|---|---|\n| 2021 | 10 |\n| 2022 | 12 |"
    tab_table = "Year\tRevenue\n2021\t10\n2022\t12"
    prose = "Revenue grew in 2022.\nThe board approved | the plan."

    assert compare.is_table_like(markdown_table)
    assert compare.is_table_like(tab_table)
    assert not compare.is_table_like(prose)


def test_samples_are_the_first_a_table_and_the_longest_chunk():
    chunks = [
        {"text": "intro", "page": 1},
        {"text": "| a | b |\n| 1 | 2 |", "page": 2},
        {"text": "x" * 50, "page": 3},
    ]

    samples = compare.pick_samples(chunks)

    assert samples == {
        "first": chunks[0],
        "table": chunks[1],
        "longest": chunks[2],
    }


def test_samples_without_a_table():
    chunks = [{"text": "only prose here", "page": 1}]

    assert compare.pick_samples(chunks) == {
        "first": chunks[0],
        "table": None,
        "longest": chunks[0],
    }


def test_no_chunks_no_samples():
    assert compare.pick_samples([]) == {"first": None, "table": None, "longest": None}


def test_the_scanned_fixture_has_pages_but_no_text(tmp_path):
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")

    built = compare.build_scanned_pdf(
        REPO / "frontend/tests/test-data/kubernetes.pdf", tmp_path / "scanned.pdf"
    )

    pdf = pdfium.PdfDocument(str(built))
    assert len(pdf) == 2
    assert all(not page.get_textpage().get_text_range().strip() for page in pdf)


def test_the_cjk_fixture_carries_the_passage_as_text(tmp_path):
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("reportlab")

    built = compare.build_cjk_pdf(tmp_path / "cjk.pdf")

    text = pdfium.PdfDocument(str(built))[0].get_textpage().get_text_range()
    assert "知识库检索说明" in text
    assert "検索の仕組み" in text


# ── Orchestration against fake backend and OpenSearch ─────────────────────

import json  # noqa: E402

import httpx  # noqa: E402


class _FakeStack:
    """A backend that ingests into whatever index and mode /settings last set."""

    def __init__(self, *, fail_upload=False):
        self.settings = {"index_name": "documents", "disable_ingest_with_langflow": False}
        self.settings_posts: list[dict] = []
        self.deleted: list[str] = []
        self.uploads: list[tuple[str, list[str]]] = []
        self.indexes: dict[str, dict[str, list[dict]]] = {}
        self.fail_upload = fail_upload

    def backend(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/settings" and request.method == "GET":
            return httpx.Response(
                200, json={"knowledge": {**self.settings, "chunk_size": 1000, "ocr": True}}
            )
        if request.url.path == "/settings" and request.method == "POST":
            body = json.loads(request.content)
            self.settings_posts.append(body)
            self.settings.update(body)
            return httpx.Response(200, json={"message": "ok"})
        if request.url.path == "/router/upload_ingest":
            if self.fail_upload:
                return httpx.Response(500, json={"error": "boom"})
            names = re.findall(rb'filename="([^"]+)"', request.content)
            names = [n.decode() for n in names]
            path = "openrag" if self.settings["disable_ingest_with_langflow"] else "langflow"
            index = self.settings["index_name"]
            self.uploads.append((index, names))
            self.indexes[index] = {
                name: [{"text": f"{name} {path} text one two three four", "page": 1}]
                for name in names
            }
            return httpx.Response(201, json={"task_id": f"task-{path}"})
        if request.url.path.startswith("/tasks/"):
            path = request.url.path.rsplit("-", 1)[-1]
            index = self.uploads[-1][0]
            files = {
                f"/tmp/{name}": {
                    "filename": name,
                    "status": "completed",
                    "error": None,
                    "result": {
                        "status": "indexed",
                        "chunk_stats": {"chunk_count": 1, "ingest_path": path},
                    },
                }
                for name in self.indexes[index]
            }
            return httpx.Response(200, json={"status": "completed", "files": files})
        return httpx.Response(404)

    def opensearch(self, request: httpx.Request) -> httpx.Response:
        index = request.url.path.strip("/").split("/")[0]
        if request.method == "DELETE":
            self.deleted.append(index)
            self.indexes.pop(index, None)
            return httpx.Response(200, json={"acknowledged": True})
        name = json.loads(request.content)["query"]["term"]["filename"]
        chunks = self.indexes.get(index, {}).get(name, [])
        return httpx.Response(
            200, json={"hits": {"hits": [{"_id": "1", "_source": c} for c in chunks]}}
        )

    def clients(self):
        return (
            compare.OpenRAG(
                httpx.Client(base_url="http://backend", transport=httpx.MockTransport(self.backend))
            ),
            compare.Index(
                httpx.Client(base_url="http://os", transport=httpx.MockTransport(self.opensearch))
            ),
        )


import re  # noqa: E402


def _files(tmp_path, *names):
    files = []
    for name in names:
        path = tmp_path / name
        path.write_text("x")
        files.append((compare.Fixture(name, "plain text", source=name), path))
    return files


def test_each_path_ingests_into_its_own_fresh_index_and_settings_are_restored(tmp_path):
    stack = _FakeStack()
    api, index = stack.clients()

    results = compare.run_comparison(api, index, _files(tmp_path, "a.txt", "b.md"), poll_seconds=0)

    assert stack.settings_posts == [
        {"index_name": "compare-openrag-documents", "disable_ingest_with_langflow": True},
        {"index_name": "compare-langflow-documents", "disable_ingest_with_langflow": False},
        {"index_name": "documents", "disable_ingest_with_langflow": False},
    ]
    assert stack.deleted == ["compare-openrag-documents", "compare-langflow-documents"]
    assert stack.uploads == [
        ("compare-openrag-documents", ["a.txt", "b.md"]),
        ("compare-langflow-documents", ["a.txt", "b.md"]),
    ]
    doc = results["documents"][0]
    assert doc["name"] == "a.txt"
    assert doc["paths"]["openrag"]["chunk_stats"]["ingest_path"] == "openrag"
    assert doc["paths"]["langflow"]["chunks"][0]["text"].startswith("a.txt langflow")
    assert results["settings"]["chunk_size"] == 1000


def test_settings_are_restored_when_a_run_fails(tmp_path):
    stack = _FakeStack(fail_upload=True)
    api, index = stack.clients()

    with pytest.raises(compare.ApiError):
        compare.run_comparison(api, index, _files(tmp_path, "a.txt"), poll_seconds=0)

    assert stack.settings_posts[-1] == {
        "index_name": "documents",
        "disable_ingest_with_langflow": False,
    }


def test_indexes_can_be_deleted_after_the_run(tmp_path):
    stack = _FakeStack()
    api, index = stack.clients()

    compare.run_comparison(
        api, index, _files(tmp_path, "a.txt"), poll_seconds=0, delete_indexes=True
    )

    assert stack.deleted == ["compare-openrag-documents", "compare-langflow-documents"] * 2


def test_the_report_compares_each_document(tmp_path):
    stack = _FakeStack()
    api, index = stack.clients()
    results = compare.run_comparison(api, index, _files(tmp_path, "a.txt"), poll_seconds=0)

    report = compare.render_report(results)

    assert "# Ingest path comparison" in report
    assert "## a.txt" in report
    assert "| chunk_count | 1 | 1 |" in report
    # Each path's text names its path, so each side misses part of the other's.
    assert "Missing from langflow" in report
    assert "Missing from openrag" in report
