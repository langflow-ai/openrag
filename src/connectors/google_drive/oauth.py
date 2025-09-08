import os
import json
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import aiofiles


class GoogleDriveOAuth:
    """Handles Google Drive OAuth authentication flow"""

    SCOPES = [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ]

    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_file: str = "token.json",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.creds: Optional[Credentials] = None

    async def load_credentials(self) -> Optional[Credentials]:
        """Load existing credentials from token file"""
        if os.path.exists(self.token_file):
            async with aiofiles.open(self.token_file, "r") as f:
                token_data = json.loads(await f.read())

            # Create credentials from token data
            self.creds = Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                id_token=token_data.get("id_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,  # Need for refresh
                scopes=token_data.get("scopes", self.SCOPES),
            )

            # Set expiry if available (ensure timezone-naive for Google auth compatibility)
            if token_data.get("expiry"):
                from datetime import datetime

                expiry_dt = datetime.fromisoformat(token_data["expiry"])
                # Remove timezone info to make it naive (Google auth expects naive datetimes)
                self.creds.expiry = expiry_dt.replace(tzinfo=None)

        # If credentials are expired, refresh them
        if self.creds and self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
            await self.save_credentials()

        return self.creds

    async def save_credentials(self):
        """Save credentials to token file (without client_secret)"""
        if self.creds:
            # Create minimal token data without client_secret
            token_data = {
                "token": self.creds.token,
                "refresh_token": self.creds.refresh_token,
                "id_token": self.creds.id_token,
                "scopes": self.creds.scopes,
            }

            # Add expiry if available
            if self.creds.expiry:
                token_data["expiry"] = self.creds.expiry.isoformat()

            async with aiofiles.open(self.token_file, "w") as f:
                await f.write(json.dumps(token_data, indent=2))

    def create_authorization_url(self, redirect_uri: str) -> str:
        """Create authorization URL for OAuth flow"""
        # Create flow from client credentials directly
        client_config = {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

        flow = Flow.from_client_config(
            client_config, scopes=self.SCOPES, redirect_uri=redirect_uri
        )

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",  # Force consent to get refresh token
        )

        # Store flow state for later use
        self._flow_state = flow.state
        self._flow = flow

        return auth_url

    async def handle_authorization_callback(
        self, authorization_code: str, state: str
    ) -> bool:
        """Handle OAuth callback and exchange code for tokens"""
        if not hasattr(self, "_flow") or self._flow_state != state:
            raise ValueError("Invalid OAuth state")

        # Exchange authorization code for credentials
        self._flow.fetch_token(code=authorization_code)
        self.creds = self._flow.credentials

        # Save credentials
        await self.save_credentials()

        return True

    async def is_authenticated(self) -> bool:
        """Check if we have valid credentials"""
        if not self.creds:
            await self.load_credentials()

        return bool(self.creds and self.creds.valid)

    def get_service(self):
        """Get authenticated Google Drive service"""
        if not self.creds or not self.creds.valid:
            raise ValueError("Not authenticated")

        return build("drive", "v3", credentials=self.creds)

    async def revoke_credentials(self):
        """Revoke credentials and delete token file"""
        if self.creds:
            self.creds.revoke(Request())

        if os.path.exists(self.token_file):
            os.remove(self.token_file)

        self.creds = None
