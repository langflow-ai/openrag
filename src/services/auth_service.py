import os
import uuid
import json
import httpx
import aiofiles
from datetime import datetime, timedelta
from typing import Optional
import asyncio

from config.settings import WEBHOOK_BASE_URL, is_no_auth_mode
from session_manager import SessionManager
from services.langflow_mcp_service import LangflowMCPService
from connectors.google_drive.oauth import GoogleDriveOAuth
from connectors.onedrive.oauth import OneDriveOAuth
from connectors.sharepoint.oauth import SharePointOAuth
from connectors.google_drive import GoogleDriveConnector
from connectors.onedrive import OneDriveConnector
from connectors.sharepoint import SharePointConnector


class AuthService:
    def __init__(self, session_manager: SessionManager, connector_service=None, langflow_mcp_service: LangflowMCPService | None = None):
        self.session_manager = session_manager
        self.connector_service = connector_service
        self.used_auth_codes = set()  # Track used authorization codes
        self.langflow_mcp_service = langflow_mcp_service
        self._background_tasks = set()

    async def init_oauth(
        self,
        connector_type: str,
        purpose: str,
        connection_name: str,
        redirect_uri: str,
        user_id: str = None,
    ) -> dict:
        """Initialize OAuth flow for authentication or data source connection"""
        # Check if we're in no-auth mode
        if is_no_auth_mode():
            if purpose == "app_auth":
                raise ValueError(
                    "OAuth credentials not configured. Please add GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET environment variables to enable authentication."
                )
            else:
                raise ValueError(
                    "OAuth credentials not configured. Data source connections require OAuth setup."
                )

        # Validate connector_type based on purpose
        if purpose == "app_auth" and connector_type != "google_drive":
            raise ValueError("Only Google login supported for app authentication")
        elif purpose == "data_source" and connector_type not in [
            "google_drive",
            "onedrive",
            "sharepoint",
        ]:
            raise ValueError(f"Unsupported connector type: {connector_type}")
        elif purpose not in ["app_auth", "data_source"]:
            raise ValueError(f"Unsupported purpose: {purpose}")

        if not redirect_uri:
            raise ValueError("redirect_uri is required")

        # We'll validate client credentials when creating the connector

        # Create connection configuration
        token_file = f"{connector_type}_{purpose}_{uuid.uuid4().hex[:8]}.json"
        config = {
            "token_file": token_file,
            "connector_type": connector_type,
            "purpose": purpose,
            "redirect_uri": redirect_uri,
        }

        # Only add webhook URL if WEBHOOK_BASE_URL is configured
        if WEBHOOK_BASE_URL:
            config["webhook_url"] = (
                f"{WEBHOOK_BASE_URL}/connectors/{connector_type}/webhook"
            )

        # Create connection in manager
        connection_id = (
            await self.connector_service.connection_manager.create_connection(
                connector_type=connector_type,
                name=connection_name,
                config=config,
                user_id=user_id,
            )
        )

        # Get OAuth configuration from connector and OAuth classes
        import os

        # Map connector types to their connector and OAuth classes
        connector_class_map = {
            "google_drive": (GoogleDriveConnector, GoogleDriveOAuth),
            "onedrive": (OneDriveConnector, OneDriveOAuth),
            "sharepoint": (SharePointConnector, SharePointOAuth),
        }

        connector_class, oauth_class = connector_class_map.get(
            connector_type, (None, None)
        )
        if not connector_class or not oauth_class:
            raise ValueError(f"No classes found for connector type: {connector_type}")

        # Get scopes from OAuth class
        scopes = oauth_class.SCOPES

        # Get endpoints from OAuth class
        auth_endpoint = oauth_class.AUTH_ENDPOINT
        token_endpoint = oauth_class.TOKEN_ENDPOINT

        # src/services/auth_service.py
        client_key = getattr(connector_class, "CLIENT_ID_ENV_VAR", None)
        secret_key = getattr(connector_class, "CLIENT_SECRET_ENV_VAR", None)

        def _assert_env_key(name, val):
            if not isinstance(val, str) or not val.strip():
                raise RuntimeError(
                    f"{connector_class.__name__} misconfigured: {name} must be a non-empty string "
                    f"(got {val!r}). Define it as a class attribute on the connector."
                )

        _assert_env_key("CLIENT_ID_ENV_VAR", client_key)
        _assert_env_key("CLIENT_SECRET_ENV_VAR", secret_key)

        client_id = os.getenv(client_key)
        client_secret = os.getenv(secret_key)

        if not client_id or not client_secret:
            raise RuntimeError(
                f"Missing OAuth env vars for {connector_class.__name__}. "
                f"Set {client_key} and {secret_key} in the environment."
            )

        oauth_config = {
            "client_id": client_id,
            "scopes": scopes,
            "redirect_uri": redirect_uri,
            "authorization_endpoint": auth_endpoint,
            "token_endpoint": token_endpoint,
        }

        return {"connection_id": connection_id, "oauth_config": oauth_config}

    async def handle_oauth_callback(
        self,
        connection_id: str,
        authorization_code: str,
        state: str = None,
        request=None,
    ) -> dict:
        """Handle OAuth callback - exchange authorization code for tokens"""
        if not all([connection_id, authorization_code]):
            raise ValueError(
                "Missing required parameters (connection_id, authorization_code)"
            )

        # Check if authorization code has already been used
        if authorization_code in self.used_auth_codes:
            raise ValueError("Authorization code already used")

        # Mark code as used to prevent duplicate requests
        self.used_auth_codes.add(authorization_code)

        try:
            # Get connection config
            connection_config = (
                await self.connector_service.connection_manager.get_connection(
                    connection_id
                )
            )
            if not connection_config:
                raise ValueError("Connection not found")

            # Exchange authorization code for tokens
            redirect_uri = connection_config.config.get("redirect_uri")
            if not redirect_uri:
                raise ValueError("Redirect URI not found in connection config")

            # Get connector to access client credentials and endpoints
            connector = self.connector_service.connection_manager._create_connector(
                connection_config
            )

            # Get token endpoint from connector type
            connector_type = connection_config.connector_type
            connector_class_map = {
                "google_drive": (GoogleDriveConnector, GoogleDriveOAuth),
                "onedrive": (OneDriveConnector, OneDriveOAuth),
                "sharepoint": (SharePointConnector, SharePointOAuth),
            }

            connector_class, oauth_class = connector_class_map.get(
                connector_type, (None, None)
            )
            if not connector_class or not oauth_class:
                raise ValueError(
                    f"No classes found for connector type: {connector_type}"
                )

            token_url = oauth_class.TOKEN_ENDPOINT

            token_payload = {
                "code": authorization_code,
                "client_id": connector.get_client_id(),
                "client_secret": connector.get_client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }

            async with httpx.AsyncClient() as client:
                token_response = await client.post(token_url, data=token_payload)

            if token_response.status_code != 200:
                raise Exception(f"Token exchange failed: {token_response.text}")

            token_data = token_response.json()

            # Store tokens in the token file (without client_secret)
            # Use actual scopes from OAuth response
            granted_scopes = token_data.get("scope")
            if not granted_scopes:
                raise ValueError(
                    f"OAuth provider for {connector_type} did not return granted scopes in token response"
                )

            # OAuth providers typically return scopes as a space-separated string
            scopes = (
                granted_scopes.split(" ")
                if isinstance(granted_scopes, str)
                else granted_scopes
            )

            token_file_data = {
                "token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token"),
                "scopes": scopes,
            }

            # Add expiry if provided
            if token_data.get("expires_in"):
                expiry = datetime.now() + timedelta(
                    seconds=int(token_data["expires_in"])
                )
                token_file_data["expiry"] = expiry.isoformat()

            # Save tokens to file
            token_file_path = connection_config.config["token_file"]
            async with aiofiles.open(token_file_path, "w") as f:
                await f.write(json.dumps(token_file_data, indent=2))

            # Route based on purpose
            purpose = connection_config.config.get("purpose", "data_source")

            if purpose == "app_auth":
                return await self._handle_app_auth(
                    connection_id, connection_config, token_data, request
                )
            else:
                return await self._handle_data_source_auth(
                    connection_id, connection_config
                )

        except Exception as e:
            # Remove used code from set if we failed
            self.used_auth_codes.discard(authorization_code)
            raise e

    async def _handle_app_auth(
        self, connection_id: str, connection_config, token_data: dict, request=None
    ) -> dict:
        """Handle app authentication - create user session"""
        # Extract issuer from redirect_uri in connection config
        redirect_uri = connection_config.config.get("redirect_uri")
        if not redirect_uri:
            raise ValueError("redirect_uri not found in connection config")
        # Get base URL from redirect_uri (remove path)
        from urllib.parse import urlparse

        parsed = urlparse(redirect_uri)
        issuer = f"{parsed.scheme}://{parsed.netloc}"

        jwt_token = await self.session_manager.create_user_session(
            token_data["access_token"], issuer
        )

        if jwt_token:
            # Get the user info to create a persistent connector connection
            user_info = await self.session_manager.get_user_info_from_token(
                token_data["access_token"]
            )

            # Best-effort: update Langflow MCP servers to include user's JWT and owner headers
            try:
                if self.langflow_mcp_service and isinstance(jwt_token, str) and jwt_token.strip():
                    global_vars = {"JWT": jwt_token}
                    global_vars["CONNECTOR_TYPE_URL"] = "url"
                    if user_info:
                        if user_info.get("id"):
                            global_vars["OWNER"] = user_info.get("id")
                        if user_info.get("name"):
                            # OWNER_NAME may contain spaces, which can cause issues in headers.
                            # Alternative: URL-encode the owner name to preserve spaces and special characters.
                            owner_name = user_info.get("name")
                            if owner_name:
                                global_vars["OWNER_NAME"] = str(f"\"{owner_name}\"")
                        if user_info.get("email"):
                            global_vars["OWNER_EMAIL"] = user_info.get("email")

                    # Run in background to avoid delaying login flow
                    task = asyncio.create_task(
                        self.langflow_mcp_service.update_mcp_servers_with_global_vars(global_vars)
                    )
                    # Keep reference until done to avoid premature GC
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
            except Exception:
                # Do not block login on MCP update issues
                pass
            
            response_data = {
                "status": "authenticated",
                "purpose": "app_auth",
                "redirect": "/",
                "jwt_token": jwt_token,  # Include JWT token in response
            }

            if user_info and user_info.get("id"):
                # Convert the temporary auth connection to a persistent OAuth connection
                await self.connector_service.connection_manager.update_connection(
                    connection_id=connection_id,
                    connector_type="google_drive",
                    name=f"Google Drive ({user_info.get('email', 'Unknown')})",
                    user_id=user_info.get("id"),
                    config={
                        **connection_config.config,
                        "purpose": "data_source",
                        "user_email": user_info.get("email"),
                        **(
                            {
                                "webhook_url": f"{WEBHOOK_BASE_URL}/connectors/google_drive/webhook"
                            }
                            if WEBHOOK_BASE_URL
                            else {}
                        ),
                    },
                )
                response_data["google_drive_connection_id"] = connection_id
            else:
                # Fallback: delete connection if we can't get user info
                await self.connector_service.connection_manager.delete_connection(
                    connection_id
                )

            return response_data
        else:
            # Clean up connection if session creation failed
            await self.connector_service.connection_manager.delete_connection(
                connection_id
            )
            raise Exception("Failed to create user session")

    async def _handle_data_source_auth(
        self, connection_id: str, connection_config
    ) -> dict:
        """Handle data source connection - keep the connection for syncing"""
        return {
            "status": "authenticated",
            "connection_id": connection_id,
            "purpose": "data_source",
            "connector_type": connection_config.connector_type,
        }

    async def get_user_info(self, request) -> Optional[dict]:
        """Get current user information from request"""
        # In no-auth mode, return a consistent response
        if is_no_auth_mode():
            return {"authenticated": False, "user": None, "no_auth_mode": True}

        user = getattr(request.state, "user", None)

        if user:
            user_data = {
                "authenticated": True,
                "user": {
                    "user_id": user.user_id,
                    "email": user.email,
                    "name": user.name,
                    "picture": user.picture,
                    "provider": user.provider,
                    "last_login": user.last_login.isoformat()
                    if user.last_login
                    else None,
                },
            }
            
            return user_data
        else:
            return {"authenticated": False, "user": None}
