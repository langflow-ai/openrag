import os
import json
from typing import Optional, Iterable, Sequence
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import aiofiles


class GoogleDriveOAuth:
    """Handles Google Drive OAuth authentication flow with scope-upgrade detection."""

    # Core scopes needed by your connector:
    # - drive.readonly: content/export
    # - drive.metadata.readonly: owners/permissions/parents
    REQUIRED_SCOPES = {
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    }

    # Optional OIDC/userinfo scopes (nice-to-have; keep them if you use identity info elsewhere)
    OPTIONAL_SCOPES = {"openid", "email", "profile"}

    # Final scopes we request during auth
    SCOPES = sorted(list(REQUIRED_SCOPES | OPTIONAL_SCOPES))

    AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

    def __init__(self, client_id: str, client_secret: str, token_file: str = "token.json"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.creds: Optional[Credentials] = None
        self._flow_state: Optional[str] = None
        self._flow: Optional[Flow] = None

    # ---------------------------
    # Internal helpers
    # ---------------------------
    @staticmethod
    def _scopes_satisfied(creds: Credentials, required: Iterable[str]) -> bool:
        """
        Check that the credential's scopes include all required scopes.
        Google sometimes returns None/[] for creds.scopes after refresh; guard for that.
        """
        try:
            got = set(creds.scopes or [])
        except Exception:
            got = set()
        return set(required).issubset(got)

    # ---------------------------
    # Public methods
    # ---------------------------
    async def load_credentials(self) -> Optional[Credentials]:
        """Load existing credentials from token file; refresh if expired.
        If token exists but lacks required scopes, delete it to force re-auth with upgraded scopes.
        """
        if os.path.exists(self.token_file):
            async with aiofiles.open(self.token_file, "r") as f:
                token_data = json.loads(await f.read())

            # Build creds from stored token data (be tolerant of missing fields)
            scopes_from_file: Sequence[str] = token_data.get("scopes") or self.SCOPES
            self.creds = Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                id_token=token_data.get("id_token"),
                token_uri=self.TOKEN_ENDPOINT,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=scopes_from_file,
            )

            # Restore expiry (as naive datetime for google-auth)
            if token_data.get("expiry"):
                try:
                    expiry_dt = datetime.fromisoformat(token_data["expiry"])
                    self.creds.expiry = expiry_dt.replace(tzinfo=None)
                except Exception:
                    # If malformed, let refresh handle it
                    pass

            # If expired and we have a refresh token, try refreshing
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                finally:
                    await self.save_credentials()

            # *** Scope-upgrade detection ***
            if self.creds and not self._scopes_satisfied(self.creds, self.REQUIRED_SCOPES):
                # Old/narrow token — remove it to force a clean re-consent with broader scopes
                try:
                    os.remove(self.token_file)
                except FileNotFoundError:
                    pass
                self.creds = None  # signal caller that we need to re-auth

        return self.creds

    async def save_credentials(self):
        """Save credentials to token file (no client_secret)."""
        if not self.creds:
            return

        token_data = {
            "token": self.creds.token,
            "refresh_token": self.creds.refresh_token,
            "id_token": self.creds.id_token,
            # Persist the scopes we actually have now; sort for determinism
            "scopes": sorted(list(self.creds.scopes or self.SCOPES)),
        }
        if self.creds.expiry:
            token_data["expiry"] = self.creds.expiry.isoformat()

        async with aiofiles.open(self.token_file, "w") as f:
            await f.write(json.dumps(token_data, indent=2))

    def create_authorization_url(self, redirect_uri: str, *, force_consent: bool = True) -> str:
        """Create authorization URL for OAuth flow.
        Set force_consent=True to guarantee Google prompts for the broader scopes (scope upgrade).
        """
        client_config = {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                # Use v2 endpoints consistently
                "auth_uri": self.AUTH_ENDPOINT,
                "token_uri": self.TOKEN_ENDPOINT,
            }
        }

        flow = Flow.from_client_config(client_config, scopes=self.SCOPES, redirect_uri=redirect_uri)

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            # include_granted_scopes=True can cause Google to reuse an old narrow grant.
            # For upgrades, it's safer to disable it when force_consent is True.
            include_granted_scopes="false" if force_consent else "true",
            prompt="consent" if force_consent else None,  # ensure we actually see the consent screen
        )

        self._flow_state = flow.state
        self._flow = flow
        return auth_url

    async def handle_authorization_callback(self, authorization_code: str, state: str) -> bool:
        """Handle OAuth callback and exchange code for tokens."""
        if not self._flow or self._flow_state != state:
            raise ValueError("Invalid or missing OAuth state")

        self._flow.fetch_token(code=authorization_code)
        self.creds = self._flow.credentials
        await self.save_credentials()
        return True

    async def is_authenticated(self) -> bool:
        """Return True if we have a usable credential with all required scopes."""
        if not self.creds:
            await self.load_credentials()
        return bool(self.creds and self.creds.valid and self._scopes_satisfied(self.creds, self.REQUIRED_SCOPES))

    def get_service(self):
        """Get authenticated Google Drive service."""
        if not self.creds or not self.creds.valid or not self._scopes_satisfied(self.creds, self.REQUIRED_SCOPES):
            raise ValueError("Not authenticated with required scopes")
        # cache_discovery=False avoids a deprecation warning chatter in some environments
        return build("drive", "v3", credentials=self.creds, cache_discovery=False)

    async def revoke_credentials(self):
        """Revoke credentials and delete token file."""
        if self.creds:
            try:
                self.creds.revoke(Request())
            except Exception:
                # Revocation is best-effort; continue to clear local token
                pass
        if os.path.exists(self.token_file):
            try:
                os.remove(self.token_file)
            except FileNotFoundError:
                pass
        self.creds = None
