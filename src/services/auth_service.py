import os
import uuid
import json
import httpx
import aiofiles
from datetime import datetime, timedelta
from typing import Optional

from config.settings import GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, WEBHOOK_BASE_URL
from session_manager import SessionManager

class AuthService:
    def __init__(self, session_manager: SessionManager, connector_service=None):
        self.session_manager = session_manager
        self.connector_service = connector_service
        self.used_auth_codes = set()  # Track used authorization codes

    async def init_oauth(self, provider: str, purpose: str, connection_name: str, 
                        redirect_uri: str, user_id: str = None) -> dict:
        """Initialize OAuth flow for authentication or data source connection"""
        if provider != "google":
            raise ValueError("Unsupported provider")
        
        if not redirect_uri:
            raise ValueError("redirect_uri is required")
        
        if not GOOGLE_OAUTH_CLIENT_ID:
            raise ValueError("Google OAuth client ID not configured")
        
        # Create connection configuration
        token_file = f"{provider}_{purpose}_{uuid.uuid4().hex[:8]}.json"
        config = {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "token_file": token_file,
            "provider": provider,
            "purpose": purpose,
            "redirect_uri": redirect_uri
        }
        
        # Only add webhook URL if WEBHOOK_BASE_URL is configured
        if WEBHOOK_BASE_URL:
            config["webhook_url"] = f"{WEBHOOK_BASE_URL}/connectors/{provider}_drive/webhook"
        
        # Create connection in manager
        connector_type = f"{provider}_drive" if purpose == "data_source" else f"{provider}_auth"
        connection_id = await self.connector_service.connection_manager.create_connection(
            connector_type=connector_type,
            name=connection_name,
            config=config,
            user_id=user_id
        )
        
        # Return OAuth configuration for client-side flow
        scopes = [
            'openid', 'email', 'profile',
            'https://www.googleapis.com/auth/drive.readonly',
            'https://www.googleapis.com/auth/drive.metadata.readonly'
        ]

        oauth_config = {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "scopes": scopes,
            "redirect_uri": redirect_uri,
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_endpoint": "https://oauth2.googleapis.com/token"
        }
        
        return {
            "connection_id": connection_id,
            "oauth_config": oauth_config
        }

    async def handle_oauth_callback(self, connection_id: str, authorization_code: str, 
                                   state: str = None) -> dict:
        """Handle OAuth callback - exchange authorization code for tokens"""
        if not all([connection_id, authorization_code]):
            raise ValueError("Missing required parameters (connection_id, authorization_code)")
        
        # Check if authorization code has already been used
        if authorization_code in self.used_auth_codes:
            raise ValueError("Authorization code already used")
        
        # Mark code as used to prevent duplicate requests
        self.used_auth_codes.add(authorization_code)

        try:
            # Get connection config
            connection_config = await self.connector_service.connection_manager.get_connection(connection_id)
            if not connection_config:
                raise ValueError("Connection not found")

            # Exchange authorization code for tokens
            redirect_uri = connection_config.config.get("redirect_uri")
            if not redirect_uri:
                raise ValueError("Redirect URI not found in connection config")

            token_url = "https://oauth2.googleapis.com/token"
            token_payload = {
                "code": authorization_code,
                "client_id": connection_config.config["client_id"],
                "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            }

            async with httpx.AsyncClient() as client:
                token_response = await client.post(token_url, data=token_payload)

            if token_response.status_code != 200:
                raise Exception(f"Token exchange failed: {token_response.text}")

            token_data = token_response.json()

            # Store tokens in the token file
            token_file_data = {
                "token": token_data["access_token"],
                "refresh_token": token_data.get("refresh_token"),
                "scopes": [
                    "openid", "email", "profile",
                    "https://www.googleapis.com/auth/drive.readonly",
                    "https://www.googleapis.com/auth/drive.metadata.readonly"
                ]
            }

            # Add expiry if provided
            if token_data.get("expires_in"):
                expiry = datetime.now() + timedelta(seconds=int(token_data["expires_in"]))
                token_file_data["expiry"] = expiry.isoformat()

            # Save tokens to file
            token_file_path = connection_config.config["token_file"]
            async with aiofiles.open(token_file_path, 'w') as f:
                await f.write(json.dumps(token_file_data, indent=2))

            # Route based on purpose
            purpose = connection_config.config.get("purpose", "data_source")

            if purpose == "app_auth":
                return await self._handle_app_auth(connection_id, connection_config, token_data)
            else:
                return await self._handle_data_source_auth(connection_id, connection_config)

        except Exception as e:
            # Remove used code from set if we failed
            self.used_auth_codes.discard(authorization_code)
            raise e

    async def _handle_app_auth(self, connection_id: str, connection_config, token_data: dict) -> dict:
        """Handle app authentication - create user session"""
        jwt_token = await self.session_manager.create_user_session(token_data["access_token"])

        if jwt_token:
            # Get the user info to create a persistent Google Drive connection
            user_info = await self.session_manager.get_user_info_from_token(token_data["access_token"])
            user_id = user_info["id"] if user_info else None
            
            response_data = {
                "status": "authenticated",
                "purpose": "app_auth",
                "redirect": "/",
                "jwt_token": jwt_token  # Include JWT token in response
            }
            
            if user_id:
                # Convert the temporary auth connection to a persistent Google Drive connection
                await self.connector_service.connection_manager.update_connection(
                    connection_id=connection_id,
                    connector_type="google_drive",
                    name=f"Google Drive ({user_info.get('email', 'Unknown')})",
                    user_id=user_id,
                    config={
                        **connection_config.config,
                        "purpose": "data_source",
                        "user_email": user_info.get("email"),
                        **({"webhook_url": f"{WEBHOOK_BASE_URL}/connectors/google_drive/webhook"} if WEBHOOK_BASE_URL else {})
                    }
                )
                response_data["google_drive_connection_id"] = connection_id
            else:
                # Fallback: delete connection if we can't get user info
                await self.connector_service.connection_manager.delete_connection(connection_id)
            
            return response_data
        else:
            # Clean up connection if session creation failed
            await self.connector_service.connection_manager.delete_connection(connection_id)
            raise Exception("Failed to create user session")

    async def _handle_data_source_auth(self, connection_id: str, connection_config) -> dict:
        """Handle data source connection - keep the connection for syncing"""
        return {
            "status": "authenticated",
            "connection_id": connection_id,
            "purpose": "data_source",
            "connector_type": connection_config.connector_type
        }
    
    async def get_user_info(self, request) -> Optional[dict]:
        """Get current user information from request"""
        user = getattr(request.state, 'user', None)
        
        if user:
            return {
                "authenticated": True,
                "user": {
                    "user_id": user.user_id,
                    "email": user.email,
                    "name": user.name,
                    "picture": user.picture,
                    "provider": user.provider,
                    "last_login": user.last_login.isoformat() if user.last_login else None
                }
            }
        else:
            return {
                "authenticated": False,
                "user": None
            }