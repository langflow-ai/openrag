import asyncio
import json
import platform
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from config.settings import (
    DOCLING_ERROR_DETAIL_MAX_LENGTH,
    DOCLING_SERVE_URL,
    DOCLING_SERVE_VERIFY_SSL,
    get_openrag_config,
)
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger
from utils.run_mode_utils import is_run_mode_on_prem, is_run_mode_saas

logger = get_logger(__name__)


class DoclingConfig(BaseModel):
    do_ocr: bool
    ocr_engine: str
    do_table_structure: bool
    do_picture_classification: bool
    do_picture_description: bool


class DoclingServeError(Exception):
    """Raised when docling-serve conversion fails."""


class DoclingTransientError(DoclingServeError):
    """Raised for errors that may resolve on retry (network failures, 5xx)."""


class DoclingTaskState(StrEnum):
    """Result of a single status check against Docling Serve."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    NOT_FOUND = "not_found"


@dataclass
class DoclingStatusSnapshot:
    """Single-point-in-time view of a Docling task's state."""

    state: DoclingTaskState
    detail: str | None = None
    raw: dict | None = None


def get_docling_preset_configs(
    table_structure=False, ocr=False, picture_descriptions=False
) -> dict[str, Any]:
    """Get docling preset configurations based on toggle settings"""
    is_macos = platform.system() == "Darwin"

    config = {
        "do_ocr": ocr,
        "ocr_engine": "ocrmac" if is_macos else "easyocr",
        "do_table_structure": table_structure,
        "do_picture_classification": picture_descriptions,
        "do_picture_description": picture_descriptions,
    }

    return config


def _stringify_docling_error_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("error_message", "message", "detail", "error"):
            nested = _stringify_docling_error_value(value.get(key))
            if nested:
                return nested
        return json.dumps(value, default=str)
    if value:
        return str(value)
    return None


def _format_docling_error(payload: dict[str, Any]) -> str:
    messages = []
    errors = payload.get("errors")
    if isinstance(errors, list):
        for error in errors:
            message = _stringify_docling_error_value(error)
            if message:
                messages.append(message)
    else:
        message = _stringify_docling_error_value(errors)
        if message:
            messages.append(message)

    for key in ("error_message", "message", "detail", "error"):
        message = _stringify_docling_error_value(payload.get(key))
        if message:
            messages.append(message)

    if messages:
        result = "; ".join(dict.fromkeys(messages))
    else:
        result = json.dumps(payload, default=str)

    if not result:
        return "Unknown Docling processing error"

    if len(result) > DOCLING_ERROR_DETAIL_MAX_LENGTH:
        return f"{result[:DOCLING_ERROR_DETAIL_MAX_LENGTH]}..."
    return result


