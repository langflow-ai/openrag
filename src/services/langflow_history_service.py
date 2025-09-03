"""
Langflow Message History Service
Retrieves message history from Langflow's database using user bindings
"""

import asyncio
import httpx
from typing import List, Dict, Optional, Any
from datetime import datetime

from config.settings import LANGFLOW_URL, LANGFLOW_KEY, LANGFLOW_SUPERUSER, LANGFLOW_SUPERUSER_PASSWORD
from services.user_binding_service import user_binding_service


class LangflowHistoryService:
    """Service to retrieve message history from Langflow using user bindings"""
    
    def __init__(self):
        self.langflow_url = LANGFLOW_URL
        self.auth_token = None
        
    def _resolve_langflow_user_id(self, user_id: str) -> Optional[str]:
        """Resolve user_id to Langflow user ID
        
        Args:
            user_id: Either Google user ID or direct Langflow user ID
            
        Returns:
            Langflow user ID or None
        """
        # First, check if this is already a Langflow user ID by checking UUID format
        if self._is_uuid_format(user_id):
            print(f"User ID {user_id} appears to be a Langflow UUID, using directly")
            return user_id
            
        # Otherwise, try to get Langflow user ID from Google binding
        langflow_user_id = user_binding_service.get_langflow_user_id(user_id)
        if langflow_user_id:
            print(f"Found Langflow binding for Google user {user_id}: {langflow_user_id}")
            return langflow_user_id
            
        print(f"No Langflow user ID found for {user_id}")
        return None
        
    def _is_uuid_format(self, user_id: str) -> bool:
        """Check if string looks like a UUID (Langflow user ID format)"""
        import re
        # Basic UUID pattern check (with or without dashes)
        uuid_pattern = r'^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$'
        return bool(re.match(uuid_pattern, user_id.lower().replace('-', '')))
        
    async def _authenticate(self) -> Optional[str]:
        """Authenticate with Langflow and get access token"""
        if self.auth_token:
            return self.auth_token
            
        if not all([LANGFLOW_SUPERUSER, LANGFLOW_SUPERUSER_PASSWORD]):
            print("Missing Langflow superuser credentials")
            return None
            
        try:
            login_data = {
                "username": LANGFLOW_SUPERUSER,
                "password": LANGFLOW_SUPERUSER_PASSWORD
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.langflow_url.rstrip('/')}/api/v1/login",
                    data=login_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    self.auth_token = result.get('access_token')
                    print(f"Successfully authenticated with Langflow for history retrieval")
                    return self.auth_token
                else:
                    print(f"Langflow authentication failed: {response.status_code}")
                    return None
                    
        except Exception as e:
            print(f"Error authenticating with Langflow: {e}")
            return None
            
    async def get_user_sessions(self, user_id: str, flow_id: Optional[str] = None) -> List[str]:
        """Get all session IDs for a user's conversations
        
        Args:
            user_id: Either Google user ID or direct Langflow user ID
        """
        # Determine the Langflow user ID
        langflow_user_id = self._resolve_langflow_user_id(user_id)
        if not langflow_user_id:
            print(f"No Langflow user found for user: {user_id}")
            return []
            
        token = await self._authenticate()
        if not token:
            return []
            
        try:
            headers = {"Authorization": f"Bearer {token}"}
            params = {}
            
            if flow_id:
                params["flow_id"] = flow_id
                
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.langflow_url.rstrip('/')}/api/v1/monitor/messages/sessions",
                    headers=headers,
                    params=params
                )
                
                if response.status_code == 200:
                    session_ids = response.json()
                    
                    # Filter sessions to only include those belonging to the user
                    user_sessions = await self._filter_sessions_by_user(session_ids, langflow_user_id, token)
                    print(f"Found {len(user_sessions)} sessions for user {user_id} (Langflow ID: {langflow_user_id})")
                    return user_sessions
                else:
                    print(f"Failed to get sessions: {response.status_code} - {response.text}")
                    return []
                    
        except Exception as e:
            print(f"Error getting user sessions: {e}")
            return []
            
    async def _filter_sessions_by_user(self, session_ids: List[str], langflow_user_id: str, token: str) -> List[str]:
        """Filter session IDs to only include those belonging to the specified user"""
        user_sessions = []
        
        try:
            headers = {"Authorization": f"Bearer {token}"}
            
            async with httpx.AsyncClient() as client:
                for session_id in session_ids:
                    # Get a sample message from this session to check flow ownership
                    response = await client.get(
                        f"{self.langflow_url.rstrip('/')}/api/v1/monitor/messages",
                        headers=headers,
                        params={
                            "session_id": session_id,
                            "order_by": "timestamp"
                        }
                    )
                    
                    if response.status_code == 200:
                        messages = response.json()
                        if messages and len(messages) > 0:
                            # Check if this session belongs to the user via flow ownership
                            flow_id = messages[0].get('flow_id')
                            if flow_id and await self._is_user_flow(flow_id, langflow_user_id, token):
                                user_sessions.append(session_id)
                                
        except Exception as e:
            print(f"Error filtering sessions by user: {e}")
            
        return user_sessions
        
    async def _is_user_flow(self, flow_id: str, langflow_user_id: str, token: str) -> bool:
        """Check if a flow belongs to the specified user"""
        try:
            headers = {"Authorization": f"Bearer {token}"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.langflow_url.rstrip('/')}/api/v1/flows/{flow_id}",
                    headers=headers
                )
                
                if response.status_code == 200:
                    flow_data = response.json()
                    return flow_data.get('user_id') == langflow_user_id
                    
        except Exception as e:
            print(f"Error checking flow ownership: {e}")
            
        return False
        
    async def get_session_messages(self, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a specific session"""
        # Verify user has access to this session
        langflow_user_id = self._resolve_langflow_user_id(user_id)
        if not langflow_user_id:
            return []
            
        token = await self._authenticate()
        if not token:
            return []
            
        try:
            headers = {"Authorization": f"Bearer {token}"}
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.langflow_url.rstrip('/')}/api/v1/monitor/messages",
                    headers=headers,
                    params={
                        "session_id": session_id,
                        "order_by": "timestamp"
                    }
                )
                
                if response.status_code == 200:
                    messages = response.json()
                    
                    # Verify user owns this session (security check)
                    if messages and len(messages) > 0:
                        flow_id = messages[0].get('flow_id')
                        if not await self._is_user_flow(flow_id, langflow_user_id, token):
                            print(f"User {user_id} does not own session {session_id}")
                            return []
                    
                    # Convert to OpenRAG format
                    return self._convert_langflow_messages(messages)
                else:
                    print(f"Failed to get messages for session {session_id}: {response.status_code}")
                    return []
                    
        except Exception as e:
            print(f"Error getting session messages: {e}")
            return []
            
    def _convert_langflow_messages(self, langflow_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert Langflow messages to OpenRAG format"""
        converted_messages = []
        
        for msg in langflow_messages:
            try:
                # Map Langflow message format to OpenRAG format
                converted_msg = {
                    "role": "user" if msg.get("sender") == "User" else "assistant",
                    "content": msg.get("text", ""),
                    "timestamp": msg.get("timestamp"),
                    "langflow_message_id": msg.get("id"),
                    "langflow_session_id": msg.get("session_id"),
                    "langflow_flow_id": msg.get("flow_id"),
                    "sender": msg.get("sender"),
                    "sender_name": msg.get("sender_name"),
                    "files": msg.get("files", []),
                    "properties": msg.get("properties", {}),
                    "error": msg.get("error", False),
                    "edit": msg.get("edit", False)
                }
                converted_messages.append(converted_msg)
                
            except Exception as e:
                print(f"Error converting message: {e}")
                continue
                
        return converted_messages
        
    async def get_user_conversation_history(self, user_id: str, flow_id: Optional[str] = None) -> Dict[str, Any]:
        """Get all conversation history for a user, organized by session"""
        langflow_user_id = self._resolve_langflow_user_id(user_id)
        if not langflow_user_id:
            return {
                "error": f"No Langflow user found for {user_id}",
                "conversations": []
            }
            
        try:
            # Get all user sessions
            session_ids = await self.get_user_sessions(user_id, flow_id)
            
            conversations = []
            for session_id in session_ids:
                messages = await self.get_session_messages(user_id, session_id)
                if messages:
                    # Create conversation metadata
                    first_message = messages[0] if messages else None
                    last_message = messages[-1] if messages else None
                    
                    conversation = {
                        "session_id": session_id,
                        "langflow_session_id": session_id,  # For compatibility
                        "response_id": session_id,  # Map session_id to response_id for frontend compatibility
                        "messages": messages,
                        "message_count": len(messages),
                        "created_at": first_message.get("timestamp") if first_message else None,
                        "last_activity": last_message.get("timestamp") if last_message else None,
                        "flow_id": first_message.get("langflow_flow_id") if first_message else None,
                        "source": "langflow"
                    }
                    conversations.append(conversation)
            
            # Sort by last activity (most recent first)
            conversations.sort(key=lambda c: c.get("last_activity", ""), reverse=True)
            
            return {
                "conversations": conversations,
                "total_conversations": len(conversations),
                "langflow_user_id": langflow_user_id,
                "user_id": user_id
            }
            
        except Exception as e:
            print(f"Error getting user conversation history: {e}")
            return {
                "error": str(e),
                "conversations": []
            }


# Global instance
langflow_history_service = LangflowHistoryService()