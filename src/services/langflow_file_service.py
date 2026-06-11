import asyncio
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from config.settings import (
    DOCLING_SERVE_VERIFY_SSL,
    LANGFLOW_INGEST_CALLBACK_BATCH_SIZE,
    LANGFLOW_INGEST_FLOW_ID,
    LANGFLOW_URL_INGEST_FLOW_ID,
    OPENRAG_BACKEND_ROUTER_ENABLE,
    clients,
    get_ingest_callback_url,
)
from services.document_index_writer import DocumentIndexContext
from utils.hash_utils import hash_id
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LangflowFileService:
    INGEST_OPENSEARCH_COMPONENT_ID = "OpenSearchVectorStoreComponentMultimodalMultiEmbedding-By9U4"
    URL_INGEST_OPENSEARCH_COMPONENT_ID = (
        "OpenSearchVectorStoreComponentMultimodalMultiEmbedding-PMGGV"
    )

    def __init__(
        self,
        flows_service=None,
        docling_service=None,
        document_index_writer=None,
        ingest_token_service=None,
    ):
        self.flow_id_ingest = LANGFLOW_INGEST_FLOW_ID
        self.flows_service = flows_service
        self.docling_service = docling_service
        self.document_index_writer = document_index_writer
        self.ingest_token_service = ingest_token_service
        self.flow_id_url_ingest = LANGFLOW_URL_INGEST_FLOW_ID
        self._embedding_dimension_cache: dict[str, int] = {}

    _TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

    @classmethod
    def _is_transient_status(cls, status_code: int) -> bool:
        return status_code in cls._TRANSIENT_STATUS_CODES

    @staticmethod
    def _is_transient_request_error(error: Exception) -> bool:
        return isinstance(
            error,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RequestError,
            ),
        )

    @staticmethod
    def merge_ui_ingest_settings_into_tweaks(
        tweaks: dict[str, Any] | None,
        settings: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Merge UI ingest dict (camelCase) into Langflow run ``tweaks``.

        - ``chunkSize`` / ``chunkOverlap`` / ``separator`` update the flow's
          ``SplitText-QIKhg`` node when any of those keys are present.
        - ``embeddingModel`` is intentionally not mapped to a component tweak.
          The embedding model should be supplied via
          ``run_ingestion_flow(..., selected_embedding_model=...)`` so Langflow
          resolves it through the global variable override, without relying on
          provider-specific component ids.
        """
        final_tweaks = dict(tweaks) if tweaks else {}
        if not settings:
            return final_tweaks

        if settings.get("chunkSize") or settings.get("chunkOverlap") or settings.get("separator"):
            if "SplitText-QIKhg" not in final_tweaks:
                final_tweaks["SplitText-QIKhg"] = {}
            if settings.get("chunkSize"):
                final_tweaks["SplitText-QIKhg"]["chunk_size"] = settings["chunkSize"]
            if settings.get("chunkOverlap"):
                final_tweaks["SplitText-QIKhg"]["chunk_overlap"] = settings["chunkOverlap"]
            if settings.get("separator"):
                final_tweaks["SplitText-QIKhg"]["separator"] = settings["separator"]

        return final_tweaks

    async def _detect_embedding_dimensions(
        self,
        embedding_model: str,
        embedding_provider: str | None,
    ) -> int:
        """Generate one probe embedding so mapping dimensions match the provider."""
        from services.models_service import ModelsService

        cache_key = f"{embedding_provider or ''}:{embedding_model}"
        cached = self._embedding_dimension_cache.get(cache_key)
        if cached:
            return cached

        litellm_model_name = await ModelsService().get_litellm_model_name(
            embedding_model,
            provider=embedding_provider,
        )
        response = await clients.patched_embedding_client.embeddings.create(
            model=litellm_model_name,
            input=["dimension probe"],
        )
        if not response.data:
            raise RuntimeError("Embedding provider returned no data for dimension probe")

        first = response.data[0]
        embedding = first["embedding"] if isinstance(first, dict) else first.embedding
        dimensions = len(embedding)
        if dimensions <= 0:
            raise RuntimeError("Embedding provider returned an empty dimension probe")

        self._embedding_dimension_cache[cache_key] = dimensions
        return dimensions

    async def _ensure_langflow_ingest_index(self, embedding_model: str | None) -> None:
        """Pre-create index mappings Langflow cannot manage with a DLS JWT."""
        if clients.opensearch is None:
            logger.debug("[LF] OpenSearch admin client unavailable; skipping ingest preflight")
            return

        try:
            from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL
            from config.settings import get_index_name, get_openrag_config
            from utils.embedding_fields import ensure_embedding_field_exists
            from utils.embeddings import create_index_body

            config = get_openrag_config()
            index_name = get_index_name()
            model_name = embedding_model or OPENAI_DEFAULT_EMBEDDING_MODEL
            embedding_dimensions = await self._detect_embedding_dimensions(
                model_name,
                config.knowledge.embedding_provider,
            )
            if not await clients.opensearch.indices.exists(index=index_name):
                await clients.opensearch.indices.create(
                    index=index_name,
                    body=await create_index_body(model_name, embedding_dimensions),
                )

            await ensure_embedding_field_exists(
                clients.opensearch,
                model_name,
                index_name,
                embedding_dimensions,
            )
        except Exception as e:
            logger.warning(
                "[LF] Failed to preconfigure OpenSearch index before Langflow ingest",
                embedding_model=embedding_model,
                error=str(e),
            )

    def _resolve_document_id(
        self,
        file_tuples: list[tuple[str, Any, str]] | None,
        document_id: str | None,
    ) -> str:
        if document_id:
            return document_id
        if file_tuples and len(file_tuples[0]) > 1:
            content: Any = file_tuples[0][1]
            if isinstance(content, str):
                content = content.encode("utf-8")
            if isinstance(content, bytes):
                return hash_id(io.BytesIO(content))
        return str(uuid.uuid4())

    def _configure_ingest_callback(
        self,
        *,
        document_id: str,
        filename: str,
        mimetype: str,
        file_size: int,
        embedding_model: str,
        owner: str | None,
        owner_name: str | None,
        owner_email: str | None,
        connector_type: str | None,
        source_url: str | None,
        allowed_users: list[str] | None,
        allowed_groups: list[str] | None,
        allowed_principals: list[str] | None,
        allowed_principal_labels: list[dict[str, Any]] | None = None,
    ) -> tuple[str | None, str | None]:
        if self.ingest_token_service is None:
            logger.warning(
                "[LF] Backend-owned ingest delegation DISABLED: no ingest_token_service "
                "wired. No OPENRAG_INGEST_* globals will be sent, so the Langflow "
                "OpenSearch component will fall back to a direct write.",
                document_id=document_id,
                backend_router_enabled=OPENRAG_BACKEND_ROUTER_ENABLE,
            )
            return None, None

        from config.settings import get_index_name

        ingest_run_id = f"{document_id}-{uuid.uuid4().hex}"
        context = DocumentIndexContext(
            document_id=document_id,
            filename=filename,
            mimetype=mimetype,
            embedding_model=embedding_model,
            owner=owner,
            owner_name=owner_name,
            owner_email=owner_email,
            file_size=file_size,
            connector_type=connector_type,
            source_url=source_url,
            allowed_users=allowed_users or [],
            allowed_groups=allowed_groups or [],
            allowed_principals=allowed_principals or [],
            allowed_principal_labels=allowed_principal_labels or [],
            ingest_run_id=ingest_run_id,
            is_sample_data=connector_type == "openrag_docs",
            index_name=get_index_name(),
        )
        token = self.ingest_token_service.create_token(context)
        logger.info(
            "[LF] Configured backend ingest callback",
            document_id=document_id,
            ingest_run_id=ingest_run_id,
            index_name=context.index_name,
            callback_url=get_ingest_callback_url(),
        )
        return token, ingest_run_id

    def _ingest_callback_global_var_headers(
        self,
        *,
        ingest_token: str | None,
        ingest_run_id: str | None,
    ) -> dict[str, str]:
        if not ingest_token or not ingest_run_id:
            logger.warning(
                "[LF] Ingest callback globals NOT attached to Langflow run "
                "(missing token or run_id) — OpenSearch component will resolve "
                "OPENRAG_INGEST_* to their placeholders and fall back to a direct "
                "write instead of delegating to the backend.",
                has_token=bool(ingest_token),
                has_run_id=bool(ingest_run_id),
            )
            return {}
        callback_url = get_ingest_callback_url()
        logger.info(
            "[LF] Ingest callback globals attached — delegating writes to backend",
            ingest_run_id=ingest_run_id,
            callback_url=callback_url,
            batch_size=LANGFLOW_INGEST_CALLBACK_BATCH_SIZE,
        )
        return {
            "X-Langflow-Global-Var-OPENRAG_INGEST_URL": callback_url,
            "X-Langflow-Global-Var-OPENRAG_INGEST_TOKEN": ingest_token,
            "X-Langflow-Global-Var-OPENRAG_INGEST_RUN_ID": ingest_run_id,
            "X-Langflow-Global-Var-OPENRAG_INGEST_BATCH_SIZE": str(
                LANGFLOW_INGEST_CALLBACK_BATCH_SIZE
            ),
        }

    async def _cleanup_failed_callback_ingest(
        self,
        *,
        ingest_token: str | None,
        ingest_run_id: str | None,
    ) -> None:
        if self.ingest_token_service is not None and ingest_token:
            self.ingest_token_service.revoke_token(ingest_token)
        if self.document_index_writer is None or not ingest_run_id:
            return
        try:
            await self.document_index_writer.delete_ingest_run(ingest_run_id)
        except Exception as e:
            logger.warning(
                "[LF] Failed to clean up partial backend ingest run",
                ingest_run_id=ingest_run_id,
                error=str(e),
            )

    async def upload_user_file(self, file_tuple, jwt_token: str | None = None) -> dict[str, Any]:
        """Upload a file using Langflow Files API v2: POST /api/v2/files.
        Returns JSON with keys: id, name, path, size, provider.
        """
        logger.debug("[LF] Upload (v2) -> /api/v2/files")
        resp = await clients.langflow_request(
            "POST",
            "/api/v2/files",
            files={"file": file_tuple},
            headers={"Content-Type": None},
        )
        logger.debug(
            "[LF] Upload response",
            status_code=resp.status_code,
            reason=resp.reason_phrase,
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Upload failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text,
            )
        resp.raise_for_status()
        return resp.json()

    async def delete_user_file(self, file_id: str) -> None:
        """Delete a file by id using v2: DELETE /api/v2/files/{id}."""
        # NOTE: use v2 root, not /api/v1
        logger.debug("[LF] Delete (v2) -> /api/v2/files/{id}", file_id=file_id)
        resp = await clients.langflow_request("DELETE", f"/api/v2/files/{file_id}")
        logger.debug(
            "[LF] Delete response",
            status_code=resp.status_code,
            reason=resp.reason_phrase,
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Delete failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text[:500],
            )
        resp.raise_for_status()

    async def run_ingestion_flow(
        self,
        file_paths: list[str],
        file_tuples: list[tuple[str, str, str]],
        jwt_token: str | None = None,
        session_id: str | None = None,
        tweaks: dict[str, Any] | None = None,
        owner: str | None = None,
        owner_name: str | None = None,
        owner_email: str | None = None,
        connector_type: str | None = None,
        document_id: str | None = None,
        source_url: str | None = None,
        allowed_users: list[str] | None = None,
        allowed_groups: list[str] | None = None,
        allowed_principals: list[str] | None = None,
        allowed_principal_labels: list[dict[str, Any]] | None = None,
        selected_embedding_model: str | None = None,
        docling_task_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Trigger the ingestion flow with provided file paths.
        The flow must expose a File component path in input schema or accept files parameter.
        """
        if not self.flow_id_ingest:
            logger.error("[LF] LANGFLOW_INGEST_FLOW_ID is not configured")
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")

        payload: dict[str, Any] = {
            "input_value": "Ingest files",
            "input_type": "chat",
            "output_type": "text",  # Changed from "json" to "text"
        }
        if not tweaks:
            tweaks = {}

        # Pass files via tweaks to File component (File-PSU37 from the flow)
        if file_paths:
            tweaks["DoclingRemote-Dp3PX"] = {"path": file_paths}

        # Pass metadata via tweaks to OpenSearch component
        metadata_tweaks = []
        if owner or owner is None:
            metadata_tweaks.append({"key": "owner", "value": owner})
        if owner_name:
            metadata_tweaks.append({"key": "owner_name", "value": owner_name})
        if owner_email:
            metadata_tweaks.append({"key": "owner_email", "value": owner_email})
        if connector_type:
            metadata_tweaks.append({"key": "connector_type", "value": connector_type})
        logger.info(f"[LF] Metadata tweaks {metadata_tweaks}")

        if session_id:
            payload["session_id"] = session_id

        logger.debug(
            "[LF] Run ingestion -> /run/%s | files=%s session_id=%s tweaks_keys=%s jwt_present=%s",
            self.flow_id_ingest,
            len(file_paths) if file_paths else 0,
            session_id,
            list(tweaks.keys()) if isinstance(tweaks, dict) else None,
            bool(jwt_token),
        )
        # To compute the file size in bytes, use len() on the file content (which should be bytes)
        file_size_bytes = len(file_tuples[0][1]) if file_tuples and len(file_tuples[0]) > 1 else 0
        # Avoid logging full payload to prevent leaking sensitive data (e.g., JWT)

        # Extract file metadata if file_tuples is provided
        filename = str(file_tuples[0][0]) if file_tuples and len(file_tuples) > 0 else ""
        mimetype = (
            str(file_tuples[0][2])
            if file_tuples and len(file_tuples) > 0 and len(file_tuples[0]) > 2
            else ""
        )
        resolved_document_id = self._resolve_document_id(file_tuples, document_id)

        # Get the current embedding model and provider credentials from config
        from config.settings import get_openrag_config
        from utils.langflow_headers import add_provider_credentials_to_headers

        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model
        if selected_embedding_model:
            embedding_model = selected_embedding_model

        headers = {
            "X-Langflow-Global-Var-JWT": str(jwt_token or ""),
            "X-Langflow-Global-Var-OWNER": str(owner),
            "X-Langflow-Global-Var-OWNER_NAME": str(owner_name),
            "X-Langflow-Global-Var-OWNER_EMAIL": str(owner_email),
            "X-Langflow-Global-Var-CONNECTOR_TYPE": str(connector_type),
            "X-Langflow-Global-Var-FILENAME": filename,
            "X-Langflow-Global-Var-MIMETYPE": mimetype,
            "X-Langflow-Global-Var-FILESIZE": str(file_size_bytes),
            "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL": str(embedding_model),
            "X-Langflow-Global-Var-DOCUMENT_ID": resolved_document_id,
            "X-Langflow-Global-Var-SOURCE_URL": str(source_url) if source_url else "",
            "X-Langflow-Global-Var-DOCLING_TASK_ID": str(docling_task_id)
            if docling_task_id
            else "",
            "X-Langflow-Global-Var-DOCLING_SERVE_VERIFY_SSL": str(DOCLING_SERVE_VERIFY_SSL).lower(),
        }

        # Serialize ACL lists as JSON strings for Langflow global vars
        # (flows will parse these back into lists before indexing)
        headers["X-Langflow-Global-Var-ALLOWED_USERS"] = json.dumps(allowed_users or [])
        headers["X-Langflow-Global-Var-ALLOWED_GROUPS"] = json.dumps(allowed_groups or [])
        headers["X-Langflow-Global-Var-ALLOWED_PRINCIPALS"] = json.dumps(allowed_principals or [])
        headers["X-Langflow-Global-Var-ALLOWED_PRINCIPAL_LABELS"] = json.dumps(
            allowed_principal_labels or []
        )

        ingest_token, ingest_run_id = self._configure_ingest_callback(
            document_id=resolved_document_id,
            filename=filename,
            mimetype=mimetype,
            file_size=file_size_bytes,
            embedding_model=embedding_model,
            owner=owner,
            owner_name=owner_name,
            owner_email=owner_email,
            connector_type=connector_type,
            source_url=source_url,
            allowed_users=allowed_users,
            allowed_groups=allowed_groups,
            allowed_principals=allowed_principals,
            allowed_principal_labels=allowed_principal_labels,
        )
        headers.update(
            self._ingest_callback_global_var_headers(
                ingest_token=ingest_token,
                ingest_run_id=ingest_run_id,
            )
        )
        if tweaks:
            payload["tweaks"] = tweaks
            logger.debug("[LF] Tweaks configured", tweak_keys=list(tweaks.keys()))

        # Add provider credentials as global variables for ingestion
        await add_provider_credentials_to_headers(
            headers, config, flows_service=self.flows_service, jwt_token=jwt_token
        )
        if self.ingest_token_service is None:
            await self._ensure_langflow_ingest_index(embedding_model)
        start_time = time.time()
        logger.info(
            "[INGEST] Run started",
            flow_id=self.flow_id_ingest,
            filename=filename,
            mimetype=mimetype,
        )
        try:
            resp = await clients.langflow_request(
                "POST",
                f"/api/v1/run/{self.flow_id_ingest}",
                json=payload,
                headers=headers,
            )
            duration = round(time.time() - start_time, 2)
            logger.info(
                "[INGEST] Run complete",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                duration_s=duration,
            )
            if resp.status_code >= 400:
                logger.error(
                    "[LF] Run failed",
                    status_code=resp.status_code,
                    reason=resp.reason_phrase,
                    body=resp.text[:1000],
                )

                # Extract error message from Langflow response
                error_message = f"Server error '{resp.status_code} {resp.reason_phrase}'"
                try:
                    error_data = resp.json()
                    if isinstance(error_data, dict) and "detail" in error_data:
                        detail = error_data["detail"]
                        if isinstance(detail, str):
                            try:
                                detail_obj = json.loads(detail)
                                if isinstance(detail_obj, dict) and "message" in detail_obj:
                                    error_message = detail_obj["message"]
                                else:
                                    error_message = detail
                            except json.JSONDecodeError:
                                error_message = detail
                        elif isinstance(detail, dict) and "message" in detail:
                            error_message = detail["message"]
                except Exception:
                    pass

                raise Exception(error_message)

            # Check if response is actually JSON before parsing
            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                logger.error(
                    "[LF] Unexpected response content type from Langflow",
                    content_type=content_type,
                    status_code=resp.status_code,
                    body=resp.text[:1000],
                )
                raise ValueError(
                    f"Langflow returned {content_type} instead of JSON. "
                    f"This may indicate the ingestion flow failed or the endpoint is incorrect. "
                    f"Response preview: {resp.text[:500]}"
                )

            try:
                resp_json = resp.json()
            except Exception as e:
                logger.error(
                    "[LF] Failed to parse run response as JSON",
                    body=resp.text[:1000],
                    error=str(e),
                )

                raise
            return resp_json
        except Exception:
            await self._cleanup_failed_callback_ingest(
                ingest_token=ingest_token,
                ingest_run_id=ingest_run_id,
            )
            raise

    async def run_url_ingestion_flow(
        self,
        docs_url: str,
        crawl_depth: int,
        jwt_token: str | None = None,
        owner: str | None = None,
        owner_name: str | None = None,
        owner_email: str | None = None,
        connector_type: str = "url",
        prevent_outside: bool = True,
        tweaks: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run URL-based docs ingestion flow using Langflow global variable passthrough."""
        if not docs_url:
            raise ValueError("DEFAULT_DOCS_URL is not configured")
        flow_id = await self._ensure_url_ingest_flow_id()

        payload: dict[str, Any] = {
            "input_value": docs_url,
            "input_type": "chat",
            "output_type": "text",
        }
        if not tweaks:
            tweaks = {}

        from config.settings import get_openrag_config
        from utils.langflow_headers import add_provider_credentials_to_headers

        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model
        resolved_document_id = hash_id(io.BytesIO(docs_url.encode("utf-8")))
        headers = {
            "X-Langflow-Global-Var-JWT": str(jwt_token or ""),
            "X-Langflow-Global-Var-OWNER": str(owner),
            "X-Langflow-Global-Var-OWNER_NAME": str(owner_name),
            "X-Langflow-Global-Var-OWNER_EMAIL": str(owner_email),
            "X-Langflow-Global-Var-CONNECTOR_TYPE": str(connector_type),
            "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL": str(embedding_model),
            "X-Langflow-Global-Var-DOCUMENT_ID": resolved_document_id,
            "X-Langflow-Global-Var-SOURCE_URL": str(docs_url),
            "X-Langflow-Global-Var-ALLOWED_USERS": json.dumps([]),
            "X-Langflow-Global-Var-ALLOWED_GROUPS": json.dumps([]),
            "X-Langflow-Global-Var-ALLOWED_PRINCIPALS": json.dumps([]),
            "X-Langflow-Global-Var-DOCLING_TASK_ID": "",
            "X-Langflow-Global-Var-FILENAME": str(docs_url),
            "X-Langflow-Global-Var-MIMETYPE": "text/html",
            "X-Langflow-Global-Var-FILESIZE": "0",
            "X-Langflow-Global-Var-DOCLING_SERVE_VERIFY_SSL": str(DOCLING_SERVE_VERIFY_SSL).lower(),
        }
        ingest_token, ingest_run_id = self._configure_ingest_callback(
            document_id=resolved_document_id,
            filename=docs_url,
            mimetype="text/html",
            file_size=0,
            embedding_model=embedding_model,
            owner=owner,
            owner_name=owner_name,
            owner_email=owner_email,
            connector_type=connector_type,
            source_url=docs_url,
            allowed_users=[],
            allowed_groups=[],
            allowed_principals=[],
            allowed_principal_labels=[],
        )
        headers.update(
            self._ingest_callback_global_var_headers(
                ingest_token=ingest_token,
                ingest_run_id=ingest_run_id,
            )
        )
        if tweaks:
            payload["tweaks"] = tweaks
        await add_provider_credentials_to_headers(
            headers, config, flows_service=self.flows_service, jwt_token=jwt_token
        )
        if self.ingest_token_service is None:
            await self._ensure_langflow_ingest_index(embedding_model)

        logger.info(
            "[LF] Running URL ingestion flow",
            docs_url=docs_url,
            crawl_depth=crawl_depth,
            connector_type=connector_type,
            embedding_model=embedding_model,
            tweak_keys=list(tweaks.keys()),
        )
        try:
            resp = await clients.langflow_request(
                "POST",
                f"/api/v1/run/{flow_id}",
                json=payload,
                headers=headers,
            )
            logger.info(
                "[LF] URL ingestion flow response received",
                status_code=resp.status_code,
                flow_id=flow_id,
            )
            if resp.status_code >= 400:
                logger.error(
                    "[LF] URL ingestion flow failed",
                    status_code=resp.status_code,
                    reason=resp.reason_phrase,
                    body=resp.text[:1000],
                )
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                logger.error(
                    "[LF] Unexpected URL ingestion response content type",
                    content_type=content_type,
                    status_code=resp.status_code,
                    body=resp.text[:1000],
                )
                raise ValueError(
                    f"Langflow returned {content_type} instead of JSON for URL ingestion. "
                    f"Response preview: {resp.text[:500]}"
                )

            return resp.json()
        except Exception:
            await self._cleanup_failed_callback_ingest(
                ingest_token=ingest_token,
                ingest_run_id=ingest_run_id,
            )
            raise

    async def _ensure_url_ingest_flow_id(self) -> str:
        """Ensure URL ingest flow ID is valid; import flow if missing.

        Retries once for transient Langflow failures so short outages do not
        permanently block URL ingestion for the current process.
        """
        configured_flow_id = self.flow_id_url_ingest
        max_attempts = 2
        last_error: Exception | None = None

        from config.paths import get_flows_path

        flow_file = Path(get_flows_path()) / "openrag_url_mcp.json"
        if not flow_file.exists():
            raise ValueError(
                f"LANGFLOW_URL_INGEST_FLOW_ID is invalid and flow file was not found at {flow_file}"
            )
        with flow_file.open("r", encoding="utf-8") as f:
            flow_payload = json.load(f)

        for attempt in range(1, max_attempts + 1):
            try:
                if configured_flow_id:
                    check_resp = await clients.langflow_request(
                        "GET", f"/api/v1/flows/{configured_flow_id}"
                    )
                    if check_resp.status_code < 400:
                        return configured_flow_id
                    if check_resp.status_code != 404:
                        if self._is_transient_status(check_resp.status_code):
                            if attempt < max_attempts:
                                logger.warning(
                                    "[LF] Transient URL ingest flow check failure, retrying once",
                                    status_code=check_resp.status_code,
                                    attempt=attempt,
                                    max_attempts=max_attempts,
                                    retry_in_seconds=1,
                                )
                                await asyncio.sleep(1)
                                continue
                            raise httpx.HTTPStatusError(
                                "URL ingest flow check failed",
                                request=check_resp.request,
                                response=check_resp,
                            )
                        logger.warning(
                            "[LF] URL ingest flow check returned non-404 error",
                            flow_id=configured_flow_id,
                            status_code=check_resp.status_code,
                            body_preview=check_resp.text[:300],
                        )
                        check_resp.raise_for_status()

                logger.warning(
                    "[LF] URL ingest flow ID missing/invalid; importing flow JSON",
                    flow_file=str(flow_file),
                    previous_flow_id=configured_flow_id,
                )
                create_resp = await clients.langflow_request(
                    "POST", "/api/v1/flows/", json=flow_payload
                )
                if create_resp.status_code not in (200, 201):
                    if self._is_transient_status(create_resp.status_code):
                        if attempt < max_attempts:
                            logger.warning(
                                "[LF] Transient URL ingest flow import failure, retrying once",
                                status_code=create_resp.status_code,
                                attempt=attempt,
                                max_attempts=max_attempts,
                                retry_in_seconds=1,
                            )
                            await asyncio.sleep(1)
                            continue
                        raise httpx.HTTPStatusError(
                            "URL ingest flow import failed",
                            request=create_resp.request,
                            response=create_resp,
                        )
                    logger.error(
                        "[LF] Failed to import URL ingest flow",
                        status_code=create_resp.status_code,
                        body_preview=create_resp.text[:500],
                    )
                    create_resp.raise_for_status()

                flow_data = create_resp.json()
                imported_flow_id = flow_data.get("id")
                if not imported_flow_id:
                    raise ValueError("Langflow flow import succeeded but no flow id was returned")

                self.flow_id_url_ingest = imported_flow_id
                logger.warning(
                    "[LF] Imported URL ingest flow for current runtime",
                    imported_flow_id=imported_flow_id,
                    note="Persist this in LANGFLOW_URL_INGEST_FLOW_ID to avoid re-importing on restart.",
                )
                return imported_flow_id

            except httpx.RequestError as e:
                last_error = e
                if attempt == max_attempts:
                    raise
                logger.warning(
                    "[LF] Transient request error during URL ingest auto-heal, retrying once",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    retry_in_seconds=1,
                    error=str(e),
                )
                await asyncio.sleep(1)

            except Exception as e:
                last_error = e
                raise

        if last_error:
            raise last_error
        raise RuntimeError("Unable to validate/import URL ingest flow")

    async def submit_to_docling(
        self,
        filename: str,
        content: bytes,
        jwt_token: str | None = None,
        owner: str | None = None,
    ) -> str:
        """Upload a file to Docling Serve and return the task_id immediately.

        Phase 1 of the two-phase ingestion model. The caller is responsible
        for polling Docling (typically via DoclingPollingService) and only
        invoking Langflow once Docling reports SUCCESS.
        """
        if self.docling_service is None:
            raise RuntimeError(
                "DoclingService is not configured. Ensure DOCLING_SERVE_URL is set "
                "and the service was injected correctly."
            )
        try:
            task_id = await self.docling_service.upload_to_docling_direct_async(
                filename, content, user_id=owner, auth_header=jwt_token
            )
            logger.debug(
                "[LF] Docling submission accepted",
                extra={"task_id": task_id, "filename": filename},
            )
            return task_id
        except Exception as e:
            logger.error(
                "[LF] Docling submission failed",
                extra={"error": str(e), "filename": filename},
            )
            raise Exception(f"Docling upload failed: {str(e)}") from e

    async def upload_and_ingest_file(
        self,
        file_tuple,
        session_id: str | None = None,
        tweaks: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
        jwt_token: str | None = None,
        owner: str | None = None,
        owner_name: str | None = None,
        owner_email: str | None = None,
        connector_type: str | None = None,
        docling_polling_service: Any | None = None,
        file_task: Any | None = None,
        document_id: str | None = None,
        source_url: str | None = None,
        allowed_users: list[str] | None = None,
        allowed_groups: list[str] | None = None,
        allowed_principals: list[str] | None = None,
        allowed_principal_labels: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Two-phase Docling upload + Langflow ingest operation.

        Phase 1: submit the file to Docling, receive a task_id. If a
        ``docling_polling_service`` is provided, poll the backend for Docling
        completion before invoking Langflow. This keeps Langflow execution
        slots free during long Docling conversions.

        Phase 2: trigger the Langflow ingestion flow once Docling has
        succeeded. The task_id is forwarded so the flow's DoclingRemote
        component fetches the already-completed result instead of re-uploading
        or re-polling.

        When ``docling_polling_service`` is None, falls back to the legacy
        single-step behavior (Langflow polls Docling itself), preserving
        backward compatibility.

        Args:
            file_tuple: (filename, content, content_type)
            docling_polling_service: optional DoclingPollingService for the
                two-phase flow. When None, Langflow handles polling.
            file_task: optional FileTask for phase / status tracking.
        """
        from models.tasks import DoclingPhaseStatus, IngestionPhase

        logger.debug("[LF] Starting two-phase Docling+Langflow ingest")

        filename, content, _ = file_tuple

        # ── Phase 1: submit to Docling ──────────────────────────────────
        if file_task is not None:
            file_task.phase = IngestionPhase.DOCLING
            file_task.docling_status = DoclingPhaseStatus.PENDING

        task_id = await self.submit_to_docling(filename, content, owner=owner, jwt_token=jwt_token)

        if file_task is not None:
            file_task.docling_task_id = task_id
            file_task.docling_status = DoclingPhaseStatus.PROCESSING

        # ── Phase 1b: backend-side polling (optional) ───────────────────
        if docling_polling_service is not None:
            from config.settings import (
                DOCLING_POLL_BACKOFF_FACTOR,
                DOCLING_POLL_INTERVAL_SECONDS,
                DOCLING_POLL_MAX_INTERVAL_SECONDS,
                DOCLING_POLL_MAX_SECONDS,
                DOCLING_POLL_TRANSIENT_RETRIES,
            )
            from services.docling_polling_service import PollOutcome

            poll_result = await docling_polling_service.poll_until_ready(
                task_id=task_id,
                poll_interval=DOCLING_POLL_INTERVAL_SECONDS,
                max_seconds=DOCLING_POLL_MAX_SECONDS,
                max_interval=DOCLING_POLL_MAX_INTERVAL_SECONDS,
                backoff_factor=DOCLING_POLL_BACKOFF_FACTOR,
                transient_retry_budget=DOCLING_POLL_TRANSIENT_RETRIES,
                user_id=owner,
                auth_header=jwt_token,
            )

            if poll_result.outcome != PollOutcome.SUCCESS:
                if file_task is not None:
                    if poll_result.outcome == PollOutcome.EXPIRED:
                        file_task.docling_status = DoclingPhaseStatus.EXPIRED
                    else:
                        file_task.docling_status = DoclingPhaseStatus.FAILED
                logger.error(
                    "[LF] Docling polling did not reach SUCCESS; skipping Langflow",
                    extra={
                        "task_id": task_id,
                        "filename": filename,
                        "outcome": poll_result.outcome.value,
                        "detail": poll_result.detail,
                        "elapsed_seconds": round(poll_result.elapsed_seconds, 2),
                    },
                )
                raise Exception(
                    f"Docling conversion did not complete ({poll_result.outcome.value}): "
                    f"{poll_result.detail or 'no detail provided'}"
                )

            if file_task is not None:
                file_task.docling_status = DoclingPhaseStatus.SUCCESS
            logger.info(
                "[LF] Docling conversion ready; proceeding to Langflow",
                extra={
                    "task_id": task_id,
                    "filename": filename,
                    "elapsed_seconds": round(poll_result.elapsed_seconds, 2),
                },
            )

        # ── Phase 2: trigger Langflow ingestion ─────────────────────────
        final_tweaks = LangflowFileService.merge_ui_ingest_settings_into_tweaks(tweaks, settings)
        if settings:
            logger.debug(
                "[LF] Applying ingestion settings",
                extra={"settings": settings, "tweaks": final_tweaks},
            )

        if file_task is not None:
            file_task.phase = IngestionPhase.LANGFLOW

        try:
            total_start_time = time.time()
            ingest_result = await self.run_ingestion_flow(
                file_paths=[],  # Files are not uploaded to Langflow FS
                file_tuples=[file_tuple],
                jwt_token=jwt_token,
                session_id=session_id,
                tweaks=final_tweaks,
                owner=owner,
                owner_name=owner_name,
                owner_email=owner_email,
                connector_type=connector_type,
                docling_task_id=task_id,
                document_id=document_id,
                source_url=source_url,
                allowed_users=allowed_users,
                allowed_groups=allowed_groups,
                allowed_principals=allowed_principals,
                allowed_principal_labels=allowed_principal_labels,
            )
            total_duration = round(time.time() - total_start_time, 2)
            logger.info(f"[LF] Ingestion completed successfully in {total_duration}s")
        except Exception as e:
            logger.error(
                "[LF] Ingestion failed during combined operation",
                extra={"error": str(e), "filename": filename},
            )
            # Docling Serve has no cancel endpoint; let any orphan task expire.
            raise

        if file_task is not None:
            file_task.phase = IngestionPhase.COMPLETE
            # Legacy path leaves docling_status at PROCESSING because the
            # backend never observed Docling completion directly. Langflow
            # returning success implies its DoclingRemote component consumed
            # the task, so Docling succeeded — mark SUCCESS to keep status
            # fields coherent. Idempotent for the polling path.
            file_task.docling_status = DoclingPhaseStatus.SUCCESS

        return {
            "status": "success",
            "docling_task_id": task_id,
            "ingestion": ingest_result,
            "message": f"File '{filename}' processed via Docling and ingested successfully",
        }
