import logging
from typing import Any, Dict, List, Optional

import httpx

from config.settings import (
    LANGFLOW_BASE_URL,
    LANGFLOW_INGEST_FLOW_ID,
    LANGFLOW_URL,
)


class LangflowFileService:
    def __init__(self):
        self.base_url = LANGFLOW_BASE_URL.rstrip("/")
        self.flow_id_ingest = LANGFLOW_INGEST_FLOW_ID
        self.logger = logging.getLogger(__name__)

    async def _get_api_key(self) -> Optional[str]:
        """Get Langflow API key, ensuring it's generated if needed"""
        from config.settings import generate_langflow_api_key

        api_key = await generate_langflow_api_key()
        print(f"[LF] _get_api_key returning: {'present' if api_key else 'None'}")
        if api_key:
            print(f"[LF] API key prefix: {api_key[:8]}...")
        return api_key

    async def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        api_key = await self._get_api_key()
        headers = {"x-api-key": api_key} if api_key else {}
        if extra:
            headers.update(extra)
        return headers

    async def upload_user_file(
        self, file_tuple, jwt_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload a file using Langflow Files API v2: POST /api/v2/files.
        Returns JSON with keys: id, name, path, size, provider.
        """
        # NOTE: base_url points to /api/v1; v2 endpoints must not be prefixed with /api/v1
        url = f"{LANGFLOW_URL}/api/v2/files"
        api_key = await self._get_api_key()
        self.logger.debug("[LF] Upload (v2) -> %s (key_present=%s)", url, bool(api_key))
        if api_key:
            self.logger.debug(f"[LF] Using API key: {api_key[:12]}...")
        else:
            self.logger.error("[LF] No API key available for upload!")
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": file_tuple}
            headers = await self._headers()
            print(f"[LF] Upload headers: {headers}")
            # Note: jwt_token is for OpenSearch, not for Langflow API - only use x-api-key
            resp = await client.post(url, headers=headers, files=files)
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
        url = f"{LANGFLOW_URL}/api/v2/files/{file_id}"
        self.logger.debug("[LF] Delete (v2) -> %s (id=%s)", url, file_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = await self._headers()
            resp = await client.delete(url, headers=headers)
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

        url = f"{self.base_url}/run/{self.flow_id_ingest}"

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
            "[LF] Run ingestion -> %s | files=%s session_id=%s tweaks_keys=%s jwt_present=%s",
            url,
            len(file_paths) if file_paths else 0,
            session_id,
            list(tweaks.keys()) if isinstance(tweaks, dict) else None,
            bool(jwt_token),
        )

        # Log the full payload for debugging
        self.logger.debug("[LF] Request payload: %s", payload)

        extra_headers = {}
        # Note: Ingestion flow doesn't need JWT authentication context
        # Removed X-LANGFLOW-GLOBAL-VAR-JWT header

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url, headers=await self._headers(extra_headers), json=payload
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
