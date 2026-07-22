from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from scripts import openrag_bulk as bulk


def test_collect_upload_items_filters_deduplicates_and_sorts(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    nested = docs / "nested"
    nested.mkdir(parents=True)
    small = docs / "small.pdf"
    large = nested / "large.pdf"
    ignored = nested / "notes.txt"
    small.write_bytes(b"1")
    large.write_bytes(b"12345")
    ignored.write_text("ignore", encoding="utf-8")

    items = bulk.collect_upload_items(
        [str(docs), str(small)],
        include=["*.pdf"],
        exclude=["nested/*"],
    )

    assert [item.path for item in items] == [small.resolve()]

    all_pdfs = bulk.collect_upload_items([str(docs)], include=["*.pdf"])
    assert [item.path.name for item in bulk.sort_upload_items(all_pdfs, "size-desc")] == [
        "large.pdf",
        "small.pdf",
    ]


@pytest.mark.asyncio
async def test_api_client_posts_repeated_file_parts_to_openrag_v1(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        captured.update(
            url=str(request.url),
            api_key=request.headers.get("X-API-Key"),
            body=body,
        )
        return httpx.Response(202, json={"task_id": "task-1", "file_count": 2})

    client = bulk.OpenRAGApiClient(
        base_url="http://openrag.test",
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    )
    try:
        response = await client.submit_batch(
            [bulk.BulkUploadItem(first), bulk.BulkUploadItem(second)],
            settings_json='{"chunk_size":1000}',
            tweaks_json=None,
            replace_duplicates=True,
            timeout=5,
        )
    finally:
        await client.close()

    assert response["task_id"] == "task-1"
    assert captured["url"] == "http://openrag.test/api/v1/documents/ingest"
    assert captured["api_key"] == "secret-key"
    assert captured["body"].count(b'name="file"') == 2
    assert b'name="settings"' in captured["body"]
    assert b'{"chunk_size":1000}' in captured["body"]
    assert b'name="replace_duplicates"' in captured["body"]


@pytest.mark.asyncio
async def test_upload_bulk_items_batches_polls_and_aggregates(tmp_path: Path) -> None:
    paths = []
    for index in range(5):
        path = tmp_path / f"doc-{index}.txt"
        path.write_text(f"document {index}", encoding="utf-8")
        paths.append(path)

    class FakeClient:
        def __init__(self) -> None:
            self.submissions: list[dict[str, Any]] = []
            self.poll_counts: dict[str, int] = {}

        async def submit_batch(self, items, **kwargs):
            task_id = f"task-{len(self.submissions) + 1}"
            self.submissions.append(
                {"task_id": task_id, "files": [item.path.name for item in items], **kwargs}
            )
            return {"task_id": task_id, "status": "accepted"}

        async def get_task_status(self, task_id: str, *, timeout: float):
            count = self.poll_counts.get(task_id, 0) + 1
            self.poll_counts[task_id] = count
            file_count = len(self.submissions[int(task_id.removeprefix("task-")) - 1]["files"])
            if count == 1:
                return {
                    "task_id": task_id,
                    "status": "running",
                    "total_files": file_count,
                    "processed_files": 0,
                    "successful_files": 0,
                    "failed_files": 0,
                    "files": {},
                }
            return {
                "task_id": task_id,
                "status": "completed",
                "total_files": file_count,
                "processed_files": file_count,
                "successful_files": file_count,
                "failed_files": 0,
                "duration_seconds": 0.01,
                "files": {},
            }

    fake = FakeClient()
    persisted: list[dict[str, Any]] = []
    summary = await bulk.upload_bulk_items(
        client=fake,
        items=[bulk.BulkUploadItem(path) for path in paths],
        options=bulk.BulkUploadOptions(
            batch_size=2,
            max_inflight=2,
            max_submit=1,
            poll_interval=0,
            progress_interval=60,
            summary_interval=0,
            settings_json='{"chunk_size":1000}',
        ),
        progress=bulk.ProgressReporter(enabled=False),
        summary_callback=lambda value: persisted.append(json.loads(json.dumps(value))),
    )

    assert [submission["files"] for submission in fake.submissions] == [
        ["doc-0.txt", "doc-1.txt"],
        ["doc-2.txt", "doc-3.txt"],
        ["doc-4.txt"],
    ]
    assert all(
        submission["settings_json"] == '{"chunk_size":1000}' for submission in fake.submissions
    )
    assert [batch["status"] for batch in summary["batches"]] == [
        "completed",
        "completed",
        "completed",
    ]
    assert summary["successful_files"] == 5
    assert summary["failed_files"] == 0
    assert summary["completed_batches"] == 3
    assert summary["failed_batches"] == 0
    assert not bulk.bulk_failed(summary)
    assert persisted[0]["batches"][0]["status"] == "queued"


@pytest.mark.asyncio
async def test_upload_bulk_items_records_batch_failure_and_continues(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    class FakeClient:
        calls = 0

        async def submit_batch(self, _items, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise bulk.ApiError("payload too large", 413)
            return {"task_id": "task-ok", "status": "accepted"}

        async def get_task_status(self, _task_id: str, *, timeout: float):
            return {
                "status": "completed",
                "total_files": 1,
                "processed_files": 1,
                "successful_files": 1,
                "failed_files": 0,
                "files": {},
            }

    summary = await bulk.upload_bulk_items(
        client=FakeClient(),
        items=[bulk.BulkUploadItem(first), bulk.BulkUploadItem(second)],
        options=bulk.BulkUploadOptions(
            batch_size=1,
            max_inflight=1,
            poll_interval=0,
            summary_interval=0,
        ),
        progress=bulk.ProgressReporter(enabled=False),
    )

    assert [batch["status"] for batch in summary["batches"]] == ["failed", "completed"]
    assert "payload too large" in summary["batches"][0]["error"]
    assert summary["failed_batches"] == 1
    assert bulk.bulk_failed(summary)


def test_persist_list_and_load_summary(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    output_dir = runs_dir / "run-1"
    summary = {
        "total_files": 1,
        "batches": [{"batch_index": 1, "status": "completed", "successful_files": 1}],
    }

    saved = bulk.persist_summary(
        summary,
        output_dir=output_dir,
        run_id="run-1",
        started=0,
    )
    listed = bulk.list_runs(runs_dir)
    compact = bulk.load_summary_reference(runs_dir, "latest", detail=False)
    detailed = bulk.load_summary_reference(runs_dir, "run-1", detail=True)

    assert json.loads((output_dir / "summary.json").read_text(encoding="utf-8")) == saved
    assert listed["runs"][0]["run_id"] == "run-1"
    assert listed["runs"][0]["state"] == "completed"
    assert "batches" not in compact
    assert compact["summary"]["batch_status_counts"] == {"completed": 1}
    assert detailed["batches"][0]["successful_files"] == 1


def test_bulk_upload_command_loads_a_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "one.txt").write_text("one", encoding="utf-8")
    (docs / "two.txt").write_text("two", encoding="utf-8")

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

        async def get_task_status(self, _task_id: str, *, timeout: float):
            return {
                "status": "completed",
                "total_files": 2,
                "processed_files": 2,
                "successful_files": 2,
                "failed_files": 0,
                "files": {},
            }

    monkeypatch.setattr(bulk, "OpenRAGApiClient", FakeClient)
    exit_code = bulk.main(
        [
            "bulk",
            "upload",
            "--api-key",
            "test-key",
            "--no-progress",
            "--runs-dir",
            str(tmp_path / "runs"),
            "--run-id",
            "directory-run",
            "--poll-interval",
            "0",
            "--summary-interval",
            "0",
            str(docs),
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert FakeClient.submissions == [["one.txt", "two.txt"]]
    assert summary["total_files"] == 2
    assert summary["successful_files"] == 2
