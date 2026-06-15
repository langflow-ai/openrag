"""Checks for client.documents — ingest (path / no-wait / file object) and delete."""

import io
import uuid

from harness import Check, Context, Skip

from checks.common import (
    make_doc,
    register_doc_cleanup,
    supports_delete_by_filter_id,
)


async def ingest_wait(ctx: Context) -> None:
    """Ingest the shared document used by the search/chat checks downstream."""
    path, token = make_doc(ctx, "shared", "The flamingo named Zephyr lives on planet Xylox-7.")
    register_doc_cleanup(ctx, path.name)

    result = await ctx.client.documents.ingest(file_path=str(path))
    assert result.status is not None, "ingest returned no status"
    assert result.successful_files >= 1, (
        f"ingestion completed but successful_files={result.successful_files} "
        f"(status={result.status})"
    )
    ctx.shared["doc"] = {"filename": path.name, "token": token}


async def ingest_nowait_poll(ctx: Context) -> None:
    path, _ = make_doc(ctx, "poll", "Content for the task-polling check.")
    register_doc_cleanup(ctx, path.name)

    task = await ctx.client.documents.ingest(file_path=str(path), wait=False)
    assert task.task_id is not None, "wait=False returned no task_id"

    status = await ctx.client.documents.get_task_status(task.task_id)
    assert status.status is not None, "get_task_status returned no status"

    final = await ctx.client.documents.wait_for_task(task.task_id)
    assert final.status in ("completed", "failed"), (
        f"wait_for_task ended in non-terminal status: {final.status}"
    )


async def ingest_file_object(ctx: Context) -> None:
    token = uuid.uuid4().hex
    filename = f"sdk_smoke_fileobj_{token[:8]}.md"
    content = f"# File Object Check\n\nToken: {token}\n".encode()
    register_doc_cleanup(ctx, filename)

    result = await ctx.client.documents.ingest(file=io.BytesIO(content), filename=filename)
    assert result.status is not None, "file-object ingest returned no status"


async def reingest_same_filename(ctx: Context) -> None:
    path, _ = make_doc(ctx, "reingest", "Content for the re-ingest check.")
    register_doc_cleanup(ctx, path.name)

    first = await ctx.client.documents.ingest(file_path=str(path))
    assert first.status is not None
    second = await ctx.client.documents.ingest(file_path=str(path))
    assert second.status is not None, "re-ingesting the same filename failed"


async def delete_by_filename(ctx: Context) -> None:
    path, _ = make_doc(ctx, "delete", "Content for the delete-by-filename check.")
    ingest_result = await ctx.client.documents.ingest(file_path=str(path))

    result = await ctx.client.documents.delete(path.name)
    if ingest_result.successful_files > 0:
        assert result.success is True, f"delete failed: {result.error}"
        assert result.deleted_chunks > 0, "delete reported no chunks removed"
    else:
        assert result.success is False
        assert result.deleted_chunks == 0


async def delete_missing_idempotent(ctx: Context) -> None:
    missing = f"never_ingested_{uuid.uuid4().hex}.pdf"
    result = await ctx.client.documents.delete(missing)
    assert result.success is False, "deleting a missing file reported success"
    assert result.deleted_chunks == 0
    assert result.filename == missing
    assert result.error is not None, "missing-file delete carried no error message"


async def delete_by_filter_id(ctx: Context) -> None:
    """Deleting via filter_id removes only files in the filter's data_sources."""
    if not supports_delete_by_filter_id(ctx.client):
        raise Skip("documents.delete(filter_id=...) requires openrag-sdk >= 0.4.0")

    alpha, _ = make_doc(ctx, "delfilter_alpha", "Unique content about copper falcons.")
    beta, _ = make_doc(ctx, "delfilter_beta", "Unique content about silver herons.")
    register_doc_cleanup(ctx, alpha.name)
    register_doc_cleanup(ctx, beta.name)
    await ctx.client.documents.ingest(file_path=str(alpha))
    await ctx.client.documents.ingest(file_path=str(beta))

    created = await ctx.client.knowledge_filters.create(
        {
            "name": f"SDK smoke delete-filter {uuid.uuid4().hex[:6]}",
            "description": "Auto-created by SDK smoke tests",
            "queryData": {
                "query": "",
                "filters": {
                    "data_sources": [alpha.name],
                    "document_types": ["*"],
                    "owners": ["*"],
                    "connector_types": ["*"],
                },
                "limit": 10,
                "scoreThreshold": 0,
            },
        }
    )
    assert created.success is True, f"filter creation failed: {created.error}"
    ctx.add_cleanup(
        f"delete filter {created.id}",
        lambda: ctx.client.knowledge_filters.delete(created.id),
    )

    result = await ctx.client.documents.delete(filter_id=created.id)
    assert result.success is True, f"delete by filter_id failed: {result.error}"
    assert result.filter_id == created.id
    assert alpha.name in (result.filenames or []), "alpha not reported deleted"
    assert beta.name not in (result.filenames or []), "beta wrongly deleted"


CHECKS = [
    Check("documents.ingest_wait", ingest_wait),
    Check("documents.ingest_nowait_poll", ingest_nowait_poll),
    Check("documents.ingest_file_object", ingest_file_object),
    Check("documents.reingest_same_filename", reingest_same_filename),
    Check("documents.delete_by_filename", delete_by_filename),
    Check("documents.delete_missing_idempotent", delete_missing_idempotent),
    Check("documents.delete_by_filter_id", delete_by_filter_id),
]
