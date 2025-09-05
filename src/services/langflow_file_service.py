import logging
from typing import Any, Dict, List, Optional

from config.settings import LANGFLOW_INGEST_FLOW_ID, clients


class LangflowFileService:
    def __init__(self):
        self.flow_id_ingest = LANGFLOW_INGEST_FLOW_ID
        self.logger = logging.getLogger(__name__)

    async def upload_user_file(
        self, file_tuple, jwt_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload a file using Langflow Files API v2: POST /api/v2/files.
        Returns JSON with keys: id, name, path, size, provider.
        """
        self.logger.debug("[LF] Upload (v2) -> /api/v2/files")
        resp = await clients.langflow_request(
            "POST", "/api/v2/files", files={"file": file_tuple}
        )
        self.logger.debug(
            "[LF] Upload response: %s %s", resp.status_code, resp.reason_phrase
        )
        if resp.status_code >= 400:
            self.logger.error(
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
        self.logger.debug("[LF] Delete (v2) -> /api/v2/files/%s", file_id)
        resp = await clients.langflow_request("DELETE", f"/api/v2/files/{file_id}")
        self.logger.debug(
            "[LF] Delete response: %s %s", resp.status_code, resp.reason_phrase
        )
        if resp.status_code >= 400:
            self.logger.error(
                "[LF] Delete failed: %s %s | body=%s",
                resp.status_code,
                resp.reason_phrase,
                resp.text[:500],
            )
        resp.raise_for_status()

    async def run_ingestion_flow(
        self,
        file_paths: List[str],
        session_id: Optional[str] = None,
        tweaks: Optional[Dict[str, Any]] = None,
        jwt_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Trigger the ingestion flow with provided file paths.
        The flow must expose a File component path in input schema or accept files parameter.
        """
        if not self.flow_id_ingest:
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")

        payload: Dict[str, Any] = {
            "input_value": "Ingest files",
            "input_type": "chat",
            "output_type": "text",  # Changed from "json" to "text"
        }

        # Pass files via tweaks to File component (File-PSU37 from the flow)
        if file_paths:
            if not tweaks:
                tweaks = {}
            tweaks["File-PSU37"] = {"path": file_paths}

        if tweaks:
            payload["tweaks"] = tweaks
        if session_id:
            payload["session_id"] = session_id

        self.logger.debug(
            "[LF] Run ingestion -> /run/%s | files=%s session_id=%s tweaks_keys=%s jwt_present=%s",
            self.flow_id_ingest,
            len(file_paths) if file_paths else 0,
            session_id,
            list(tweaks.keys()) if isinstance(tweaks, dict) else None,
            bool(jwt_token),
        )

        # Log the full payload for debugging
        self.logger.debug("[LF] Request payload: %s", payload)

        resp = await clients.langflow_request(
            "POST", f"/api/v1/run/{self.flow_id_ingest}", json=payload
        )
        self.logger.debug(
            "[LF] Run response: %s %s", resp.status_code, resp.reason_phrase
        )
        if resp.status_code >= 400:
            self.logger.error(
                "[LF] Run failed: %s %s | body=%s",
                resp.status_code,
                resp.reason_phrase,
                resp.text[:1000],
            )
        resp.raise_for_status()
        return resp.json()
