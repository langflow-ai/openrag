from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field

from dependencies import get_document_index_writer, get_langflow_ingest_token_service
from services.document_index_writer import DocumentIndexChunk, DocumentIndexWriter
from services.langflow_ingest_token_service import LangflowIngestTokenService
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LangflowIngestChunk(BaseModel):
    id: str
    text: str
    vector: list[float] = Field(min_length=1)
    page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LangflowIngestBatch(BaseModel):
    ingest_run_id: str
    batch_id: int = 0
    final: bool = False
    chunks: list[LangflowIngestChunk] = Field(default_factory=list)


def _extract_ingest_token(
    authorization: str | None,
    x_openrag_ingest_token: str | None,
) -> str:
    token = x_openrag_ingest_token or authorization or ""
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Langflow ingest token")
    return token


def _authorized_chunk_id(body: LangflowIngestBatch, document_id: str, index: int) -> str:
    """Build a backend-owned chunk id inside the token's document namespace."""
    if not document_id:
        raise HTTPException(status_code=403, detail="Langflow ingest token is missing document id")
    return f"{document_id}_{body.batch_id}_{index}"


async def ingest_langflow_chunks(
    body: LangflowIngestBatch,
    authorization: str | None = Header(default=None),
    x_openrag_ingest_token: str | None = Header(default=None),
    token_service: LangflowIngestTokenService = Depends(get_langflow_ingest_token_service),
    writer: DocumentIndexWriter = Depends(get_document_index_writer),
):
    token = _extract_ingest_token(authorization, x_openrag_ingest_token)
    try:
        context, jti = token_service.validate_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    if body.ingest_run_id != context.ingest_run_id:
        raise HTTPException(status_code=403, detail="Ingest run mismatch")

    chunks = [
        DocumentIndexChunk(
            chunk_id=_authorized_chunk_id(body, context.document_id, index),
            text=chunk.text,
            vector=chunk.vector,
            page=chunk.page,
            metadata={**chunk.metadata, "langflow_chunk_id": chunk.id},
        )
        for index, chunk in enumerate(body.chunks)
    ]
    try:
        result = await writer.index_chunks(context, chunks, final=body.final)
    except Exception as e:
        logger.error(
            "Langflow ingest callback failed",
            ingest_run_id=body.ingest_run_id,
            batch_id=body.batch_id,
            chunk_count=len(chunks),
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e)) from e

    if body.final:
        token_service.mark_finalized(jti)

    return {
        "status": "ok",
        "batch_id": body.batch_id,
        **result,
    }
