import asyncio
import platform
import json
from pathlib import Path
from typing import Any, Optional, Dict
import httpx
from pydantic import BaseModel

from config.settings import get_openrag_config, DOCLING_SERVE_URL
from utils.logging_config import get_logger

logger = get_logger(__name__)

class DoclingConfig(BaseModel):
    do_ocr: bool
    ocr_engine: str
    do_table_structure: bool
    do_picture_classification: bool
    do_picture_description: bool
    picture_description_local: Optional[dict] = None

class DoclingServeError(Exception):
    """Raised when docling-serve conversion fails."""

def get_docling_preset_configs(
    table_structure=False, ocr=False, picture_descriptions=False
) -> Dict[str, Any]:
    """Get docling preset configurations based on toggle settings"""
    is_macos = platform.system() == "Darwin"

    config = {
        "do_ocr": ocr,
        "ocr_engine": "ocrmac" if is_macos else "easyocr",
        "do_table_structure": table_structure,
        "do_picture_classification": picture_descriptions,
        "do_picture_description": picture_descriptions,
        "picture_description_local": {
            "repo_id": "HuggingFaceTB/SmolVLM-256M-Instruct",
            "prompt": "Describe this image in a few sentences.",
        },
    }

    return config

class DoclingService:
    _default_client: Optional[httpx.AsyncClient] = None

    def __init__(self, docling_url: Optional[str] = None, httpx_client: Optional[httpx.AsyncClient] = None):
        """
        Initialize the DoclingService.
        
        Args:
            docling_url: Base URL of the Docling Serve instance. If None, auto-detects.
            httpx_client: Pre-configured httpx async client.
        """
        if docling_url:
            self.docling_url = docling_url.rstrip("/")
        else:
            self.docling_url = DOCLING_SERVE_URL
            
        self.httpx_client = httpx_client

    def _get_client(self) -> httpx.AsyncClient:
        if self.httpx_client:
            return self.httpx_client
        if DoclingService._default_client is None or DoclingService._default_client.is_closed:
            DoclingService._default_client = httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=10.0)
            )
        return DoclingService._default_client

    def _build_docling_options(self) -> Dict[str, Any]:
        """Build the options payload for docling from OpenRAG configs."""
        config = get_openrag_config()
        knowledge_config = config.knowledge
        
        preset = get_docling_preset_configs(
            table_structure=knowledge_config.table_structure,
            ocr=knowledge_config.ocr,
            picture_descriptions=knowledge_config.picture_descriptions
        )
        
        options = {
            "to_formats": "json",
            "image_export_mode": "placeholder",
            **preset
        }
        return options

    async def upload_to_docling_direct_async(self, filename: str, file_content: bytes) -> str:
        """
        Upload a file to Docling Serve asynchronously using direct multipart/form-data upload.
        """
        options = self._build_docling_options()
        
        # Docling serve async multipart endpoint /v1/convert/file/async
        # Options are passed as form data
        data = {
            k: str(v).lower() if isinstance(v, bool) else v
            for k, v in options.items()
            if not isinstance(v, dict)
        }        # picture_description_local needs to be JSON if it's a dict

        if "picture_description_local" in options:
            data["picture_description_local"] = json.dumps(options["picture_description_local"])

        files = {"files": (filename, file_content)}
        
        client = self._get_client()
        should_close = client != self.httpx_client
        
        try:
            if should_close:
                async with client:
                    response = await client.post(
                        f"{self.docling_url}/v1/convert/file/async",
                        files=files,
                        data=data
                    )
            else:
                response = await client.post(
                    f"{self.docling_url}/v1/convert/file/async",
                    files=files,
                    data=data
                )
            
            response.raise_for_status()
            task = response.json()
            return task["task_id"]
        except Exception as e:
            logger.error("Docling upload failed", filename=filename, error=str(e))
            raise

    async def get_docling_result_async(
        self,
        task_id: str,
        poll_interval: float = 1.0,
        timeout: float = 600.0
    ) -> Dict[str, Any]:
        """
        Poll Docling Serve for the result of an async conversion task.
        """
        client = self._get_client()
        should_close = client != self.httpx_client
        
        try:
            if should_close:
                async with client:
                    return await self._poll_result(client, task_id, poll_interval, timeout)
            else:
                return await self._poll_result(client, task_id, poll_interval, timeout)
        except Exception as e:
            logger.error("Docling result retrieval failed", task_id=task_id, error=str(e))
            raise

    async def _poll_result(self, client: httpx.AsyncClient, task_id: str, poll_interval: float, timeout: float) -> Dict[str, Any]:
        """Internal polling logic."""
        elapsed = 0.0
        while elapsed < timeout:
            try:
                response = await client.get(f"{self.docling_url}/v1/status/poll/{task_id}")
                response.raise_for_status()
                status_data = response.json()
            except Exception as e:
                logger.error("Error polling docling status", task_id=task_id, error=str(e))
                raise DoclingServeError(f"Error polling docling status: {str(e)}")

            status = status_data.get("task_status")

            if status == "success":
                result_response = await client.get(f"{self.docling_url}/v1/result/{task_id}")
                result_response.raise_for_status()
                result_json = result_response.json()
                
                # Extract the json_content which matches the old convert_file/bytes return
                doc_content = result_json.get("document", {}).get("json_content")
                if doc_content is None:
                    raise DoclingServeError("docling-serve response missing document.json_content")
                
                return doc_content
            elif status == "failure":
                raise DoclingServeError(f"Docling conversion failed: {status_data}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"Docling task {task_id} did not complete within {timeout} seconds")

    async def convert_file(self, file_path: str) -> Dict[str, Any]:
        """
        Convert a local file via docling-serve async polling.
        """
        path = Path(file_path)
        file_bytes = path.read_bytes()
        task_id = await self.upload_to_docling_direct_async(path.name, file_bytes)
        return await self.get_docling_result_async(task_id)

    async def convert_bytes(self, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Convert in-memory bytes via docling-serve async polling.
        """
        task_id = await self.upload_to_docling_direct_async(filename, content)
        return await self.get_docling_result_async(task_id)