class DoclingService:
    _default_client: httpx.AsyncClient | None = None

    def __init__(
        self, docling_url: str | None = None, httpx_client: httpx.AsyncClient | None = None
    ):
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
                timeout=httpx.Timeout(300.0, connect=10.0), verify=DOCLING_SERVE_VERIFY_SSL
            )
        return DoclingService._default_client

    async def _build_docling_options_async(
        self,
        *,
        ocr_override: bool | None = None,
        picture_descriptions_override: bool | None = None,
    ) -> dict[str, Any]:
        """Build the options payload for docling from OpenRAG configs, incorporating VLM settings if enabled."""
        from services.watsonx_iam import WatsonxIamError, get_iam_token

        config = get_openrag_config()
        knowledge_config = config.knowledge

        is_ocr_enabled = ocr_override if ocr_override is not None else knowledge_config.ocr
        is_pic_desc_enabled = (
            picture_descriptions_override
            if picture_descriptions_override is not None
            else knowledge_config.picture_descriptions
        )

        preset = get_docling_preset_configs(
            table_structure=knowledge_config.table_structure,
            ocr=is_ocr_enabled,
            picture_descriptions=is_pic_desc_enabled,
        )

        options = {"to_formats": "json", "image_export_mode": "placeholder", **preset}

        # If picture descriptions are enabled, configure custom/local VLM model
        if is_pic_desc_enabled and knowledge_config.vlm_enabled:
            provider = knowledge_config.vlm_provider
            vlm_model = knowledge_config.vlm_model
            prompt = knowledge_config.vlm_prompt

            if provider == "local":
                options["picture_description_local"] = {
                    "repo_id": vlm_model,
                    "prompt": prompt,
                }
            elif provider == "watsonx":
                watsonx = config.providers.watsonx
                if not (watsonx.api_key and watsonx.endpoint and watsonx.project_id):
                    raise DoclingServeError(
                        "Docling VLM is enabled but the watsonx provider is not fully "
                        "configured (api key, endpoint, and project id are required)"
                    )
                try:
                    token = await get_iam_token(watsonx.api_key)
                except httpx.RequestError as e:
                    raise DoclingTransientError(
                        f"watsonx IAM token exchange network error: {str(e)}"
                    ) from e
                except WatsonxIamError as e:
                    raise DoclingServeError(str(e)) from e

                url = (
                    f"{watsonx.endpoint.rstrip('/')}/ml/v1/text/chat"
                    f"?version={knowledge_config.vlm_watsonx_api_version}"
                )
                options["picture_description_api"] = {
                    "url": url,
                    "headers": {"Authorization": f"Bearer {token}"},
                    "params": {
                        "model_id": vlm_model,
                        "project_id": watsonx.project_id,
                        "max_tokens": knowledge_config.vlm_max_tokens,
                    },
                    "prompt": prompt,
                }
            elif provider == "anthropic":
                anthropic = config.providers.anthropic
                if not anthropic.api_key:
                    raise DoclingServeError(
                        "Docling VLM is enabled but the Anthropic provider is not configured"
                    )
                url = "https://api.anthropic.com/v1/messages"
                options["picture_description_api"] = {
                    "url": url,
                    "headers": {
                        "x-api-key": anthropic.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    "params": {
                        "model": vlm_model,
                        "max_tokens": knowledge_config.vlm_max_tokens,
                    },
                    "prompt": prompt,
                }
            elif provider == "ollama":
                ollama = config.providers.ollama
                if not ollama.endpoint:
                    raise DoclingServeError(
                        "Docling VLM is enabled but the Ollama provider is not configured"
                    )
                url = f"{transform_localhost_url(ollama.endpoint).rstrip('/')}/v1/chat/completions"
                options["picture_description_api"] = {
                    "url": url,
                    "headers": {},
                    "params": {
                        "model": vlm_model,
                        "max_completion_tokens": knowledge_config.vlm_max_tokens,
                    },
                    "prompt": prompt,
                }
            else:  # openai or default
                openai = config.providers.openai
                if not openai.api_key:
                    raise DoclingServeError(
                        "Docling VLM is enabled but the OpenAI provider is not configured"
                    )
                url = "https://api.openai.com/v1/chat/completions"
                options["picture_description_api"] = {
                    "url": url,
                    "headers": {"Authorization": f"Bearer {openai.api_key}"},
                    "params": {
                        "model": vlm_model,
                        "max_completion_tokens": knowledge_config.vlm_max_tokens,
                    },
                    "prompt": prompt,
                }

        return options

    def _get_auth_headers(
        self, user_id: str | None = None, auth_header: str | None = None
    ) -> dict[str, str]:
        """Build authentication headers for Docling Serve in saas run mode."""
        headers = {}
        if (is_run_mode_saas() or is_run_mode_on_prem()) and auth_header:
            headers["Authorization"] = auth_header
        return headers

    async def upload_to_docling_direct_async(
        self,
        filename: str,
        file_content: bytes,
        user_id: str | None = None,
        auth_header: str | None = None,
        *,
        ocr: bool | None = None,
        picture_descriptions: bool | None = None,
    ) -> str:
        """
        Upload a file to Docling Serve asynchronously using direct multipart/form-data upload.
        """
        options = await self._build_docling_options_async(
            ocr_override=ocr,
            picture_descriptions_override=picture_descriptions,
        )

        headers = self._get_auth_headers(user_id, auth_header)

        # Docling serve async multipart endpoint /v1/convert/file/async
        # Options are passed as form data; dict-valued options (e.g.
        # picture_description_local, vlm_pipeline_model_api) go as JSON strings.
        data = {
            k: json.dumps(v)
            if isinstance(v, dict)
            else str(v).lower()
            if isinstance(v, bool)
            else v
            for k, v in options.items()
        }

        files = {"files": (filename, file_content)}

        client = self._get_client()
        should_close = client != self.httpx_client

        try:
            if should_close:
                async with client:
                    response = await client.post(
                        f"{self.docling_url}/v1/convert/file/async",
                        files=files,
                        data=data,
                        headers=headers,
                    )
            else:
                response = await client.post(
                    f"{self.docling_url}/v1/convert/file/async",
                    files=files,
                    data=data,
                    headers=headers,
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
        timeout: float = 600.0,
        user_id: str | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        """
        Poll Docling Serve for the result of an async conversion task.
        """
        client = self._get_client()
        should_close = client != self.httpx_client

        try:
            if should_close:
                async with client:
                    return await self._poll_result(
                        client, task_id, poll_interval, timeout, user_id, auth_header
                    )
            else:
                return await self._poll_result(
                    client, task_id, poll_interval, timeout, user_id, auth_header
                )
        except Exception as e:
            logger.error("Docling result retrieval failed", task_id=task_id, error=str(e))
            raise

    async def check_task_status(
        self,
        task_id: str,
        user_id: str | None = None,
        auth_header: str | None = None,
    ) -> DoclingStatusSnapshot:
        """
        Single (non-blocking) status check against Docling Serve.

        Used by the backend polling coordinator so that the polling loop lives
        in OpenRAG and not inside Langflow. Maps the Docling Serve response
        into a DoclingStatusSnapshot regardless of HTTP outcome.
        """
        client = self._get_client()
        url = f"{self.docling_url}/v1/status/poll/{task_id}"
        headers = self._get_auth_headers(user_id, auth_header)
        try:
            response = await client.get(url, headers=headers)
        except httpx.RequestError as e:
            # Transient network error — surface as PROCESSING so caller can
            # retry without prematurely failing the file.
            logger.debug("Transient error checking docling status", task_id=task_id, error=str(e))
            return DoclingStatusSnapshot(state=DoclingTaskState.PROCESSING, detail=str(e))

        if response.status_code == 404:
            return DoclingStatusSnapshot(state=DoclingTaskState.NOT_FOUND, detail="Task not found")
        if response.status_code >= 500:
            logger.debug(
                "Transient HTTP error from docling status endpoint",
                task_id=task_id,
                status_code=response.status_code,
            )
            return DoclingStatusSnapshot(
                state=DoclingTaskState.PROCESSING,
                detail=f"HTTP {response.status_code}",
            )
        if response.status_code >= 400:
            return DoclingStatusSnapshot(
                state=DoclingTaskState.FAILED,
                detail=f"HTTP {response.status_code}: {response.text[:300]}",
            )

        try:
            payload = response.json()
        except ValueError as e:
            return DoclingStatusSnapshot(
                state=DoclingTaskState.FAILED,
                detail=f"Malformed status response: {str(e)}",
            )

        status = payload.get("task_status")
        if status == "success":
            return DoclingStatusSnapshot(state=DoclingTaskState.SUCCESS, raw=payload)
        if status == "failure" or payload.get("errors") or payload.get("error"):
            err_details = _format_docling_error(payload)
            return DoclingStatusSnapshot(
                state=DoclingTaskState.FAILED,
                detail=f"Docling processing failed: {err_details}",
                raw=payload,
            )
        if status in ("started", "processing", "running"):
            return DoclingStatusSnapshot(state=DoclingTaskState.PROCESSING, raw=payload)
        return DoclingStatusSnapshot(state=DoclingTaskState.PENDING, raw=payload)

    async def fetch_task_result(
        self,
        task_id: str,
        user_id: str | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch the converted document for a Docling task that is already SUCCESS.

        Raises:
            DoclingServeError: if the result endpoint returns 404 (task expired
                or unknown), an unexpected status code, or a payload missing
                document.json_content.
        """
        client = self._get_client()
        url = f"{self.docling_url}/v1/result/{task_id}"
        headers = self._get_auth_headers(user_id, auth_header)
        try:
            response = await client.get(url, headers=headers)
        except httpx.RequestError as e:
            raise DoclingTransientError(f"Network error fetching docling result: {str(e)}") from e

        if response.status_code >= 500:
            raise DoclingTransientError(
                f"Docling result fetch failed with HTTP {response.status_code}: {response.text[:300]}"
            )
        if response.status_code == 404:
            raise DoclingServeError(
                f"Docling result not found for task {task_id} (task expired or unknown)"
            )
        if response.status_code >= 400:
            raise DoclingServeError(
                f"Docling result fetch failed with HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            payload = response.json()
        except ValueError as e:
            raise DoclingServeError(f"Malformed docling result payload: {str(e)}") from e

        if payload.get("status") == "failure" or payload.get("errors"):
            raise DoclingServeError(f"Docling processing failed: {_format_docling_error(payload)}")

        document = payload.get("document") or {}
        if document.get("json_content") is None:
            raise DoclingServeError("docling-serve response missing document.json_content")
        return document["json_content"]

    async def _poll_result(
        self,
        client: httpx.AsyncClient,
        task_id: str,
        poll_interval: float,
        timeout: float,
        user_id: str | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        """Internal polling logic."""
        elapsed = 0.0
        headers = self._get_auth_headers(user_id, auth_header)
        while elapsed < timeout:
            try:
                response = await client.get(
                    f"{self.docling_url}/v1/status/poll/{task_id}", headers=headers
                )
                response.raise_for_status()
                status_data = response.json()
            except Exception as e:
                logger.error("Error polling docling status", task_id=task_id, error=str(e))
                raise DoclingServeError(f"Error polling docling status: {str(e)}") from e

            status = status_data.get("task_status")

            if status == "success":
                result_response = await client.get(
                    f"{self.docling_url}/v1/result/{task_id}", headers=headers
                )
                result_response.raise_for_status()
                result_json = result_response.json()

                # Extract the json_content which matches the old convert_file/bytes return
                document = result_json.get("document") or {}
                doc_content = document.get("json_content")
                if doc_content is None:
                    raise DoclingServeError("docling-serve response missing document.json_content")

                return doc_content
            elif status == "failure" or status_data.get("errors"):
                raise DoclingServeError(
                    f"Docling processing failed: {_format_docling_error(status_data)}"
                )

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"Docling task {task_id} did not complete within {timeout} seconds")

    async def convert_file(
        self,
        file_path: str,
        user_id: str | None = None,
        auth_header: str | None = None,
        *,
        ocr: bool | None = None,
        picture_descriptions: bool | None = None,
    ) -> dict[str, Any]:
        """
        Convert a local file via docling-serve async polling.
        """
        path = Path(file_path)
        file_bytes = path.read_bytes()
        task_id = await self.upload_to_docling_direct_async(
            path.name,
            file_bytes,
            user_id=user_id,
            auth_header=auth_header,
            ocr=ocr,
            picture_descriptions=picture_descriptions,
        )
        return await self.get_docling_result_async(
            task_id, user_id=user_id, auth_header=auth_header
        )

    async def convert_bytes(
        self,
        content: bytes,
        filename: str,
        user_id: str | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        """
        Convert in-memory bytes via docling-serve async polling.
        """
        task_id = await self.upload_to_docling_direct_async(
            filename, content, user_id=user_id, auth_header=auth_header
        )
        return await self.get_docling_result_async(
            task_id, user_id=user_id, auth_header=auth_header
        )
