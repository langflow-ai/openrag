import logging
from typing import Any, Dict, List, Optional

from config.settings import LANGFLOW_INGEST_FLOW_ID, clients

logger = logging.getLogger(__name__)


class LangflowFileService:
    def __init__(self):
        self.flow_id_ingest = LANGFLOW_INGEST_FLOW_ID

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
            "[LF] Upload response: %s %s", resp.status_code, resp.reason_phrase
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Upload failed: %s %s | body=%s",
                resp.status_code,
                resp.reason_phrase,
                resp.text[:500],
            )
        resp.raise_for_status()
        return resp.json()

    async def delete_user_file(self, file_id: str) -> None:
        """Delete a file by id using v2: DELETE /api/v2/files/{id}."""
        # NOTE: use v2 root, not /api/v1
        logger.debug("[LF] Delete (v2) -> /api/v2/files/%s", file_id)
        resp = await clients.langflow_request("DELETE", f"/api/v2/files/{file_id}")
        logger.debug(
            "[LF] Delete response: %s %s", resp.status_code, resp.reason_phrase
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Delete failed: %s %s | body=%s",
                resp.status_code,
                resp.reason_phrase,
                resp.text[:500],
            )
        resp.raise_for_status()

    async def run_ingestion_flow(
        self,
        file_paths: List[str],
        jwt_token: str,
        session_id: Optional[str] = None,
        tweaks: Optional[Dict[str, Any]] = None,
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
            tweaks["File-PSU37"] = {"path": file_paths}

        # Pass JWT token via tweaks using the x-langflow-global-var- pattern
        if jwt_token:
            # Using the global variable pattern that Langflow expects for OpenSearch components
            tweaks["OpenSearchHybrid-Ve6bS"] = {"jwt_token": jwt_token}
            logger.error("[LF] Adding JWT token to tweaks for OpenSearch components")
        else:
            logger.error("[LF] No JWT token provided")
        if tweaks:
            payload["tweaks"] = tweaks
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

        # Log the full payload for debugging
        logger.debug("[LF] Request payload: %s", payload)

        resp = await clients.langflow_request(
            "POST", f"/api/v1/run/{self.flow_id_ingest}", json=payload
        )
        logger.debug("[LF] Run response: %s %s", resp.status_code, resp.reason_phrase)
        if resp.status_code >= 400:
            logger.error(
                "[LF] Run failed: %s %s | body=%s",
                resp.status_code,
                resp.reason_phrase,
                resp.text[:1000],
            )
        resp.raise_for_status()
        return resp.json()

    async def upload_and_ingest_file(
        self,
        file_tuple,
        session_id: Optional[str] = None,
        tweaks: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        jwt_token: Optional[str] = None,
        delete_after_ingest: bool = True,
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
                }
            )
        except Exception as e:
            logger.error("[LF] Upload failed during combined operation", extra={"error": str(e)})
            raise Exception(f"Upload failed: {str(e)}")

        # Step 2: Prepare for ingestion
        file_path = upload_result.get("path")
        if not file_path:
            raise ValueError("Upload successful but no file path returned")

        # Convert UI settings to component tweaks if provided
        final_tweaks = tweaks.copy() if tweaks else {}
        
        if settings:
            logger.debug("[LF] Applying ingestion settings", extra={"settings": settings})

            # Split Text component tweaks (SplitText-QIKhg)
            if (
                settings.get("chunkSize")
                or settings.get("chunkOverlap")
                or settings.get("separator")
            ):
                if "SplitText-QIKhg" not in final_tweaks:
                    final_tweaks["SplitText-QIKhg"] = {}
                if settings.get("chunkSize"):
                    final_tweaks["SplitText-QIKhg"]["chunk_size"] = settings["chunkSize"]
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
                final_tweaks["OpenAIEmbeddings-joRJ6"]["model"] = settings["embeddingModel"]

            logger.debug("[LF] Final tweaks with settings applied", extra={"tweaks": final_tweaks})

        # Step 3: Run ingestion
        try:
            ingest_result = await self.run_ingestion_flow(
                file_paths=[file_path],
                session_id=session_id,
                tweaks=final_tweaks,
                jwt_token=jwt_token,
            )
            logger.debug("[LF] Ingestion completed successfully")
        except Exception as e:
            logger.error(
                "[LF] Ingestion failed during combined operation",
                extra={
                    "error": str(e),
                    "file_path": file_path
                }
            )
            # Note: We could optionally delete the uploaded file here if ingestion fails
            raise Exception(f"Ingestion failed: {str(e)}")

        # Step 4: Delete file from Langflow (optional)
        file_id = upload_result.get("id")
        delete_result = None
        delete_error = None
        
        if delete_after_ingest and file_id:
            try:
                logger.debug("[LF] Deleting file after successful ingestion", extra={"file_id": file_id})
                await self.delete_user_file(file_id)
                delete_result = {"status": "deleted", "file_id": file_id}
                logger.debug("[LF] File deleted successfully")
            except Exception as e:
                delete_error = str(e)
                logger.warning(
                    "[LF] Failed to delete file after ingestion",
                    extra={
                        "error": delete_error,
                        "file_id": file_id
                    }
                )
                delete_result = {"status": "delete_failed", "file_id": file_id, "error": delete_error}

        # Return combined result
        result = {
            "status": "success",
            "upload": upload_result,
            "ingestion": ingest_result,
            "message": f"File '{upload_result.get('name')}' uploaded and ingested successfully"
        }
        
        if delete_after_ingest:
            result["deletion"] = delete_result
            if delete_result and delete_result.get("status") == "deleted":
                result["message"] += " and cleaned up"
            elif delete_error:
                result["message"] += f" (cleanup warning: {delete_error})"
        
        return result