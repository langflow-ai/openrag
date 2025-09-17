from pathlib import Path
import httpx
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from ..base import BaseConnector, ConnectorDocument, DocumentACL
from .oauth import OneDriveOAuth


class OneDriveConnector(BaseConnector):
    """OneDrive connector using Microsoft Graph API"""

    CLIENT_ID_ENV_VAR = "MICROSOFT_GRAPH_OAUTH_CLIENT_ID"
    CLIENT_SECRET_ENV_VAR = "MICROSOFT_GRAPH_OAUTH_CLIENT_SECRET"

    # Connector metadata
    CONNECTOR_NAME = "OneDrive"
    CONNECTOR_DESCRIPTION = "Connect your personal OneDrive to sync documents"
    CONNECTOR_ICON = "onedrive"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        token_file = config.get("token_file") or str(project_root / "onedrive_token.json")
        self.oauth = OneDriveOAuth(
            client_id=self.get_client_id(),
            client_secret=self.get_client_secret(),
            token_file=token_file,
        )
        self.subscription_id = config.get("subscription_id") or config.get(
            "webhook_channel_id"
        )
        self.base_url = "https://graph.microsoft.com/v1.0"

    async def authenticate(self) -> bool:
        if await self.oauth.is_authenticated():
            self._authenticated = True
            return True
        return False

    async def setup_subscription(self) -> str:
        if not self._authenticated:
            raise ValueError("Not authenticated")

        webhook_url = self.config.get("webhook_url")
        if not webhook_url:
            raise ValueError("webhook_url required in config for subscriptions")

        expiration = (datetime.utcnow() + timedelta(days=2)).isoformat() + "Z"
        body = {
            "changeType": "created,updated,deleted",
            "notificationUrl": webhook_url,
            "resource": "/me/drive/root",
            "expirationDateTime": expiration,
            "clientState": str(uuid.uuid4()),
        }

        token = self.oauth.get_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/subscriptions",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        self.subscription_id = data["id"]
        return self.subscription_id

    async def list_files(
        self, page_token: Optional[str] = None, limit: int = 100
    ) -> Dict[str, Any]:
        if not self._authenticated:
            raise ValueError("Not authenticated")

        params = {"$top": str(limit)}
        if page_token:
            params["$skiptoken"] = page_token

        token = self.oauth.get_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/me/drive/root/children",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        files = []
        for item in data.get("value", []):
            if item.get("file"):
                files.append(
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "mimeType": item.get("file", {}).get(
                            "mimeType", "application/octet-stream"
                        ),
                        "webViewLink": item.get("webUrl"),
                        "createdTime": item.get("createdDateTime"),
                        "modifiedTime": item.get("lastModifiedDateTime"),
                    }
                )

        next_token = None
        next_link = data.get("@odata.nextLink")
        if next_link:
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(next_link)
            next_token = parse_qs(parsed.query).get("$skiptoken", [None])[0]

        return {"files": files, "nextPageToken": next_token}

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        if not self._authenticated:
            raise ValueError("Not authenticated")

        token = self.oauth.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            meta_resp = await client.get(
                f"{self.base_url}/me/drive/items/{file_id}", headers=headers
            )
            meta_resp.raise_for_status()
            metadata = meta_resp.json()

            content_resp = await client.get(
                f"{self.base_url}/me/drive/items/{file_id}/content", headers=headers
            )
            content_resp.raise_for_status()
            content = content_resp.content

            perm_resp = await client.get(
                f"{self.base_url}/me/drive/items/{file_id}/permissions", headers=headers
            )
            perm_resp.raise_for_status()
            permissions = perm_resp.json()

        acl = self._parse_permissions(metadata, permissions)
        modified = datetime.fromisoformat(
            metadata["lastModifiedDateTime"].replace("Z", "+00:00")
        ).replace(tzinfo=None)
        created = datetime.fromisoformat(
            metadata["createdDateTime"].replace("Z", "+00:00")
        ).replace(tzinfo=None)

        document = ConnectorDocument(
            id=metadata["id"],
            filename=metadata["name"],
            mimetype=metadata.get("file", {}).get(
                "mimeType", "application/octet-stream"
            ),
            content=content,
            source_url=metadata.get("webUrl"),
            acl=acl,
            modified_time=modified,
            created_time=created,
            metadata={"size": metadata.get("size")},
        )
        return document

    def _parse_permissions(
        self, metadata: Dict[str, Any], permissions: Dict[str, Any]
    ) -> DocumentACL:
        acl = DocumentACL()
        owner = metadata.get("createdBy", {}).get("user", {}).get("email")
        if owner:
            acl.owner = owner
        for perm in permissions.get("value", []):
            role = perm.get("roles", ["read"])[0]
            grantee = perm.get("grantedToV2") or perm.get("grantedTo")
            if not grantee:
                continue
            user = grantee.get("user")
            if user and user.get("email"):
                acl.user_permissions[user["email"]] = role
            group = grantee.get("group")
            if group and group.get("email"):
                acl.group_permissions[group["email"]] = role
        return acl

    def handle_webhook_validation(
        self, request_method: str, headers: Dict[str, str], query_params: Dict[str, str]
    ) -> Optional[str]:
        """Handle Microsoft Graph webhook validation"""
        if request_method == "GET":
            validation_token = query_params.get("validationtoken") or query_params.get(
                "validationToken"
            )
            if validation_token:
                return validation_token
        return None

    def extract_webhook_channel_id(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Optional[str]:
        """Extract SharePoint subscription ID from webhook payload"""
        values = payload.get("value", [])
        return values[0].get("subscriptionId") if values else None

    async def handle_webhook(self, payload: Dict[str, Any]) -> List[str]:
        values = payload.get("value", [])
        file_ids = []
        for item in values:
            resource_data = item.get("resourceData", {})
            file_id = resource_data.get("id")
            if file_id:
                file_ids.append(file_id)
        return file_ids

    async def cleanup_subscription(
        self, subscription_id: str, resource_id: str = None
    ) -> bool:
        if not self._authenticated:
            return False
        token = self.oauth.get_access_token()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self.base_url}/subscriptions/{subscription_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        return resp.status_code in (200, 204)
