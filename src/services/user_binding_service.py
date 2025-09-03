"""
User Binding Service
Manages mappings between Google OAuth user IDs and Langflow user IDs
Uses verified Langflow API endpoints: /api/v1/login and /api/v1/users/whoami
"""

import json
import os
from typing import Dict, Optional, Any
import httpx
from config.settings import LANGFLOW_URL, LANGFLOW_KEY

USER_BINDINGS_FILE = "user_bindings.json"

class UserBindingService:
    def __init__(self):
        self.bindings_file = USER_BINDINGS_FILE
        self.bindings = self._load_bindings()

    def _load_bindings(self) -> Dict[str, Any]:
        """Load user bindings from JSON file"""
        try:
            if os.path.exists(self.bindings_file):
                with open(self.bindings_file, 'r') as f:
                    return json.load(f)
            else:
                return {}
        except Exception as e:
            print(f"Error loading user bindings: {e}")
            return {}

    def _save_bindings(self):
        """Save user bindings to JSON file"""
        try:
            with open(self.bindings_file, 'w') as f:
                json.dump(self.bindings, f, indent=2)
            print(f"Saved user bindings to {self.bindings_file}")
        except Exception as e:
            print(f"Error saving user bindings: {e}")

    def get_langflow_user_id(self, google_user_id: str) -> Optional[str]:
        """Get Langflow user ID from Google user ID"""
        return self.bindings.get(google_user_id, {}).get('langflow_user_id')

    def get_google_user_id(self, langflow_user_id: str) -> Optional[str]:
        """Get Google user ID from Langflow user ID (reverse lookup)"""
        for google_id, binding in self.bindings.items():
            if binding.get('langflow_user_id') == langflow_user_id:
                return google_id
        return None

    def create_binding(self, google_user_id: str, langflow_user_id: str, google_user_info: Dict[str, Any]):
        """Create a new binding between Google and Langflow user IDs"""
        self.bindings[google_user_id] = {
            'langflow_user_id': langflow_user_id,
            'google_user_info': {
                'email': google_user_info.get('email'),
                'name': google_user_info.get('name'),
                'picture': google_user_info.get('picture'),
                'verified_email': google_user_info.get('verified_email')
            },
            'created_at': __import__('datetime').datetime.now().isoformat(),
            'last_updated': __import__('datetime').datetime.now().isoformat()
        }
        self._save_bindings()
        print(f"Created binding: Google ID {google_user_id} -> Langflow ID {langflow_user_id}")

    def update_binding(self, google_user_id: str, google_user_info: Dict[str, Any]):
        """Update existing binding with fresh Google user info"""
        if google_user_id in self.bindings:
            self.bindings[google_user_id]['google_user_info'] = {
                'email': google_user_info.get('email'),
                'name': google_user_info.get('name'),
                'picture': google_user_info.get('picture'),
                'verified_email': google_user_info.get('verified_email')
            }
            self.bindings[google_user_id]['last_updated'] = __import__('datetime').datetime.now().isoformat()
            self._save_bindings()
            print(f"Updated binding for Google ID {google_user_id}")

    def has_binding(self, google_user_id: str) -> bool:
        """Check if a binding exists for the Google user ID"""
        return google_user_id in self.bindings

    async def get_langflow_user_info(self, langflow_access_token: str) -> Optional[Dict[str, Any]]:
        """Get current user info from Langflow /me endpoint"""
        if not LANGFLOW_URL:
            print("LANGFLOW_URL not configured")
            return None

        try:
            # Use the correct Langflow endpoint based on source code analysis
            endpoint = "/api/v1/users/whoami"
            
            headers = {}
            if langflow_access_token:
                headers["Authorization"] = f"Bearer {langflow_access_token}"
            elif LANGFLOW_KEY:
                # Try with global Langflow API key if available
                headers["Authorization"] = f"Bearer {LANGFLOW_KEY}"
                headers["x-api-key"] = LANGFLOW_KEY

            async with httpx.AsyncClient() as client:
                url = f"{LANGFLOW_URL.rstrip('/')}{endpoint}"
                print(f"Getting Langflow user info from: {url}")
                
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    user_data = response.json()
                    print(f"Successfully got Langflow user data")
                    return user_data
                else:
                    print(f"Langflow /whoami endpoint returned: {response.status_code} - {response.text}")
                    return None
            
        except Exception as e:
            print(f"Error getting Langflow user info: {e}")
            return None

    async def authenticate_with_langflow(self) -> Optional[str]:
        """Authenticate with Langflow using superuser credentials to get access token"""
        if not LANGFLOW_URL:
            return None

        try:
            from config.settings import LANGFLOW_SUPERUSER, LANGFLOW_SUPERUSER_PASSWORD
            
            if not LANGFLOW_SUPERUSER or not LANGFLOW_SUPERUSER_PASSWORD:
                print("Langflow superuser credentials not configured")
                return None

            # Try to login to Langflow
            login_data = {
                "username": LANGFLOW_SUPERUSER,
                "password": LANGFLOW_SUPERUSER_PASSWORD
            }

            async with httpx.AsyncClient() as client:
                # Use the correct Langflow login endpoint based on source code analysis
                endpoint = "/api/v1/login"
                url = f"{LANGFLOW_URL.rstrip('/')}{endpoint}"
                
                # Try form-encoded data first (standard OAuth2 flow)
                try:
                    response = await client.post(
                        url,
                        data=login_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        access_token = result.get('access_token')
                        if access_token:
                            print(f"Successfully authenticated with Langflow via {endpoint}")
                            return access_token
                    else:
                        print(f"Langflow login returned: {response.status_code} - {response.text}")
                        
                except Exception as e:
                    print(f"Error with form login: {e}")

                # If form login didn't work, try JSON (fallback)
                try:
                    response = await client.post(
                        url,
                        json=login_data,
                        headers={"Content-Type": "application/json"}
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        access_token = result.get('access_token')
                        if access_token:
                            print(f"Successfully authenticated with Langflow via {endpoint} (JSON)")
                            return access_token
                    else:
                        print(f"Langflow login (JSON) returned: {response.status_code} - {response.text}")
                        
                except Exception as e:
                    print(f"Error with JSON login: {e}")

            print("Failed to authenticate with Langflow")
            return None
            
        except Exception as e:
            print(f"Error authenticating with Langflow: {e}")
            return None

    async def ensure_binding(self, google_user_id: str, google_user_info: Dict[str, Any]) -> bool:
        """Ensure a binding exists for the Google user, create if needed"""
        if self.has_binding(google_user_id):
            # Update existing binding with fresh Google info
            self.update_binding(google_user_id, google_user_info)
            return True

        # No binding exists, try to create one
        try:
            # First authenticate with Langflow
            langflow_token = await self.authenticate_with_langflow()
            if not langflow_token:
                print("Could not authenticate with Langflow to create binding")
                return False

            # Get Langflow user info
            langflow_user_info = await self.get_langflow_user_info(langflow_token)
            if not langflow_user_info:
                print("Could not get Langflow user info")
                return False

            # Extract Langflow user ID (try different possible fields)
            langflow_user_id = None
            for id_field in ['id', 'user_id', 'sub', 'username']:
                if id_field in langflow_user_info:
                    langflow_user_id = str(langflow_user_info[id_field])
                    break

            if not langflow_user_id:
                print(f"Could not extract Langflow user ID from: {langflow_user_info}")
                return False

            # Create the binding
            self.create_binding(google_user_id, langflow_user_id, google_user_info)
            return True

        except Exception as e:
            print(f"Error creating binding for Google user {google_user_id}: {e}")
            return False

    def get_binding_info(self, google_user_id: str) -> Optional[Dict[str, Any]]:
        """Get complete binding information for a Google user ID"""
        return self.bindings.get(google_user_id)

    def list_all_bindings(self) -> Dict[str, Any]:
        """Get all user bindings (for admin purposes)"""
        return self.bindings.copy()
        
    def is_langflow_user_id(self, user_id: str) -> bool:
        """Check if user_id appears to be a Langflow UUID"""
        import re
        # Basic UUID pattern check (with or without dashes)
        uuid_pattern = r'^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, user_id.lower().replace('-', '')))
        
    def get_user_type(self, user_id: str) -> str:
        """Determine user type: 'google_oauth', 'langflow_direct', or 'unknown'"""
        if self.has_binding(user_id):
            return "google_oauth"
        elif self.is_langflow_user_id(user_id):
            return "langflow_direct"
        else:
            return "unknown"

# Global instance
user_binding_service = UserBindingService()