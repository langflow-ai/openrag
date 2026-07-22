from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

from scripts import openrag_bulk as bulk


def _args(*values: str):
    parser = bulk.build_parser()
    args = parser.parse_args(["bench", "arxiv", *values])
    bulk._validate_arxiv_args(parser, args)
    return args


def _paper(arxiv_id: str = "2501.01234v1") -> bulk.ArxivPaper:
    return bulk.ArxivPaper(
        arxiv_id=arxiv_id,
        title="Benchmark Paper",
        summary="Summary",
        authors=("Ada Lovelace",),
        published="2025-01-01T00:00:00Z",
        updated="2025-01-02T00:00:00Z",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


def test_arxiv_defaults_and_category_date_query() -> None:
    defaults = _args("--download-only")
    atom = _args(
        "--download-only",
        "--source",
        "atom",
        "--category",
        "cs.AI",
        "--date-from",
        "2024-03-01",
        "--date-to",
        "2024-03-31",
    )

    assert defaults.source == "s3"
    assert defaults.s3_uri == bulk.DEFAULT_ARXIV_S3_URI
    assert defaults.skip_existing is True
    assert defaults.query == "cat:cs.CL AND submittedDate:[202501010000 TO 202512312359]"
    assert atom.query == "cat:cs.AI AND submittedDate:[202403010000 TO 202403312359]"


def test_parse_arxiv_feed_extracts_metadata_and_https_urls() -> None:
    feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2501.01234v2</id>
    <updated>2025-01-03T00:00:00Z</updated>
    <published>2025-01-01T00:00:00Z</published>
    <title> Retrieval
      Benchmarking for Agents </title>
    <summary>Short summary.</summary>
    <author><name>Ada Lovelace</name></author>
    <author><name>Alan Turing</name></author>
    <link href="http://arxiv.org/pdf/2501.01234v2" type="application/pdf" title="pdf"/>
  </entry>
</feed>
"""

    [paper] = bulk.parse_arxiv_feed(feed)

    assert paper.arxiv_id == "2501.01234v2"
    assert paper.title == "Retrieval Benchmarking for Agents"
    assert paper.authors == ("Ada Lovelace", "Alan Turing")
    assert paper.abs_url == "https://arxiv.org/abs/2501.01234v2"
    assert paper.pdf_url == "https://arxiv.org/pdf/2501.01234v2"


def test_fetch_arxiv_papers_builds_atom_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>https://arxiv.org/abs/2501.00001v1</id>
        <title>Paper</title><summary>Summary</summary>
        <link href="https://arxiv.org/pdf/2501.00001v1" type="application/pdf"/>
      </entry>
    </feed>"""

    def fake_read_url(url: str, **kwargs):
        captured.update(url=url, **kwargs)
        return feed

    monkeypatch.setattr(bulk, "read_url", fake_read_url)
    papers = bulk.fetch_arxiv_papers(
        query="cat:cs.AI",
        start=5,
        max_results=2,
        sort_by="submittedDate",
        sort_order="descending",
        rate=bulk.RateLimiter(0),
        user_agent="openrag-test",
        timeout=4,
    )

    assert papers[0].arxiv_id == "2501.00001v1"
    assert "search_query=cat%3Acs.AI" in captured["url"]
    assert "start=5" in captured["url"]
    assert "max_results=2" in captured["url"]
    assert captured["user_agent"] == "openrag-test"
    assert captured["accept"] == "application/atom+xml"


def test_stage_s3_papers_caches_tarball_and_extracted_pdfs(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    first = source_dir / "2501.00001v1.pdf"
    second = source_dir / "2501.00002v1.pdf"
    first.write_bytes(b"%PDF first")
    second.write_bytes(b"%PDF second")
    tarball = tmp_path / "arxiv.tar"
    with tarfile.open(tarball, "w") as archive:
        archive.add(first, arcname="pdf/2501/2501.00001v1.pdf")
        archive.add(second, arcname="pdf/2501/2501.00002v1.pdf")

    downloads, errors, skipped, details = bulk.stage_s3_papers(
        s3_uri=str(tarball),
        s3_cache_dir=tmp_path / "s3-cache",
        pdf_dir=tmp_path / "pdf-cache",
        aws_cli="aws",
        request_payer="",
        start=0,
        max_results=2,
        max_pdf_bytes=1024,
        skip_existing=True,
        progress=bulk.ProgressReporter(enabled=False),
    )

    assert errors == []
    assert skipped == []
    assert details["tarball_downloaded"] is True
    assert [item.paper.arxiv_id for item in downloads] == [
        "2501.00001v1",
        "2501.00002v1",
    ]
    assert [item.path.read_bytes() for item in downloads] == [b"%PDF first", b"%PDF second"]

    cached, errors, _, details = bulk.stage_s3_papers(
        s3_uri=str(tarball),
        s3_cache_dir=tmp_path / "s3-cache",
        pdf_dir=tmp_path / "pdf-cache",
        aws_cli="aws",
        request_payer="",
        start=1,
        max_results=1,
        max_pdf_bytes=1024,
        skip_existing=True,
        progress=bulk.ProgressReporter(enabled=False),
    )

    assert errors == []
    assert details["tarball_downloaded"] is False
    assert cached[0].paper.arxiv_id == "2501.00002v1"
    assert cached[0].cached is True


def test_download_papers_reuses_pdf_and_remembers_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    paper = _paper()
    cached_path = pdf_dir / bulk.pdf_filename(paper)
    cached_path.write_bytes(b"%PDF cached")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("cached PDF should not be downloaded")

    monkeypatch.setattr(bulk, "download_pdf", fail_if_called)
    downloads, errors, skipped = bulk.download_papers(
        [paper],
        pdf_dir=pdf_dir,
        rate=bulk.RateLimiter(0),
        user_agent="test",
        timeout=1,
        max_pdf_bytes=1024,
        skip_existing=True,
        progress=bulk.ProgressReporter(enabled=False),
    )

    assert errors == []
    assert skipped == []
    assert downloads[0].cached is True

    broken = _paper("2501.09999v1")
    failure_path = pdf_dir / "_failed_downloads.json"

    def fail_download(*_args, **_kwargs):
        raise RuntimeError("missing PDF")

    monkeypatch.setattr(bulk, "download_pdf", fail_download)
    _, errors, _ = bulk.download_papers(
        [broken],
        pdf_dir=pdf_dir,
        rate=bulk.RateLimiter(0),
        user_agent="test",
        timeout=1,
        max_pdf_bytes=1024,
        skip_existing=True,
        failure_cache={},
        failure_cache_path=failure_path,
        progress=bulk.ProgressReporter(enabled=False),
    )
    failure_cache = bulk.load_failed_download_cache(failure_path)
    _, second_errors, skipped = bulk.download_papers(
        [broken],
        pdf_dir=pdf_dir,
        rate=bulk.RateLimiter(0),
        user_agent="test",
        timeout=1,
        max_pdf_bytes=1024,
        skip_existing=True,
        failure_cache=failure_cache,
        failure_cache_path=failure_path,
        progress=bulk.ProgressReporter(enabled=False),
    )

    assert errors[0]["arxiv_id"] == broken.arxiv_id
    assert second_errors == []
    assert skipped[0]["arxiv_id"] == broken.arxiv_id


def test_bench_arxiv_download_only_runs_from_local_tarball(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF local")
    tarball = tmp_path / "arxiv.tar"
    with tarfile.open(tarball, "w") as archive:
        archive.add(source, arcname="pdf/2501.01234v1.pdf")
    runs_dir = tmp_path / "runs"
    pdf_dir = tmp_path / "pdfs"

    exit_code = bulk.main(
        [
            "bench",
            "arxiv",
            "--download-only",
            "--no-progress",
            "--s3-uri",
            str(tarball),
            "--s3-request-payer",
            "",
            "--runs-dir",
            str(runs_dir),
            "--pdf-cache-dir",
            str(pdf_dir),
            "--run-id",
            "local-run",
            "--max-results",
            "1",
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert summary["state"] == "completed"
    assert summary["ready_papers"] == 1
    assert summary["downloaded_papers"] == 1
    assert (pdf_dir / "2501.01234v1.pdf").read_bytes() == b"%PDF local"
    assert json.loads((runs_dir / "local-run" / "summary.json").read_text()) == summary

    assert bulk.main(["bench", "arxiv", "list", "--runs-dir", str(runs_dir)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["runs"][0]["run_id"] == "local-run"
    assert listed["runs"][0]["state"] == "completed"


@pytest.mark.asyncio
async def test_arxiv_benchmark_hands_downloads_to_bulk_uploader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF benchmark")
    downloaded = bulk.DownloadedPaper(
        paper=_paper(),
        path=pdf,
        size=pdf.stat().st_size,
        sha256=bulk.sha256_file(pdf),
    )

    def fake_stage(**_kwargs):
        return [downloaded], [], [], {"selected_pdf_members": 1}

    class FakeClient:
        submissions: list[list[str]] = []

        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def submit_batch(self, items, **_kwargs):
            self.submissions.append([item.path.name for item in items])
            return {"task_id": "task-1", "status": "accepted"}

        async def get_task_status(self, _task_id: str, *, timeout: float) -> dict[str, Any]:
            return {
                "status": "completed",
                "total_files": 1,
                "processed_files": 1,
                "successful_files": 1,
                "failed_files": 0,
                "files": {},
            }

    monkeypatch.setattr(bulk, "stage_s3_papers", fake_stage)
    monkeypatch.setattr(bulk, "OpenRAGApiClient", FakeClient)
    args = _args(
        "--api-key",
        "test-key",
        "--no-progress",
        "--runs-dir",
        str(tmp_path / "runs"),
        "--run-id",
        "upload-run",
        "--poll-interval",
        "0",
        "--summary-interval",
        "0",
        "--max-results",
        "1",
    )

    exit_code = await bulk._arxiv_main(args)
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert FakeClient.submissions == [["paper.pdf"]]
    assert summary["state"] == "completed"
    assert summary["bulk"]["successful_files"] == 1
    assert summary["batches"][0]["status"] == "completed"
