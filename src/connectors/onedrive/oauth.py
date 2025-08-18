import os
import aiofiles
from typing import Optional
import msal


class OneDriveOAuth:
    """Handles Microsoft Graph OAuth authentication flow"""

    SCOPES = [
        "offline_access",
        "Files.Read.All",
    ]
    
    AUTH_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def __init__(self, client_id: str, client_secret: str, token_file: str = "onedrive_token.json", authority: str = "https://login.microsoftonline.com/common"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.authority = authority
        self.token_cache = msal.SerializableTokenCache()

        # Load existing cache if available
        if os.path.exists(self.token_file):
            with open(self.token_file, "r") as f:
                self.token_cache.deserialize(f.read())

        self.app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=self.authority,
            token_cache=self.token_cache,
        )

    async def save_cache(self):
        """Persist the token cache to file"""
        async with aiofiles.open(self.token_file, "w") as f:
            await f.write(self.token_cache.serialize())

    def create_authorization_url(self, redirect_uri: str) -> str:
        """Create authorization URL for OAuth flow"""
        return self.app.get_authorization_request_url(self.SCOPES, redirect_uri=redirect_uri)

    async def handle_authorization_callback(self, authorization_code: str, redirect_uri: str) -> bool:
        """Handle OAuth callback and exchange code for tokens"""
        result = self.app.acquire_token_by_authorization_code(
            authorization_code,
            scopes=self.SCOPES,
            redirect_uri=redirect_uri,
        )
        if "access_token" in result:
            await self.save_cache()
            return True
        raise ValueError(result.get("error_description") or "Authorization failed")

    async def is_authenticated(self) -> bool:
        """Check if we have valid credentials"""
        accounts = self.app.get_accounts()
        if not accounts:
            return False
        result = self.app.acquire_token_silent(self.SCOPES, account=accounts[0])
        if "access_token" in result:
            await self.save_cache()
            return True
        return False

    def get_access_token(self) -> str:
        """Get an access token for Microsoft Graph"""
        accounts = self.app.get_accounts()
        if not accounts:
            raise ValueError("Not authenticated")
        result = self.app.acquire_token_silent(self.SCOPES, account=accounts[0])
        if "access_token" not in result:
            raise ValueError(result.get("error_description") or "Failed to acquire access token")
        return result["access_token"]

    async def revoke_credentials(self):
        """Clear token cache and remove token file"""
        self.token_cache.clear()
        if os.path.exists(self.token_file):
            os.remove(self.token_file)
