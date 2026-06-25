import json
import os
from datetime import datetime, timedelta
from typing import Any

import httpx

from utils.logging_config import get_logger

logger = get_logger(__name__)


class DropboxOAuth:
    """Handles Dropbox OAuth token storage and refresh."""

    SCOPES = ["account_info.read", "files.metadata.read", "files.content.read"]
    AUTH_ENDPOINT = "https://www.dropbox.com/oauth2/authorize"
    TOKEN_ENDPOINT = "https://api.dropboxapi.com/oauth2/token"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_file: str = "dropbox_token.json",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.token_data: dict[str, Any] | None = None

    async def load_credentials(self) -> bool:
        from utils.encryption import read_encrypted_file

        raw_data, needs_upgrade = await read_encrypted_file(self.token_file)
        if not raw_data:
            return False

        try:
            self.token_data = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("[Dropbox] Stored token file is invalid JSON")
            self.token_data = None
            return False

        if needs_upgrade:
            await self.save_credentials()

        if self._is_expired():
            if self.token_data.get("refresh_token"):
                return await self.refresh_access_token()
            return False

        return bool(self.token_data.get("token"))

    async def save_credentials(self) -> None:
        if not self.token_data:
            return

        from utils.encryption import write_encrypted_file

        parent = os.path.dirname(os.path.abspath(self.token_file))
        if parent:
            os.makedirs(parent, exist_ok=True)
        await write_encrypted_file(self.token_file, json.dumps(self.token_data))

    def _is_expired(self) -> bool:
        if not self.token_data or not self.token_data.get("expiry"):
            return False
        try:
            expiry = datetime.fromisoformat(self.token_data["expiry"])
        except ValueError:
            return True
        return datetime.utcnow() >= expiry

    async def refresh_access_token(self) -> bool:
        if not self.token_data or not self.token_data.get("refresh_token"):
            return False

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.token_data["refresh_token"],
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.TOKEN_ENDPOINT, data=payload)

        if response.status_code != 200:
            logger.warning("[Dropbox] Token refresh failed: %s", response.text)
            return False

        refreshed = response.json()
        self.token_data["token"] = refreshed["access_token"]
        if refreshed.get("expires_in"):
            expiry = datetime.utcnow() + timedelta(seconds=int(refreshed["expires_in"]))
            self.token_data["expiry"] = expiry.isoformat()
        if refreshed.get("scope"):
            scope = refreshed["scope"]
            self.token_data["scopes"] = scope.split(" ") if isinstance(scope, str) else scope

        await self.save_credentials()
        return True

    async def is_authenticated(self) -> bool:
        if not self.token_data:
            await self.load_credentials()
        return bool(self.token_data and self.token_data.get("token") and not self._is_expired())

    def get_access_token(self) -> str | None:
        if not self.token_data:
            return None
        return self.token_data.get("token")
