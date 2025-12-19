"""OpenRAG SDK documents client."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from .models import DeleteDocumentResponse, IngestResponse, IngestTaskStatus

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

        raise TimeoutError(f"Ingestion task {task_id} did not complete within {timeout}s")

    async def delete(self, filename: str) -> DeleteDocumentResponse:
        """
        Delete a document from the knowledge base.

        Args:
            filename: Name of the file to delete.

        Returns:
            DeleteDocumentResponse with deleted chunk count.
        """
        response = await self._client._request(
            "DELETE",
            "/api/v1/documents",
            json={"filename": filename},
        )

        data = response.json()
        return DeleteDocumentResponse(**data)
