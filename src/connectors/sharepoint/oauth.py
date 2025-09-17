import os
import json
import aiofiles
from datetime import datetime
import httpx


class SharePointOAuth:
    """Direct token management for SharePoint, bypassing MSAL cache format"""

    SCOPES = [
        "offline_access",
        "Files.Read.All",
        "Sites.Read.All",
    ]

    AUTH_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_file: str = "sharepoint_token.json",
        authority: str = "https://login.microsoftonline.com/common",  # Keep for compatibility
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.authority = authority  # Keep for compatibility but not used
        self._tokens = None
        self._load_tokens()

    def _load_tokens(self):
        """Load tokens from file"""
        if os.path.exists(self.token_file):
            with open(self.token_file, "r") as f:
                self._tokens = json.loads(f.read())
                print(f"Loaded tokens from {self.token_file}")
        else:
            print(f"No token file found at {self.token_file}")

    async def save_cache(self):
        """Persist tokens to file (renamed for compatibility)"""
        await self._save_tokens()

    async def _save_tokens(self):
        """Save tokens to file"""
        if self._tokens:
            async with aiofiles.open(self.token_file, "w") as f:
                await f.write(json.dumps(self._tokens, indent=2))

    def _is_token_expired(self) -> bool:
        """Check if current access token is expired"""
        if not self._tokens or 'expiry' not in self._tokens:
            return True
        
        expiry_str = self._tokens['expiry']
        # Handle different expiry formats
        try:
            if expiry_str.endswith('Z'):
                expiry_dt = datetime.fromisoformat(expiry_str[:-1])
            else:
                expiry_dt = datetime.fromisoformat(expiry_str)
            
            # Add 5-minute buffer
            import datetime as dt
            now = datetime.now()
            return now >= (expiry_dt - dt.timedelta(minutes=5))
        except:
            return True

    async def _refresh_access_token(self) -> bool:
        """Refresh the access token using refresh token"""
        if not self._tokens or 'refresh_token' not in self._tokens:
            return False

        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self._tokens['refresh_token'],
            'grant_type': 'refresh_token',
            'scope': ' '.join(self.SCOPES)
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.TOKEN_ENDPOINT, data=data)
                response.raise_for_status()
                token_data = response.json()

                # Update tokens
                self._tokens['token'] = token_data['access_token']
                if 'refresh_token' in token_data:
                    self._tokens['refresh_token'] = token_data['refresh_token']
                
                # Calculate expiry
                expires_in = token_data.get('expires_in', 3600)
                import datetime as dt
                expiry = datetime.now() + dt.timedelta(seconds=expires_in)
                self._tokens['expiry'] = expiry.isoformat()

                await self._save_tokens()
                print("Access token refreshed successfully")
                return True

            except Exception as e:
                print(f"Failed to refresh token: {e}")
                return False

    def create_authorization_url(self, redirect_uri: str) -> str:
        """Create authorization URL for OAuth flow"""
        from urllib.parse import urlencode
        
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'scope': ' '.join(self.SCOPES),
            'response_mode': 'query'
        }
        
        auth_url = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        return f"{auth_url}?{urlencode(params)}"

    async def handle_authorization_callback(
        self, authorization_code: str, redirect_uri: str
    ) -> bool:
        """Handle OAuth callback and exchange code for tokens"""
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': authorization_code,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,
            'scope': ' '.join(self.SCOPES)
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.TOKEN_ENDPOINT, data=data)
                response.raise_for_status()
                token_data = response.json()

                # Store tokens in our format
                import datetime as dt
                expires_in = token_data.get('expires_in', 3600)
                expiry = datetime.now() + dt.timedelta(seconds=expires_in)
                
                self._tokens = {
                    'token': token_data['access_token'],
                    'refresh_token': token_data['refresh_token'],
                    'scopes': self.SCOPES,
                    'expiry': expiry.isoformat()
                }

                await self._save_tokens()
                print("Authorization successful, tokens saved")
                return True

            except Exception as e:
                print(f"Authorization failed: {e}")
                return False

    async def is_authenticated(self) -> bool:
        """Check if we have valid credentials"""
        if not self._tokens:
            return False

        # If token is expired, try to refresh
        if self._is_token_expired():
            print("Token expired, attempting refresh...")
            if await self._refresh_access_token():
                return True
            else:
                return False
        
        return True

    def get_access_token(self) -> str:
        """Get current access token"""
        if not self._tokens or 'token' not in self._tokens:
            raise ValueError("No access token available")
        
        if self._is_token_expired():
            raise ValueError("Access token expired and refresh failed")
        
        return self._tokens['token']

    async def revoke_credentials(self):
        """Clear tokens"""
        self._tokens = None
        if os.path.exists(self.token_file):
            os.remove(self.token_file)
