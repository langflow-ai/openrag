"""OpenRAG SDK documents client."""

from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import httpx

from .models import DeleteDocumentResponse, IngestResponse

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
    ) -> IngestResponse:
        """
        Ingest a document into the knowledge base.

        Args:
            file_path: Path to the file to ingest.
            file: File-like object to ingest (alternative to file_path).
            filename: Filename to use when providing file object.

        Returns:
            IngestResponse with document_id and chunk count.

        Raises:
            ValueError: If neither file_path nor file is provided.
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
        return IngestResponse(**data)

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
