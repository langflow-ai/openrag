import json
import asyncio
import httpx
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import LANGFLOW_INGEST_FLOW_ID, LANGFLOW_URL_INGEST_FLOW_ID, clients
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LangflowFileService:
    def __init__(self):
        self.flow_id_ingest = LANGFLOW_INGEST_FLOW_ID
        self.flow_id_url_ingest = LANGFLOW_URL_INGEST_FLOW_ID

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

    async def upload_user_file(
        self, file_tuple, jwt_token: Optional[str] = None
    ) -> Dict[str, Any]:
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
        file_paths: List[str],
        file_tuples: list[tuple[str, str, str]],
        jwt_token: Optional[str] = None,
        session_id: Optional[str] = None,
        tweaks: Optional[Dict[str, Any]] = None,
        owner: Optional[str] = None,
        owner_name: Optional[str] = None,
        owner_email: Optional[str] = None,
        connector_type: Optional[str] = None,
        document_id: Optional[str] = None,
        source_url: Optional[str] = None,
        allowed_users: Optional[List[str]] = None,
        allowed_groups: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Trigger the ingestion flow with provided file paths.
        The flow must expose a File component path in input schema or accept files parameter.
        """
        if not self.flow_id_ingest:
            logger.error("[LF] LANGFLOW_INGEST_FLOW_ID is not configured")
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")

        payload: Dict[str, Any] = {
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

        if tweaks:
            payload["tweaks"] = tweaks
            logger.debug(f"[LF] Tweaks {tweaks}")
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
        mimetype = str(file_tuples[0][2]) if file_tuples and len(file_tuples) > 0 and len(file_tuples[0]) > 2 else ""

        # Get the current embedding model and provider credentials from config
        from config.settings import get_openrag_config
        from utils.langflow_headers import add_provider_credentials_to_headers
        
        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model

        headers = {
            "X-Langflow-Global-Var-JWT": str(jwt_token),
            "X-Langflow-Global-Var-OWNER": str(owner),
            "X-Langflow-Global-Var-OWNER_NAME": str(owner_name),
            "X-Langflow-Global-Var-OWNER_EMAIL": str(owner_email),
            "X-Langflow-Global-Var-CONNECTOR_TYPE": str(connector_type),
            "X-Langflow-Global-Var-FILENAME": filename,
            "X-Langflow-Global-Var-MIMETYPE": mimetype,
            "X-Langflow-Global-Var-FILESIZE": str(file_size_bytes),
            "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL": str(embedding_model),
            "X-Langflow-Global-Var-DOCUMENT_ID": str(document_id) if document_id else "",
            "X-Langflow-Global-Var-SOURCE_URL": str(source_url) if source_url else "",
        }

        # Serialize ACL lists as JSON strings for Langflow global vars
        # (flows will parse these back into lists before indexing)
        if allowed_users is not None:
            headers["X-Langflow-Global-Var-ALLOWED_USERS"] = json.dumps(
                allowed_users or []
            )
        if allowed_groups is not None:
            headers["X-Langflow-Global-Var-ALLOWED_GROUPS"] = json.dumps(
                allowed_groups or []
            )
        
        # Add provider credentials as global variables for ingestion
        add_provider_credentials_to_headers(headers, config)
        logger.info(f"[LF] Headers {headers}")
        logger.info(f"[LF] Payload {payload}")
        resp = await clients.langflow_request(
            "POST",
            f"/api/v1/run/{self.flow_id_ingest}",
            json=payload,
            headers=headers,
        )
        logger.debug(
            "[LF] Run response", status_code=resp.status_code, reason=resp.reason_phrase
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

    async def run_url_ingestion_flow(
        self,
        docs_url: str,
        crawl_depth: int,
        jwt_token: Optional[str] = None,
        owner: Optional[str] = None,
        owner_name: Optional[str] = None,
        owner_email: Optional[str] = None,
        connector_type: str = "url",
        prevent_outside: bool = True,
        tweaks: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run URL-based docs ingestion flow using Langflow global variable passthrough."""
        if not docs_url:
            raise ValueError("DEFAULT_DOCS_URL is not configured")
        flow_id = await self._ensure_url_ingest_flow_id()

        payload: Dict[str, Any] = {
            "input_value": docs_url,
            "input_type": "chat",
            "output_type": "text",
        }
        if tweaks:
            payload["tweaks"] = tweaks

        from config.settings import get_openrag_config
        from utils.langflow_headers import add_provider_credentials_to_headers

        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model
        headers = {
            "X-Langflow-Global-Var-JWT": str(jwt_token),
            "X-Langflow-Global-Var-OWNER": str(owner),
            "X-Langflow-Global-Var-OWNER_NAME": str(owner_name),
            "X-Langflow-Global-Var-OWNER_EMAIL": str(owner_email),
            "X-Langflow-Global-Var-CONNECTOR_TYPE": str(connector_type),
            "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL": str(embedding_model),

            "X-Langflow-Global-Var-DOCUMENT_ID":"",
            "X-Langflow-Global-Var-SOURCE_URL": str(docs_url),
    
            "X-Langflow-Global-Var-ALLOWED_USERS": json.dumps( []),
            "X-Langflow-Global-Var-ALLOWED_GROUPS": json.dumps( []),
        }
        add_provider_credentials_to_headers(headers, config)


        logger.info(
            "[LF] Running URL ingestion flow",
            docs_url=docs_url,
            crawl_depth=crawl_depth,
            connector_type=connector_type,
            embedding_model=embedding_model,
            headers=headers,
            payload=payload,
        )
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

    async def _ensure_url_ingest_flow_id(self) -> str:
        """Ensure URL ingest flow ID is valid; import flow if missing.

        Retries once for transient Langflow failures so short outages do not
        permanently block URL ingestion for the current process.
        """
        configured_flow_id = self.flow_id_url_ingest
        max_attempts = 2
        last_error: Exception | None = None

        flow_file = Path(__file__).resolve().parents[2] / "flows" / "openrag_url_mcp.json"
        if not flow_file.exists():
            raise ValueError(
                "LANGFLOW_URL_INGEST_FLOW_ID is invalid and "
                f"flow file was not found at {flow_file}"
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
                    raise ValueError(
                        "Langflow flow import succeeded but no flow id was returned"
                    )

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

    async def upload_and_ingest_file(
        self,
        file_tuple,
        session_id: Optional[str] = None,
        tweaks: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        jwt_token: Optional[str] = None,
        delete_after_ingest: bool = True,
        owner: Optional[str] = None,
        owner_name: Optional[str] = None,
        owner_email: Optional[str] = None,
        connector_type: Optional[str] = None,   
    ) -> Dict[str, Any]:
        """
        Combined upload, ingest, and delete operation.
        First uploads the file, then runs ingestion on it, then optionally deletes the file.

        Args:
            file_tuple: File tuple (filename, content, content_type)
            session_id: Optional session ID for the ingestion flow
            tweaks: Optional tweaks for the ingestion flow
            settings: Optional UI settings to convert to component tweaks
            jwt_token: Optional JWT token for authentication
            delete_after_ingest: Whether to delete the file from Langflow after ingestion (default: True)

        Returns:
            Combined result with upload info, ingestion result, and deletion status
        """
        logger.debug("[LF] Starting combined upload and ingest operation")

        # Step 1: Upload the file
        try:
            upload_result = await self.upload_user_file(file_tuple, jwt_token=jwt_token)
            logger.debug(
                "[LF] Upload completed successfully",
                extra={
                    "file_id": upload_result.get("id"),
                    "file_path": upload_result.get("path"),
                },
            )
        except Exception as e:
            logger.error(
                "[LF] Upload failed during combined operation", extra={"error": str(e)}
            )
            raise Exception(f"Upload failed: {str(e)}")

        # Step 2: Prepare for ingestion
        file_path = upload_result.get("path")
        if not file_path:
            raise ValueError("Upload successful but no file path returned")

        # Convert UI settings to component tweaks if provided
        final_tweaks = tweaks.copy() if tweaks else {}

        if settings:
            logger.debug(
                "[LF] Applying ingestion settings", extra={"settings": settings}
            )

            # Split Text component tweaks (SplitText-QIKhg)
            if (
                settings.get("chunkSize")
                or settings.get("chunkOverlap")
                or settings.get("separator")
            ):
                if "SplitText-QIKhg" not in final_tweaks:
                    final_tweaks["SplitText-QIKhg"] = {}
                if settings.get("chunkSize"):
                    final_tweaks["SplitText-QIKhg"]["chunk_size"] = settings[
                        "chunkSize"
                    ]
                if settings.get("chunkOverlap"):
                    final_tweaks["SplitText-QIKhg"]["chunk_overlap"] = settings[
                        "chunkOverlap"
                    ]
                if settings.get("separator"):
                    final_tweaks["SplitText-QIKhg"]["separator"] = settings["separator"]

            # OpenAI Embeddings component tweaks (OpenAIEmbeddings-joRJ6)
            if settings.get("embeddingModel"):
                if "OpenAIEmbeddings-joRJ6" not in final_tweaks:
                    final_tweaks["OpenAIEmbeddings-joRJ6"] = {}
                final_tweaks["OpenAIEmbeddings-joRJ6"]["model"] = settings[
                    "embeddingModel"
                ]

            logger.debug(
                "[LF] Final tweaks with settings applied",
                extra={"tweaks": final_tweaks},
            )

        # Step 3: Run ingestion
        try:
            ingest_result = await self.run_ingestion_flow(
                file_paths=[file_path],
                file_tuples=[file_tuple],
                jwt_token=jwt_token,
                session_id=session_id,
                tweaks=final_tweaks,
                owner=owner,
                owner_name=owner_name,
                owner_email=owner_email,
                connector_type=connector_type,
            )
            logger.debug("[LF] Ingestion completed successfully")
        except Exception as e:
            logger.error(
                "[LF] Ingestion failed during combined operation",
                extra={"error": str(e), "file_path": file_path},
            )
            raise

        # Step 4: Delete file from Langflow (optional)
        file_id = upload_result.get("id")
        delete_result = None
        delete_error = None

        if delete_after_ingest and file_id:
            try:
                logger.debug(
                    "[LF] Deleting file after successful ingestion",
                    extra={"file_id": file_id},
                )
                await self.delete_user_file(file_id)
                delete_result = {"status": "deleted", "file_id": file_id}
                logger.debug("[LF] File deleted successfully")
            except Exception as e:
                delete_error = str(e)
                logger.warning(
                    "[LF] Failed to delete file after ingestion",
                    extra={"error": delete_error, "file_id": file_id},
                )
                delete_result = {
                    "status": "delete_failed",
                    "file_id": file_id,
                    "error": delete_error,
                }

        # Return combined result
        result = {
            "status": "success",
            "upload": upload_result,
            "ingestion": ingest_result,
            "message": f"File '{upload_result.get('name')}' uploaded and ingested successfully",
        }

        if delete_after_ingest:
            result["deletion"] = delete_result
            if delete_result and delete_result.get("status") == "deleted":
                result["message"] += " and cleaned up"
            elif delete_error:
                result["message"] += f" (cleanup warning: {delete_error})"

        return result
