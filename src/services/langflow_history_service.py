"""
Langflow Message History Service
Simplified service that retrieves message history from Langflow using shared client infrastructure
"""

from typing import Any

from api.provider_validation import (
    looks_like_provider_error_content,
    sanitize_provider_error_content,
)
from config.settings import clients
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LangflowHistoryService:
    """Simplified service to retrieve message history from Langflow"""

    def __init__(self):
        pass

    async def get_user_sessions(self, user_id: str, flow_id: str | None = None) -> list[str]:
        """Get all session IDs for a user's conversations"""
        try:
            params = {}
            if flow_id:
                params["flow_id"] = flow_id

            response = await clients.langflow_request(
                "GET", "/api/v1/monitor/messages/sessions", params=params
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

    async def get_session_messages(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        """Get all messages for a specific session"""
        try:
            response = await clients.langflow_request(
                "GET",
                "/api/v1/monitor/messages",
                params={"session_id": session_id, "order_by": "timestamp"},
            )

            if response.status_code == 200:
                messages = response.json()
                # Convert to BomaRAG format
                return self._convert_langflow_messages(messages)
            else:
                logger.error(
                    f"Failed to get messages for session {session_id}: {response.status_code}"
                )
                return []

        except Exception as e:
            logger.error(f"Error getting session messages: {e}")
            return []

    def _convert_langflow_messages(
        self, langflow_messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Convert Langflow messages to BomaRAG format"""
        converted_messages: list[dict[str, Any]] = []

        for msg in langflow_messages:
            try:
                content = msg.get("text", "") or ""
                sender = msg.get("sender")
                is_user = sender == "User"

                # Detect error messages - explicit flag, Error: prefix, or provider failures
                # (including raw JSON payloads that leak from upstream auth/rate-limit errors).
                is_error = False
                if not is_user:
                    is_error = bool(msg.get("error", False)) or looks_like_provider_error_content(
                        content
                    )
                    if is_error:
                        content = sanitize_provider_error_content(content)

                # Map Langflow message format to BomaRAG format
                converted_msg = {
                    "role": "user" if is_user else "assistant",
                    "content": content,
                    "timestamp": msg.get("timestamp"),
                    "langflow_message_id": msg.get("id"),
                    "langflow_session_id": msg.get("session_id"),
                    "langflow_flow_id": msg.get("flow_id"),
                    "sender": sender,
                    "sender_name": msg.get("sender_name"),
                    "source": "langflow",
                    "files": msg.get("files", []),
                    "properties": msg.get("properties", {}),
                    "error": is_error,
                    "edit": msg.get("edit", False),
                }

                # Extract function calls from content_blocks if present
                # Convert to match streaming format: chunk.item.type === "tool_call"
                content_blocks = msg.get("content_blocks", [])
                if content_blocks:
                    chunks = []
                    for block in content_blocks:
                        if block.get("title") == "Agent Steps" and block.get("contents"):
                            for content_item in block["contents"]:
                                if content_item.get("type") == "tool_use":
                                    # Convert Langflow tool_use format to match streaming chunks format
                                    # Frontend expects: chunk.item.type === "tool_call" with tool_name, inputs, results
                                    from utils.langflow_utils import parse_knowledge_chunks

                                    chunk = {
                                        "type": "response.output_item.added",
                                        "item": {
                                            "type": "tool_call",
                                            "tool_name": content_item.get("name", ""),
                                            "inputs": content_item.get("tool_input", {}),
                                            "results": parse_knowledge_chunks(
                                                content_item.get("output", {})
                                            ),
                                            "id": content_item.get("id")
                                            or content_item.get("run_id", ""),
                                            "status": "completed"
                                            if not content_item.get("error")
                                            else "error",
                                        },
                                    }
                                    chunks.append(chunk)

                    if chunks:
                        converted_msg["chunks"] = chunks

                # Langflow often records the same provider failure several times
                # in one session (e.g. embedding + LLM auth retries). Keep one.
                prev = converted_messages[-1] if converted_messages else None
                if (
                    is_error
                    and prev
                    and prev.get("error")
                    and (prev.get("content") or "").strip() == content.strip()
                ):
                    continue

                converted_messages.append(converted_msg)

            except Exception as e:
                logger.error(f"Error converting message: {e}")
                continue

        return converted_messages

    async def get_user_conversation_history(
        self, user_id: str, flow_id: str | None = None
    ) -> dict[str, Any]:
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
                        "source": "langflow",
                    }
                    conversations.append(conversation)

            # Sort by last activity (most recent first)
            conversations.sort(key=lambda c: c.get("last_activity") or "", reverse=True)

            return {
                "conversations": conversations,
                "total_conversations": len(conversations),
                "user_id": user_id,
            }

        except Exception as e:
            logger.error(f"Error getting user conversation history: {e}")
            return {"error": str(e), "conversations": []}


# Global instance
langflow_history_service = LangflowHistoryService()
