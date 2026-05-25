"""Service-mode backend: HTTP client to the stateless openrag-connectors service.

Each method loads the current OAuth state from OpenRAG's
``EncryptedFileTokenStore``, ships it in the request body, and persists
any ``refreshed_oauth`` back to the store under a per-connection asyncio
lock (so concurrent calls can't clobber each other's refresh tokens).

Service routes are namespaced by connector type:
``POST /v1/{connector_type}/{operation}``.
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..base import ConnectorDocument, DocumentACL
from .encrypted_token_store import EncryptedFileTokenStore

logger = logging.getLogger(__name__)

_CONNECTION_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(connection_id: str) -> asyncio.Lock:
    lock = _CONNECTION_LOCKS.get(connection_id)
    if lock is None:
        lock = asyncio.Lock()
        _CONNECTION_LOCKS[connection_id] = lock
    return lock


class ServiceBackend:
    """HTTP client mirroring LibraryBackend's surface, parameterized by type."""

    def __init__(self, connector_type: str, config: dict[str, Any]):
        self.connector_type = connector_type
        self.config = config
        self.connection_id = config.get("connection_id", "default")

        self.service_url = os.environ.get("OPENRAG_CONNECTORS_URL")
        self.bearer = os.environ.get("OPENRAG_CONNECTORS_TOKEN")
        if not self.service_url:
            raise RuntimeError(
                "Service mode requires OPENRAG_CONNECTORS_URL (e.g. http://connectors-service:8000)"
            )
        if not self.bearer:
            raise RuntimeError(
                "Service mode requires OPENRAG_CONNECTORS_TOKEN — shared bearer secret"
            )

        # Token persistence on the OpenRAG side. Service is stateless.
        if config.get("token_store") is None:
            from config.paths import get_data_file

            token_file = config.get("token_file") or get_data_file(
                f"{connector_type}_token_{self.connection_id}.json"
            )
            Path(token_file).parent.mkdir(parents=True, exist_ok=True)
            self.token_store = EncryptedFileTokenStore(token_file)
        else:
            self.token_store = config["token_store"]

        # Credentials may come from config or from per-connector env vars.
        # Look up the env var names from the upstream class so this stays
        # connector-agnostic.
        from openrag_connectors import get as get_connector_cls

        upstream_cls = get_connector_cls(connector_type)
        self.client_id = config.get("client_id") or (
            os.environ.get(upstream_cls.CLIENT_ID_ENV_VAR)
            if upstream_cls.CLIENT_ID_ENV_VAR
            else None
        )
        self.client_secret = config.get("client_secret") or (
            os.environ.get(upstream_cls.CLIENT_SECRET_ENV_VAR)
            if upstream_cls.CLIENT_SECRET_ENV_VAR
            else None
        )

    # ── BaseConnector contract ─────────────────────────────────────────────

    async def authenticate(self) -> bool:
        try:
            resp = await self._call("authenticate", {})
            return bool(resp.get("authenticated"))
        except Exception as e:
            logger.error("Service-mode authenticate failed: %s", e)
            return False

    async def list_files(
        self,
        page_token: str | None = None,
        max_files: int | None = None,
    ) -> dict[str, Any]:
        resp = await self._call("list_files", {"page_token": page_token, "max_files": max_files})
        return {
            "files": resp.get("files", []),
            "next_page_token": resp.get("next_page_token"),
        }

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        body = await self._build_request_body({"file_id": file_id})
        url = f"{self.service_url}/v1/{self.connector_type}/get_file_content"
        async with _lock_for(self.connection_id):
            async with httpx.AsyncClient(timeout=300) as http:
                r = await http.post(
                    url, json=body, headers={"Authorization": f"Bearer {self.bearer}"}
                )
                r.raise_for_status()
                content = r.content

                refreshed_b64 = r.headers.get("X-Refreshed-OAuth")
                if refreshed_b64:
                    await self._persist_refreshed(refreshed_b64)

                meta_b64 = r.headers.get("X-Connector-Document")
                if not meta_b64:
                    raise RuntimeError("Service response missing X-Connector-Document header")
                meta = json.loads(base64.b64decode(meta_b64))

        acl_dict = meta.get("acl") or {}
        acl = DocumentACL(
            owner=acl_dict.get("owner"),  # type: ignore[arg-type]
            allowed_users=acl_dict.get("allowed_users") or [],
            allowed_groups=acl_dict.get("allowed_groups") or [],
        )
        return ConnectorDocument(
            id=meta["id"],
            filename=meta["filename"],
            mimetype=meta["mimetype"],
            content=content,
            source_url=meta["source_url"],
            acl=acl,
            modified_time=datetime.fromisoformat(meta["modified_time"])
            if meta.get("modified_time")
            else datetime.now(),
            created_time=datetime.fromisoformat(meta["created_time"])
            if meta.get("created_time")
            else datetime.now(),
            metadata=meta.get("metadata") or {},
        )

    async def setup_subscription(self) -> str:
        resp = await self._call("setup_subscription", {})
        return resp["subscription_id"]

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        resp = await self._call("cleanup_subscription", {"subscription_id": subscription_id})
        return bool(resp.get("ok"))

    async def handle_webhook(self, payload: dict[str, Any]) -> list[str]:
        body_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
        result = await self.process_webhook_full(
            method="POST",
            headers=payload.get("_headers", {}),
            query_params={},
            body_bytes=base64.b64decode(body_b64),
        )
        return result.get("file_ids", [])

    def handle_webhook_validation(
        self, method: str, headers: dict[str, str], query_params: dict[str, str]
    ) -> str | None:
        # Validation is sync per BaseConnector contract. The combined
        # process_webhook_full path handles it on the wire; this method is
        # rarely the entry point in service mode.
        return None

    def extract_webhook_channel_id(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> str | None:
        # Many connectors put the id at a stable JSON path. We can do this
        # without a service round-trip by deferring to the upstream class.
        from openrag_connectors import get as get_connector_cls

        cls = get_connector_cls(self.connector_type)
        # Use a throwaway instance — extract_webhook_channel_id is pure.
        try:
            tmp = cls({})
        except Exception:
            return None
        return tmp.extract_webhook_channel_id(payload, headers)

    # ── Combined webhook fast-path ─────────────────────────────────────────

    async def process_webhook_full(
        self,
        method: str,
        headers: dict[str, str],
        query_params: dict[str, str],
        body_bytes: bytes,
    ) -> dict[str, Any]:
        """One round trip: validation + signature verification + parsing."""
        payload = {
            "method": method,
            "headers": dict(headers),
            "query_params": dict(query_params),
            "body_b64": base64.b64encode(body_bytes).decode(),
            "primary_key": self.config.get("webhook_primary_key"),
            "secondary_key": self.config.get("webhook_secondary_key"),
        }
        url = f"{self.service_url}/v1/{self.connector_type}/webhook/handle"
        async with httpx.AsyncClient(timeout=60) as http:
            r = await http.post(
                url, json=payload, headers={"Authorization": f"Bearer {self.bearer}"}
            )
            r.raise_for_status()
            return r.json()

    # ── OAuth helpers ──────────────────────────────────────────────────────

    def get_auth_url(self) -> str:
        return asyncio.get_event_loop().run_until_complete(self._get_auth_url())

    async def _get_auth_url(self, state: str | None = None) -> str:
        body = await self._build_request_body({"state": state} if state else {})
        url = f"{self.service_url}/v1/{self.connector_type}/oauth/authorize_url"
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(url, json=body, headers={"Authorization": f"Bearer {self.bearer}"})
            r.raise_for_status()
            return r.json()["url"]

    async def handle_oauth_callback(self, auth_code: str) -> dict[str, Any]:
        body = await self._build_request_body({"code": auth_code})
        url = f"{self.service_url}/v1/{self.connector_type}/oauth/callback"
        async with _lock_for(self.connection_id):
            async with httpx.AsyncClient(timeout=60) as http:
                r = await http.post(
                    url, json=body, headers={"Authorization": f"Bearer {self.bearer}"}
                )
                r.raise_for_status()
                data = r.json()
                refreshed = data.get("refreshed_oauth")
                if refreshed:
                    await self._persist_refreshed_dict(refreshed)
                return {"status": data.get("status", "success")}

    @property
    def oauth(self):
        # No local oauth object in service mode.
        return None

    # ── internals ──────────────────────────────────────────────────────────

    async def _build_request_body(self, args: dict[str, Any]) -> dict[str, Any]:
        oauth = await self._load_oauth_state()
        config_payload = {
            "connection_id": self.connection_id,
            "redirect_uri": self.config.get("redirect_uri", "http://localhost"),
            "file_ids": self.config.get("file_ids"),
            "folder_ids": self.config.get("folder_ids"),
            "recursive": self.config.get("recursive", True),
            "webhook_url": self.config.get("webhook_url"),
            "webhook_primary_key": self.config.get("webhook_primary_key"),
            "webhook_secondary_key": self.config.get("webhook_secondary_key"),
        }
        return {"config": config_payload, "oauth": oauth, "args": args}

    async def _load_oauth_state(self) -> dict[str, Any]:
        oauth: dict[str, Any] = {
            "client_id": self.client_id or "",
            "client_secret": self.client_secret or "",
            "token_type": "bearer",
        }
        raw, _ = await self.token_store.load()
        if raw:
            try:
                stored = json.loads(raw)
                oauth.update(
                    {
                        "access_token": stored.get("access_token"),
                        "refresh_token": stored.get("refresh_token"),
                        "token_type": stored.get("token_type", "bearer"),
                        "expires_at": stored.get("expires_at"),
                    }
                )
            except json.JSONDecodeError:
                pass
        return oauth

    async def _call(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        body = await self._build_request_body(args)
        url = f"{self.service_url}/v1/{self.connector_type}/{operation}"
        async with _lock_for(self.connection_id):
            async with httpx.AsyncClient(timeout=120) as http:
                r = await http.post(
                    url, json=body, headers={"Authorization": f"Bearer {self.bearer}"}
                )
                r.raise_for_status()
                data = r.json()
                refreshed = data.get("refreshed_oauth")
                if refreshed:
                    await self._persist_refreshed_dict(refreshed)
                return data

    async def _persist_refreshed(self, refreshed_b64: str) -> None:
        await self._persist_refreshed_dict(json.loads(base64.b64decode(refreshed_b64)))

    async def _persist_refreshed_dict(self, refreshed: dict[str, Any]) -> None:
        to_save = {
            "access_token": refreshed.get("access_token"),
            "refresh_token": refreshed.get("refresh_token"),
            "token_type": refreshed.get("token_type", "bearer"),
            "expires_at": refreshed.get("expires_at"),
        }
        await self.token_store.save(json.dumps(to_save))
