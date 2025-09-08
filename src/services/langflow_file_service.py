from typing import Any, Dict, List, Optional

from config.settings import LANGFLOW_INGEST_FLOW_ID, clients
from utils.logging_config import get_logger

logger = get_logger(__name__)


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
            "[LF] Upload response",
            status_code=resp.status_code,
            reason=resp.reason_phrase,
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Upload failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text[:500],
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
            logger.debug(
                "[LF] Added JWT token to tweaks for OpenSearch components"
            )
        else:
            logger.warning("[LF] No JWT token provided")
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

        # Avoid logging full payload to prevent leaking sensitive data (e.g., JWT)

        resp = await clients.langflow_request(
            "POST", f"/api/v1/run/{self.flow_id_ingest}", json=payload
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
        resp.raise_for_status()
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
