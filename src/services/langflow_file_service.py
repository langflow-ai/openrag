from typing import Any, Dict, List, Optional

import httpx

from config.settings import FLOW_ID_INGEST, LANGFLOW_BASE_URL, LANGFLOW_KEY


class LangflowFileService:
    def __init__(self):
        self.base_url = LANGFLOW_BASE_URL.rstrip("/")
        self.api_key = LANGFLOW_KEY
        self.flow_id_ingest = FLOW_ID_INGEST

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        if extra:
            headers.update(extra)
        return headers

    async def upload_user_file(self, file_tuple) -> Dict[str, Any]:
        """Upload a file for the current user using Langflow Files API."""
        url = f"{self.base_url}/files/user/upload"
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": file_tuple}
            resp = await client.post(url, headers=self._headers(), files=files)
            resp.raise_for_status()
            return resp.json()

    async def delete_user_file(self, file_id: str) -> None:
        url = f"{self.base_url}/files/user/{file_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(url, headers=self._headers())
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
            raise ValueError("FLOW_ID_INGEST is not configured")

        url = f"{self.base_url}/run/{self.flow_id_ingest}"

        payload: Dict[str, Any] = {
            "input_value": "Ingest files",
            "input_type": "chat",
            "output_type": "json",
        }

        # Prefer passing files via 'files' if flow supports it, otherwise via tweaks
        if file_paths:
            payload["files"] = file_paths
        if tweaks:
            payload["tweaks"] = tweaks
        if session_id:
            payload["session_id"] = session_id

        extra_headers = {}
        if jwt_token:
            # Provide user context if flow needs it
            extra_headers["X-LANGFLOW-GLOBAL-VAR-JWT"] = jwt_token

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url, headers=self._headers(extra_headers), json=payload
            )
            resp.raise_for_status()
            return resp.json()
