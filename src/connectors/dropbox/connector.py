import json
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from connectors.base import BaseConnector, ConnectorDocument, DocumentACL
from utils.logging_config import get_logger

from .oauth import DropboxOAuth

logger = get_logger(__name__)


class DropboxConnector(BaseConnector):
    """Dropbox connector using OAuth and Dropbox API v2."""

    CLIENT_ID_ENV_VAR = "DROPBOX_OAUTH_CLIENT_ID"
    CLIENT_SECRET_ENV_VAR = "DROPBOX_OAUTH_CLIENT_SECRET"

    CONNECTOR_TYPE = "dropbox"
    CONNECTOR_KIND = "oauth"
    CONNECTOR_NAME = "Dropbox"
    CONNECTOR_DESCRIPTION = "Add knowledge from Dropbox"
    CONNECTOR_ICON = "dropbox"

    @classmethod
    def get_oauth_class(cls):
        return DropboxOAuth

    def __init__(self, config: dict[str, Any]):
        if config is None:
            config = {}
        super().__init__(config)

        from config.paths import get_data_file

        self.client_id = config.get("client_id") or os.getenv(self.CLIENT_ID_ENV_VAR)
        self.client_secret = config.get("client_secret") or os.getenv(
            self.CLIENT_SECRET_ENV_VAR
        )
        token_file = config.get("token_file") or get_data_file("dropbox_token.json")
        Path(token_file).parent.mkdir(parents=True, exist_ok=True)

        self.oauth = (
            DropboxOAuth(self.client_id, self.client_secret, token_file)
            if self.client_id and self.client_secret
            else None
        )
        self.cfg = type(
            "DropboxConfig",
            (),
            {
                "file_ids": config.get("file_ids")
                or config.get("selected_files")
                or config.get("selected_file_ids"),
                "folder_ids": config.get("folder_ids")
                or config.get("selected_folders")
                or config.get("selected_folder_ids"),
            },
        )()
        self._account: dict[str, Any] | None = None

    def get_client_id(self) -> str:
        if self.client_id:
            return self.client_id
        raise ValueError(f"Environment variable {self.CLIENT_ID_ENV_VAR} is not set")

    def get_client_secret(self) -> str:
        if self.client_secret:
            return self.client_secret
        raise ValueError(f"Environment variable {self.CLIENT_SECRET_ENV_VAR} is not set")

    async def authenticate(self) -> bool:
        if not self.oauth:
            self._authenticated = False
            return False

        if not await self.oauth.load_credentials():
            self._authenticated = False
            return False

        try:
            self._account = await self._rpc("users/get_current_account", {})
            self._authenticated = True
            return True
        except Exception as exc:
            logger.warning("[Dropbox] Authentication check failed: %s", exc)
            self._authenticated = False
            return False

    async def _access_token(self) -> str:
        if not self.oauth:
            raise RuntimeError("Dropbox OAuth is not configured")
        if not await self.oauth.is_authenticated():
            if not await self.oauth.load_credentials():
                raise RuntimeError("Dropbox credentials are not available")
        token = self.oauth.get_access_token()
        if not token:
            raise RuntimeError("Dropbox access token is not available")
        return token

    async def _rpc(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"https://api.dropboxapi.com/2/{endpoint}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Dropbox API error ({endpoint}): {response.text}")
        return response.json()

    async def _download(self, path: str) -> tuple[bytes, dict[str, Any]]:
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://content.dropboxapi.com/2/files/download",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Dropbox-API-Arg": json.dumps({"path": path}),
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(f"Dropbox download failed: {response.text}")

        metadata_header = response.headers.get("dropbox-api-result")
        metadata = {}
        if metadata_header:
            metadata = json.loads(metadata_header)
        return response.content, metadata

    async def _list_folder(
        self,
        path: str,
        *,
        recursive: bool,
        limit: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "path": path,
            "recursive": recursive,
            "include_deleted": False,
            "include_has_explicit_shared_members": False,
            "include_mounted_folders": True,
            "include_non_downloadable_files": False,
        }
        if limit:
            payload["limit"] = min(limit, 2000)
        return await self._rpc("files/list_folder", payload)

    async def _list_continue(self, cursor: str) -> dict[str, Any]:
        return await self._rpc("files/list_folder/continue", {"cursor": cursor})

    async def _get_metadata(self, path: str) -> dict[str, Any]:
        return await self._rpc(
            "files/get_metadata",
            {
                "path": path,
                "include_deleted": False,
                "include_has_explicit_shared_members": False,
                "include_media_info": False,
            },
        )

    def _to_file_info(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        tag = entry.get(".tag")
        if tag == "deleted":
            return None

        name = entry.get("name") or entry.get("path_display") or entry.get("id")
        file_id = entry.get("id") or entry.get("path_lower") or entry.get("path_display")
        if not name or not file_id:
            return None

        is_folder = tag == "folder"
        mime_type = (
            "application/vnd.dropbox.folder"
            if is_folder
            else mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        return {
            "id": file_id,
            "name": name,
            "mimeType": mime_type,
            "mimetype": mime_type,
            "path_lower": entry.get("path_lower"),
            "path_display": entry.get("path_display"),
            "size": entry.get("size"),
            "modified_time": entry.get("server_modified") or entry.get("client_modified"),
            "webUrl": self._source_url(entry),
            "isFolder": is_folder,
        }

    def _source_url(self, entry: dict[str, Any]) -> str:
        path_display = entry.get("path_display")
        if path_display:
            return f"https://www.dropbox.com/home{path_display}"
        return "https://www.dropbox.com/home"

    async def _collect_folder_entries(
        self,
        path: str,
        *,
        recursive: bool,
        max_files: int | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        response = await self._list_folder(path, recursive=recursive, limit=max_files)
        entries = response.get("entries", [])
        cursor = response.get("cursor")

        while response.get("has_more") and (not max_files or len(entries) < max_files):
            response = await self._list_continue(response["cursor"])
            entries.extend(response.get("entries", []))
            cursor = response.get("cursor")

        return entries[:max_files] if max_files else entries, cursor

    async def list_files(
        self,
        page_token: str | None = None,
        max_files: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if page_token:
            response = await self._list_continue(page_token)
            entries = response.get("entries", [])
            files = [info for entry in entries if (info := self._to_file_info(entry))]
            files = [f for f in files if not f.get("isFolder")]
            return {
                "files": files[:max_files] if max_files else files,
                "nextPageToken": response.get("cursor") if response.get("has_more") else None,
            }

        selected_ids = self.cfg.file_ids or self.cfg.folder_ids
        if selected_ids:
            files: list[dict[str, Any]] = []
            for item_id in selected_ids:
                metadata = await self._get_metadata(item_id)
                if metadata.get(".tag") == "folder":
                    entries, _ = await self._collect_folder_entries(
                        metadata.get("id") or item_id,
                        recursive=True,
                        max_files=max_files,
                    )
                    files.extend(
                        info
                        for entry in entries
                        if (info := self._to_file_info(entry)) and not info.get("isFolder")
                    )
                else:
                    info = self._to_file_info(metadata)
                    if info:
                        files.append(info)
                if max_files and len(files) >= max_files:
                    break
            return {"files": files[:max_files] if max_files else files, "nextPageToken": None}

        entries, cursor = await self._collect_folder_entries("", recursive=True, max_files=max_files)
        files = [info for entry in entries if (info := self._to_file_info(entry))]
        files = [f for f in files if not f.get("isFolder")]
        return {"files": files, "nextPageToken": cursor}

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        metadata = await self._get_metadata(file_id)
        if metadata.get(".tag") == "folder":
            raise ValueError("Cannot ingest a Dropbox folder directly")

        content, download_metadata = await self._download(file_id)
        metadata = {**metadata, **download_metadata}
        name = metadata.get("name") or file_id
        mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        modified = self._parse_time(metadata.get("server_modified") or metadata.get("client_modified"))
        created = modified

        account = self._account or {}
        email = account.get("email")
        display_name = (account.get("name") or {}).get("display_name")

        return ConnectorDocument(
            id=metadata.get("id") or file_id,
            filename=name,
            mimetype=mime_type,
            content=content,
            source_url=self._source_url(metadata),
            acl=DocumentACL(owner=email, allowed_users=[email] if email else []),
            modified_time=modified,
            created_time=created,
            metadata={
                "connector_type": self.CONNECTOR_TYPE,
                "path_display": metadata.get("path_display"),
                "path_lower": metadata.get("path_lower"),
                "owner_name": display_name,
                "owner_email": email,
            },
        )

    def _parse_time(self, value: str | None) -> datetime:
        if not value:
            return datetime.utcnow()
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return datetime.utcnow()

    async def setup_subscription(self) -> str:
        raise NotImplementedError("Dropbox webhook subscriptions are not implemented")

    async def handle_webhook(self, payload: dict[str, Any]) -> list[str]:
        return []

    def extract_webhook_channel_id(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> str | None:
        return None

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        return True
