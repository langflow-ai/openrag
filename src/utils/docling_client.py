"""Async HTTP client for docling-serve document conversion."""

import os
from pathlib import Path

import httpx

from utils.logging_config import get_logger

logger = get_logger(__name__)


class DoclingServeError(Exception):
    """Raised when docling-serve conversion fails."""


async def _send_convert_request(
    httpx_client: httpx.AsyncClient,
    filename: str,
    file_bytes: bytes,
) -> dict:
    """Send a file to docling-serve and return the DoclingDocument dict."""
    from api.docling import DOCLING_SERVICE_URL

    url = f"{DOCLING_SERVICE_URL}/v1/convert/file"

    ocr_engine = os.getenv("DOCLING_OCR_ENGINE")
    data: dict[str, str] = {"to_formats": "json"}
    if ocr_engine:
        data["do_ocr"] = "true"
        data["ocr_engine"] = ocr_engine
    else:
        data["do_ocr"] = "false"

    try:
        response = await httpx_client.post(
            url,
            files={"files": (filename, file_bytes)},
            data=data,
        )
        response.raise_for_status()
    except httpx.ConnectError as exc:
        raise DoclingServeError(
            f"Cannot connect to docling-serve at {DOCLING_SERVICE_URL}. "
            f"Is it running? Start with: uvx docling-serve run"
        ) from exc
    except httpx.TimeoutException as exc:
        raise DoclingServeError(
            f"Timeout converting document via docling-serve: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise DoclingServeError(
            f"docling-serve returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:500]}"
        ) from exc

    resp_json = response.json()

    errors = resp_json.get("errors", [])
    if errors:
        raise DoclingServeError(f"docling-serve conversion errors: {errors}")

    doc_content = resp_json.get("document", {}).get("json_content")
    if doc_content is None:
        raise DoclingServeError(
            "docling-serve response missing document.json_content"
        )

    logger.info(
        "Document converted via docling-serve",
        filename=filename,
        processing_time=resp_json.get("processing_time"),
    )
    return doc_content


async def convert_file(file_path: str, *, httpx_client: httpx.AsyncClient) -> dict:
    """Convert a local file via docling-serve. Returns DoclingDocument dict."""
    path = Path(file_path)
    file_bytes = path.read_bytes()
    return await _send_convert_request(httpx_client, path.name, file_bytes)


async def convert_bytes(
    content: bytes, filename: str, *, httpx_client: httpx.AsyncClient
) -> dict:
    """Convert in-memory bytes via docling-serve. Returns DoclingDocument dict."""
    return await _send_convert_request(httpx_client, filename, content)
