import json
import jwt
import httpx
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class User:
    """User information from OAuth provider"""
    user_id: str  # From OAuth sub claim
    email: str
    name: str
    picture: str = None
    provider: str = "google"
    created_at: datetime = None
    last_login: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_login is None:
            self.last_login = datetime.now()


class SessionManager:
    """Manages user sessions and JWT tokens"""
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self.users: Dict[str, User] = {}  # user_id -> User
        
    async def get_user_info_from_token(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Get user info from Google using access token"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Failed to get user info: {response.status_code} {response.text}")
                return None
                
        except Exception as e:
            print(f"Error getting user info: {e}")
            return None
    
    async def create_user_session(self, access_token: str) -> Optional[str]:
        """Create user session from OAuth access token"""
        user_info = await self.get_user_info_from_token(access_token)
        if not user_info:
            return None
            
        # Create or update user
        user_id = user_info["id"]
        user = User(
            user_id=user_id,
            email=user_info["email"],
            name=user_info["name"],
            picture=user_info.get("picture"),
            provider="google"
        )
        
        # Update last login if user exists
        if user_id in self.users:
            self.users[user_id].last_login = datetime.now()
        else:
            self.users[user_id] = user
        
        # Create JWT token
        token_payload = {
            "user_id": user_id,
            "email": user.email,
            "name": user.name,
            "exp": datetime.utcnow() + timedelta(days=7),  # 7 day expiry
            "iat": datetime.utcnow()
        }
        
        token = jwt.encode(token_payload, self.secret_key, algorithm="HS256")
        return token
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify JWT token and return user info"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        return self.users.get(user_id)
    
    def get_user_from_token(self, token: str) -> Optional[User]:
        """Get user from JWT token"""
        payload = self.verify_token(token)
        if payload:
            return self.get_user(payload["user_id"])
        return None