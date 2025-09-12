"""
Langflow Message History Service
Simplified service that retrieves message history from Langflow using shared client infrastructure
"""

from typing import List, Dict, Optional, Any

from config.settings import clients
from utils.logging_config import get_logger

logger = get_logger(__name__)

class LangflowHistoryService:
    """Simplified service to retrieve message history from Langflow"""
    
    def __init__(self):
        pass
            
    async def get_user_sessions(self, user_id: str, flow_id: Optional[str] = None) -> List[str]:
        """Get all session IDs for a user's conversations"""
        try:
            params = {}
            if flow_id:
                params["flow_id"] = flow_id
                
            response = await clients.langflow_request(
                "GET",
                "/api/v1/monitor/messages/sessions",
                params=params
            )
            
            if response.status_code == 200:
                session_ids = response.json()
                logger.debug(f"Found {len(session_ids)} total sessions from Langflow")
                return session_ids
            else:
                logger.error(f"Failed to get sessions: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting user sessions: {e}")
            return []
            
    async def get_session_messages(self, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a specific session"""
        try:
            response = await clients.langflow_request(
                "GET",
                "/api/v1/monitor/messages",
                params={
                    "session_id": session_id,
                    "order_by": "timestamp"
                }
            )
            
            if response.status_code == 200:
                messages = response.json()
                # Convert to OpenRAG format
                return self._convert_langflow_messages(messages)
            else:
                logger.error(f"Failed to get messages for session {session_id}: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting session messages: {e}")
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
                
                # Extract function calls from content_blocks if present
                content_blocks = msg.get("content_blocks", [])
                if content_blocks:
                    chunks = []
                    for block in content_blocks:
                        if block.get("title") == "Agent Steps" and block.get("contents"):
                            for content in block["contents"]:
                                if content.get("type") == "tool_use":
                                    # Convert Langflow tool_use format to OpenRAG chunks format
                                    chunk = {
                                        "type": "function",
                                        "function": {
                                            "name": content.get("name", ""),
                                            "arguments": content.get("tool_input", {}),
                                            "response": content.get("output", {})
                                        },
                                        "function_call_result": content.get("output", {}),
                                        "duration": content.get("duration"),
                                        "error": content.get("error")
                                    }
                                    chunks.append(chunk)
                    
                    if chunks:
                        converted_msg["chunks"] = chunks
                        converted_msg["response_data"] = {"tool_calls": chunks}
                
                converted_messages.append(converted_msg)
                
            except Exception as e:
                logger.error(f"Error converting message: {e}")
                continue
                
        return converted_messages
        
    async def get_user_conversation_history(self, user_id: str, flow_id: Optional[str] = None) -> Dict[str, Any]:
        """Get all conversation history for a user, organized by session
        
        Simplified version - gets all sessions and lets the frontend filter by user_id
        """
        try:
            # Get all sessions (no complex filtering needed)
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
                "user_id": user_id
            }
            
        except Exception as e:
            logger.error(f"Error getting user conversation history: {e}")
            return {
                "error": str(e),
                "conversations": []
            }


# Global instance
langflow_history_service = LangflowHistoryService()