import os
import json
import logging
from typing import Optional, Dict, Any

import aiofiles
import msal

logger = logging.getLogger(__name__)


class SharePointOAuth:
    """Handles Microsoft Graph OAuth authentication flow following Google Drive pattern."""

    # Reserved scopes that must NOT be sent on token or silent calls
    RESERVED_SCOPES = {"openid", "profile", "offline_access"}

    # For PERSONAL Microsoft Accounts (OneDrive consumer):
    # - Use AUTH_SCOPES for interactive auth (consent + refresh token issuance)
    # - Use RESOURCE_SCOPES for acquire_token_silent / refresh paths
    AUTH_SCOPES = ["User.Read", "Files.Read.All", "offline_access"]
    RESOURCE_SCOPES = ["User.Read", "Files.Read.All"]
    SCOPES = AUTH_SCOPES  # Backward compatibility alias

    # Kept for reference; MSAL derives endpoints from `authority`
    AUTH_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_file: str = "sharepoint_token.json",
        authority: str = "https://login.microsoftonline.com/common",
        allow_json_refresh: bool = True,
    ):
        """
        Initialize SharePointOAuth.

        Args:
            client_id: Azure AD application (client) ID.
            client_secret: Azure AD application client secret.
            token_file: Path to persisted token cache file (MSAL cache format).
            authority: Usually "https://login.microsoftonline.com/common" for MSA + org,
                       or tenant-specific for work/school.
            allow_json_refresh: If True, permit one-time migration from legacy flat JSON
                                {"access_token","refresh_token",...}. Otherwise refuse it.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.authority = authority
        self.allow_json_refresh = allow_json_refresh
        self.token_cache = msal.SerializableTokenCache()
        self._current_account = None

        # Initialize MSAL Confidential Client
        self.app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=self.authority,
            token_cache=self.token_cache,
        )

    async def load_credentials(self) -> bool:
        """Load existing credentials from token file (async)."""
        try:
            logger.debug(f"SharePoint OAuth loading credentials from: {self.token_file}")
            if os.path.exists(self.token_file):
                logger.debug(f"Token file exists, reading: {self.token_file}")

                # Read the token file
                async with aiofiles.open(self.token_file, "r") as f:
                    cache_data = await f.read()
                    logger.debug(f"Read {len(cache_data)} chars from token file")

                if cache_data.strip():
                    # 1) Try legacy flat JSON first
                    try:
                        json_data = json.loads(cache_data)
                        if isinstance(json_data, dict) and "refresh_token" in json_data:
                            if self.allow_json_refresh:
                                logger.debug(
                                    "Found legacy JSON refresh_token and allow_json_refresh=True; attempting migration refresh"
                                )
                                return await self._refresh_from_json_token(json_data)
                            else:
                                logger.warning(
                                    "Token file contains a legacy JSON refresh_token, but allow_json_refresh=False. "
                                    "Delete the file and re-auth."
                                )
                                return False
                    except json.JSONDecodeError:
                        logger.debug("Token file is not flat JSON; attempting MSAL cache format")

                    # 2) Try MSAL cache format
                    logger.debug("Attempting MSAL cache deserialization")
                    self.token_cache.deserialize(cache_data)

                    # Get accounts from loaded cache
                    accounts = self.app.get_accounts()
                    logger.debug(f"Found {len(accounts)} accounts in MSAL cache")
                    if accounts:
                        self._current_account = accounts[0]
                        logger.debug(f"Set current account: {self._current_account.get('username', 'no username')}")

                        # IMPORTANT: Use RESOURCE_SCOPES (no reserved scopes) for silent acquisition
                        result = self.app.acquire_token_silent(self.RESOURCE_SCOPES, account=self._current_account)
                        logger.debug(f"Silent token acquisition result keys: {list(result.keys()) if result else 'None'}")
                        if result and "access_token" in result:
                            logger.debug("Silent token acquisition successful")
                            await self.save_cache()
                            return True
                        else:
                            error_msg = (result or {}).get("error") or "No result"
                            logger.warning(f"Silent token acquisition failed: {error_msg}")
                else:
                    logger.debug(f"Token file {self.token_file} is empty")
            else:
                logger.debug(f"Token file does not exist: {self.token_file}")

            return False

        except Exception as e:
            logger.error(f"Failed to load SharePoint credentials: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _refresh_from_json_token(self, token_data: dict) -> bool:
        """
        Use refresh token from a legacy JSON file to get new tokens (one-time migration path).

        Notes:
            - Prefer using an MSAL cache file and acquire_token_silent().
            - This path is only for migrating older refresh_token JSON files.
        """
        try:
            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                logger.error("No refresh_token found in JSON file - cannot refresh")
                logger.error("You must re-authenticate interactively to obtain a valid token")
                return False

            # Use only RESOURCE_SCOPES when refreshing (no reserved scopes)
            refresh_scopes = [s for s in self.RESOURCE_SCOPES if s not in self.RESERVED_SCOPES]
            logger.debug(f"Using refresh token; refresh scopes = {refresh_scopes}")

            result = self.app.acquire_token_by_refresh_token(
                refresh_token=refresh_token,
                scopes=refresh_scopes,
            )

            if result and "access_token" in result:
                logger.debug("Successfully refreshed token via legacy JSON path")
                await self.save_cache()

                accounts = self.app.get_accounts()
                logger.debug(f"After refresh, found {len(accounts)} accounts")
                if accounts:
                    self._current_account = accounts[0]
                    logger.debug(f"Set current account after refresh: {self._current_account.get('username', 'no username')}")
                return True

            # Error handling
            err = (result or {}).get("error_description") or (result or {}).get("error") or "Unknown error"
            logger.error(f"Refresh token failed: {err}")

            if any(code in err for code in ("AADSTS70000", "invalid_grant", "interaction_required")):
                logger.warning(
                    "Refresh denied due to unauthorized/expired scopes or invalid grant. "
                    "Delete the token file and perform interactive sign-in with correct scopes."
                )

            return False

        except Exception as e:
            logger.error(f"Exception during refresh from JSON token: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def save_cache(self):
        """Persist the token cache to file."""
        try:
            # Ensure parent directory exists
            parent = os.path.dirname(os.path.abspath(self.token_file))
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)

            cache_data = self.token_cache.serialize()
            if cache_data:
                async with aiofiles.open(self.token_file, "w") as f:
                    await f.write(cache_data)
                logger.debug(f"Token cache saved to {self.token_file}")
        except Exception as e:
            logger.error(f"Failed to save token cache: {e}")

    def create_authorization_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """Create authorization URL for OAuth flow."""
        # Store redirect URI for later use in callback
        self._redirect_uri = redirect_uri

        kwargs: Dict[str, Any] = {
            # IMPORTANT: interactive auth includes offline_access
            "scopes": self.AUTH_SCOPES,
            "redirect_uri": redirect_uri,
            "prompt": "consent",  # ensure refresh token on first run
        }
        if state:
            kwargs["state"] = state  # Optional CSRF protection

        auth_url = self.app.get_authorization_request_url(**kwargs)

        logger.debug(f"Generated auth URL: {auth_url}")
        logger.debug(f"Auth scopes: {self.AUTH_SCOPES}")

        return auth_url

    async def handle_authorization_callback(
        self, authorization_code: str, redirect_uri: str
    ) -> bool:
        """Handle OAuth callback and exchange code for tokens."""
        try:
            # For code exchange, we pass the same auth scopes as used in the authorize step
            result = self.app.acquire_token_by_authorization_code(
                authorization_code,
                scopes=self.AUTH_SCOPES,
                redirect_uri=redirect_uri,
            )

            if result and "access_token" in result:
                # Store the account for future use
                accounts = self.app.get_accounts()
                if accounts:
                    self._current_account = accounts[0]

                await self.save_cache()
                logger.info("SharePoint OAuth authorization successful")
                return True

            error_msg = (result or {}).get("error_description") or (result or {}).get("error") or "Unknown error"
            logger.error(f"SharePoint OAuth authorization failed: {error_msg}")
            return False

        except Exception as e:
            logger.error(f"Exception during SharePoint OAuth authorization: {e}")
            return False

    async def is_authenticated(self) -> bool:
        """Check if we have valid credentials (simplified like Google Drive)."""
        try:
            # First try to load credentials if we haven't already
            if not self._current_account:
                await self.load_credentials()

            # If we have an account, try to get a token (MSAL will refresh if needed)
            if self._current_account:
                # IMPORTANT: use RESOURCE_SCOPES here
                result = self.app.acquire_token_silent(self.RESOURCE_SCOPES, account=self._current_account)
                if result and "access_token" in result:
                    return True
                else:
                    error_msg = (result or {}).get("error") or "No result returned"
                    logger.debug(f"Token acquisition failed for current account: {error_msg}")

            # Fallback: try without specific account
            result = self.app.acquire_token_silent(self.RESOURCE_SCOPES, account=None)
            if result and "access_token" in result:
                # Update current account if this worked
                accounts = self.app.get_accounts()
                if accounts:
                    self._current_account = accounts[0]
                return True

            return False

        except Exception as e:
            logger.error(f"Authentication check failed: {e}")
            return False

    def get_access_token(self) -> str:
        """Get an access token for Microsoft Graph (simplified like Google Drive)."""
        try:
            # Try with current account first
            if self._current_account:
                result = self.app.acquire_token_silent(self.RESOURCE_SCOPES, account=self._current_account)
                if result and "access_token" in result:
                    return result["access_token"]

            # Fallback: try without specific account
            result = self.app.acquire_token_silent(self.RESOURCE_SCOPES, account=None)
            if result and "access_token" in result:
                return result["access_token"]

            # If we get here, authentication has failed
            error_msg = (result or {}).get("error_description") or (result or {}).get("error") or "No valid authentication"
            raise ValueError(f"Failed to acquire access token: {error_msg}")

        except Exception as e:
            logger.error(f"Failed to get access token: {e}")
            raise

    async def revoke_credentials(self):
        """Clear token cache and remove token file (like Google Drive)."""
        try:
            # Clear in-memory state
            self._current_account = None
            self.token_cache = msal.SerializableTokenCache()

            # Recreate MSAL app with fresh cache
            self.app = msal.ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self.client_secret,
                authority=self.authority,
                token_cache=self.token_cache,
            )

            # Remove token file
            if os.path.exists(self.token_file):
                os.remove(self.token_file)
                logger.info(f"Removed SharePoint token file: {self.token_file}")

        except Exception as e:
            logger.error(f"Failed to revoke SharePoint credentials: {e}")

    def get_service(self) -> str:
        """Return an access token (Graph doesn't need a generated client like Google Drive)."""
        return self.get_access_token()
