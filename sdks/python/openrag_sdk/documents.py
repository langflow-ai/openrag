"""OpenRAG SDK documents client."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from .exceptions import NotFoundError
from .models import (
    DeleteDocumentResponse,
    FileRecord,
    IngestResponse,
    IngestTaskStatus,
    ListFilesResponse,
)

if TYPE_CHECKING:
    from .client import OpenRAGClient


class DocumentsClient:
    """Client for document operations."""

    def __init__(self, client: "OpenRAGClient"):
        self._client = client

    async def ingest(
        self,
        file_path: str | Path | None = None,
        *,
        file: BinaryIO | None = None,
        filename: str | None = None,
        wait: bool = True,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> IngestResponse | IngestTaskStatus:
        """
        Ingest a document into the knowledge base.

        Args:
            file_path: Path to the file to ingest.
            file: File-like object to ingest (alternative to file_path).
            filename: Filename to use when providing file object.
            wait: If True, poll until ingestion completes. If False, return immediately.
            poll_interval: Seconds between status checks when waiting.
            timeout: Maximum seconds to wait for completion.

        Returns:
            IngestTaskStatus with final status if wait=True.
            IngestResponse with task_id if wait=False.

        Raises:
            ValueError: If neither file_path nor file is provided.
            TimeoutError: If ingestion doesn't complete within timeout.
        """
        if file_path is not None:
            path = Path(file_path)
            with open(path, "rb") as f:
                files = {"file": (path.name, f)}
                response = await self._client._request(
                    "POST",
                    "/api/v1/documents/ingest",
                    files=files,
                )
        elif file is not None:
            if filename is None:
                raise ValueError("filename is required when providing file object")
            files = {"file": (filename, file)}
            response = await self._client._request(
                "POST",
                "/api/v1/documents/ingest",
                files=files,
            )
        else:
            raise ValueError("Either file_path or file must be provided")

        data = response.json()
        ingest_response = IngestResponse(**data)

        if not wait:
            return ingest_response

        # Poll for completion
        return await self.wait_for_task(
            ingest_response.task_id,
            poll_interval=poll_interval,
            timeout=timeout,
        )

    async def get_task_status(self, task_id: str) -> IngestTaskStatus:
        """
        Get the status of an ingestion task.

        Args:
            task_id: The task ID returned from ingest().

        Returns:
            IngestTaskStatus with current task status.
        """
        response = await self._client._request(
            "GET",
            f"/api/v1/tasks/{task_id}",
        )
        data = response.json()
        return IngestTaskStatus(**data)

    async def wait_for_task(
        self,
        task_id: str,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
    ) -> IngestTaskStatus:
        """
        Wait for an ingestion task to complete.

        Args:
            task_id: The task ID to wait for.
            poll_interval: Seconds between status checks.
            timeout: Maximum seconds to wait.

        Returns:
            IngestTaskStatus with final status.

        Raises:
            TimeoutError: If task doesn't complete within timeout.
        """
        elapsed = 0.0
        while elapsed < timeout:
            status = await self.get_task_status(task_id)
            if status.status in ("completed", "failed"):
                return status
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"Ingestion task {task_id} did not complete within {timeout}s"
        )

    async def delete(
        self,
        filename: str | None = None,
        *,
        filter_id: str | None = None,
    ) -> DeleteDocumentResponse:
        """
        Delete document(s) from the knowledge base.

        Provide exactly one of:
            filename: delete all chunks for that filename.
            filter_id: delete chunks for each filename in the filter's data_sources.

        Returns:
            DeleteDocumentResponse with deleted chunk count.
        """
        if bool(filename) == bool(filter_id):
            raise ValueError("Provide exactly one of `filename` or `filter_id`")

        body: dict[str, str] = {}
        if filename is not None:
            body["filename"] = filename
        if filter_id is not None:
            body["filter_id"] = filter_id

        try:
            response = await self._client._request(
                "DELETE",
                "/api/v1/documents",
                json=body,
            )
        except NotFoundError as e:
            # Keep delete idempotent for SDK callers: a missing document is not
            # an exception.
            # Filter-not-found 404s still raise because the filter_id is caller input.
            if filename is not None and getattr(e, "status_code", None) == 404:
                return DeleteDocumentResponse(
                    success=False,
                    deleted_chunks=0,
                    filename=filename,
                    message=None,
                    error=getattr(e, "message", "Resource not found"),
                )
            raise

        data = response.json()
        return DeleteDocumentResponse(**data)

    async def list_files(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        sort_by: str = "filename",
        sort_order: str = "asc",
        connector_type: str | None = None,
        mimetype: str | None = None,
        owner: str | None = None,
        search: str | None = None,
        after_key: str | None = None,
    ) -> ListFilesResponse:
        """
        List ingested files in the knowledge base.

        Args:
            page: Page number (display only; use after_key for cursor navigation).
            page_size: Number of files per page (1–500, default 25).
            sort_by: Field to sort by. One of: filename, file_size, mimetype,
                indexed_time, connector_type, chunk_count, owner.
            sort_order: "asc" or "desc".
            connector_type: Filter to files from a specific connector type.
            mimetype: Filter to files with a specific MIME type.
            owner: Filter to files owned by a specific user ID.
            search: Substring/prefix match against filename.
            after_key: JSON-encoded composite cursor from a previous response's
                after_key field. Pass to fetch the next page.

        Returns:
            ListFilesResponse with files list, total count, and next after_key.
        """
        params: dict[str, str | int] = {
            "page": page,
            "page_size": page_size,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if connector_type is not None:
            params["connector_type"] = connector_type
        if mimetype is not None:
            params["mimetype"] = mimetype
        if owner is not None:
            params["owner"] = owner
        if search is not None:
            params["search"] = search
        if after_key is not None:
            params["after_key"] = after_key

        response = await self._client._request(
            "GET",
            "/api/v1/files",
            params=params,
        )
        data = response.json()
        return ListFilesResponse(
            files=[FileRecord(**f) for f in data.get("files", [])],
            total=data.get("total", 0),
            is_approximate=data.get("is_approximate", True),
            page=data.get("page", page),
            page_size=data.get("page_size", page_size),
            after_key=data.get("after_key"),
        )
