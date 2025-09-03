from config.settings import clients, LANGFLOW_URL, FLOW_ID
from agent import async_chat, async_langflow, async_chat_stream, async_langflow_stream
from auth_context import set_auth_context
import json
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ChatService:
    async def chat(
        self,
        prompt: str,
        user_id: str = None,
        jwt_token: str = None,
        previous_response_id: str = None,
        stream: bool = False,
    ):
        """Handle chat requests using the patched OpenAI client"""
        if not prompt:
            raise ValueError("Prompt is required")

        # Set authentication context for this request so tools can access it
        if user_id and jwt_token:
            set_auth_context(user_id, jwt_token)

        if stream:
            return async_chat_stream(
                clients.patched_async_client,
                prompt,
                user_id,
                previous_response_id=previous_response_id,
            )
        else:
            response_text, response_id = await async_chat(
                clients.patched_async_client,
                prompt,
                user_id,
                previous_response_id=previous_response_id,
            )
            response_data = {"response": response_text}
            if response_id:
                response_data["response_id"] = response_id
            return response_data

    async def langflow_chat(
        self,
        prompt: str,
        user_id: str = None,
        jwt_token: str = None,
        previous_response_id: str = None,
        stream: bool = False,
    ):
        """Handle Langflow chat requests"""
        if not prompt:
            raise ValueError("Prompt is required")

        if not LANGFLOW_URL or not FLOW_ID:
            raise ValueError(
                "LANGFLOW_URL and FLOW_ID environment variables are required"
            )

        # Prepare extra headers for JWT authentication
        extra_headers = {}
        if jwt_token:
            extra_headers["X-LANGFLOW-GLOBAL-VAR-JWT"] = jwt_token

        # Get context variables for filters, limit, and threshold
        from auth_context import (
            get_search_filters,
            get_search_limit,
            get_score_threshold,
        )

        filters = get_search_filters()
        limit = get_search_limit()
        score_threshold = get_score_threshold()

        # Build the complete filter expression like the search service does
        filter_expression = {}
        if filters:
            filter_clauses = []
            # Map frontend filter names to backend field names
            field_mapping = {
                "data_sources": "filename",
                "document_types": "mimetype",
                "owners": "owner",
            }

            for filter_key, values in filters.items():
                if values is not None and isinstance(values, list) and len(values) > 0:
                    # Map frontend key to backend field name
                    field_name = field_mapping.get(filter_key, filter_key)

                    if len(values) == 1:
                        # Single value filter
                        filter_clauses.append({"term": {field_name: values[0]}})
                    else:
                        # Multiple values filter
                        filter_clauses.append({"terms": {field_name: values}})

            if filter_clauses:
                filter_expression["filter"] = filter_clauses

        # Add limit and score threshold to the filter expression (only if different from defaults)
        if limit and limit != 10:  # 10 is the default limit
            filter_expression["limit"] = limit

        if score_threshold and score_threshold != 0:  # 0 is the default threshold
            filter_expression["score_threshold"] = score_threshold

        # Pass the complete filter expression as a single header to Langflow (only if we have something to send)
        if filter_expression:
            logger.info("Sending OpenRAG query filter to Langflow", filter_expression=filter_expression)
            extra_headers["X-LANGFLOW-GLOBAL-VAR-OPENRAG-QUERY-FILTER"] = json.dumps(
                filter_expression
            )

        # Ensure the Langflow client exists; try lazy init if needed
        langflow_client = await clients.ensure_langflow_client()
        if not langflow_client:
            raise ValueError(
                "Langflow client not initialized. Ensure LANGFLOW is reachable or set LANGFLOW_KEY."
            )

        if stream:
            from agent import async_langflow_chat_stream

            return async_langflow_chat_stream(
                langflow_client,
                FLOW_ID,
                prompt,
                user_id,
                extra_headers=extra_headers,
                previous_response_id=previous_response_id,
            )
        else:
            from agent import async_langflow_chat

            response_text, response_id = await async_langflow_chat(
                langflow_client,
                FLOW_ID,
                prompt,
                user_id,
                extra_headers=extra_headers,
                previous_response_id=previous_response_id,
            )
            response_data = {"response": response_text}
            if response_id:
                response_data["response_id"] = response_id
            return response_data

    async def upload_context_chat(
        self,
        document_content: str,
        filename: str,
        user_id: str = None,
        jwt_token: str = None,
        previous_response_id: str = None,
        endpoint: str = "langflow",
    ):
        """Send document content as user message to get proper response_id"""
        document_prompt = f"I'm uploading a document called '{filename}'. Here is its content:\n\n{document_content}\n\nPlease confirm you've received this document and are ready to answer questions about it."

        if endpoint == "langflow":
            # Prepare extra headers for JWT authentication
            extra_headers = {}
            if jwt_token:
                extra_headers["X-LANGFLOW-GLOBAL-VAR-JWT"] = jwt_token
            # Ensure the Langflow client exists; try lazy init if needed
            langflow_client = await clients.ensure_langflow_client()
            if not langflow_client:
                raise ValueError(
                    "Langflow client not initialized. Ensure LANGFLOW is reachable or set LANGFLOW_KEY."
                )
            response_text, response_id = await async_langflow(
                langflow_client,
                FLOW_ID,
                document_prompt,
                extra_headers=extra_headers,
                previous_response_id=previous_response_id,
            )
        else:  # chat
            # Set auth context for chat tools and provide user_id
            if user_id and jwt_token:
                set_auth_context(user_id, jwt_token)
            response_text, response_id = await async_chat(
                clients.patched_async_client,
                document_prompt,
                user_id,
                previous_response_id=previous_response_id,
            )

        return response_text, response_id

    async def get_chat_history(self, user_id: str):
        """Get chat conversation history for a user"""
        from agent import get_user_conversations

        if not user_id:
            return {"error": "User ID is required", "conversations": []}

        conversations_dict = get_user_conversations(user_id)
        logger.debug("Getting chat history for user", user_id=user_id, conversation_count=len(conversations_dict))

        # Convert conversations dict to list format with metadata
        conversations = []
        for response_id, conversation_state in conversations_dict.items():
            # Filter out system messages
            messages = []
            for msg in conversation_state.get("messages", []):
                if msg.get("role") in ["user", "assistant"]:
                    message_data = {
                        "role": msg["role"],
                        "content": msg["content"],
                        "timestamp": msg.get("timestamp").isoformat()
                        if msg.get("timestamp")
                        else None,
                    }
                    if msg.get("response_id"):
                        message_data["response_id"] = msg["response_id"]
                    messages.append(message_data)

            if messages:  # Only include conversations with actual messages
                # Generate title from first user message
                first_user_msg = next(
                    (msg for msg in messages if msg["role"] == "user"), None
                )
                title = (
                    first_user_msg["content"][:50] + "..."
                    if first_user_msg and len(first_user_msg["content"]) > 50
                    else first_user_msg["content"]
                    if first_user_msg
                    else "New chat"
                )

                conversations.append(
                    {
                        "response_id": response_id,
                        "title": title,
                        "endpoint": "chat",
                        "messages": messages,
                        "created_at": conversation_state.get("created_at").isoformat()
                        if conversation_state.get("created_at")
                        else None,
                        "last_activity": conversation_state.get(
                            "last_activity"
                        ).isoformat()
                        if conversation_state.get("last_activity")
                        else None,
                        "previous_response_id": conversation_state.get(
                            "previous_response_id"
                        ),
                        "total_messages": len(messages),
                    }
                )

        # Sort by last activity (most recent first)
        conversations.sort(key=lambda c: c["last_activity"], reverse=True)

        return {
            "user_id": user_id,
            "endpoint": "chat",
            "conversations": conversations,
            "total_conversations": len(conversations),
        }

    async def get_langflow_history(self, user_id: str):
        """Get langflow conversation history for a user - now fetches from both OpenRAG memory and Langflow database"""
        from agent import get_user_conversations
        from services.langflow_history_service import langflow_history_service
        from services.user_binding_service import user_binding_service
        
        if not user_id:
            return {"error": "User ID is required", "conversations": []}
        
        all_conversations = []
        
        try:
            # 1. Get in-memory OpenRAG conversations (current session)
            conversations_dict = get_user_conversations(user_id)
            
            for response_id, conversation_state in conversations_dict.items():
                # Filter out system messages
                messages = []
                for msg in conversation_state.get("messages", []):
                    if msg.get("role") in ["user", "assistant"]:
                        message_data = {
                            "role": msg["role"],
                            "content": msg["content"],
                            "timestamp": msg.get("timestamp").isoformat()
                            if msg.get("timestamp")
                            else None,
                        }
                        if msg.get("response_id"):
                            message_data["response_id"] = msg["response_id"]
                        messages.append(message_data)
                
                if messages:  # Only include conversations with actual messages
                    # Generate title from first user message
                    first_user_msg = next(
                        (msg for msg in messages if msg["role"] == "user"), None
                    )
                    title = (
                        first_user_msg["content"][:50] + "..."
                        if first_user_msg and len(first_user_msg["content"]) > 50
                        else first_user_msg["content"]
                        if first_user_msg
                        else "New chat"
                    )
                    
                    all_conversations.append({
                        "response_id": response_id,
                        "title": title,
                        "endpoint": "langflow",
                        "messages": messages,
                        "created_at": conversation_state.get("created_at").isoformat()
                        if conversation_state.get("created_at")
                        else None,
                        "last_activity": conversation_state.get("last_activity").isoformat()
                        if conversation_state.get("last_activity")
                        else None,
                        "previous_response_id": conversation_state.get("previous_response_id"),
                        "total_messages": len(messages),
                        "source": "openrag_memory"
                    })
            
            # 2. Get historical conversations from Langflow database 
            # (works with both Google-bound users and direct Langflow users)
            print(f"[DEBUG] Attempting to fetch Langflow history for user: {user_id}")
            langflow_history = await langflow_history_service.get_user_conversation_history(user_id)
            
            if langflow_history.get("conversations"):
                for conversation in langflow_history["conversations"]:
                    # Convert Langflow format to OpenRAG format
                    messages = []
                    for msg in conversation.get("messages", []):
                        messages.append({
                            "role": msg["role"],
                            "content": msg["content"],
                            "timestamp": msg.get("timestamp"),
                            "langflow_message_id": msg.get("langflow_message_id"),
                            "source": "langflow"
                        })
                    
                    if messages:
                        first_user_msg = next((msg for msg in messages if msg["role"] == "user"), None)
                        title = (
                            first_user_msg["content"][:50] + "..."
                            if first_user_msg and len(first_user_msg["content"]) > 50
                            else first_user_msg["content"]
                            if first_user_msg
                            else "Langflow chat"
                        )
                        
                        all_conversations.append({
                            "response_id": conversation["session_id"],
                            "title": title,
                            "endpoint": "langflow",
                            "messages": messages,
                            "created_at": conversation.get("created_at"),
                            "last_activity": conversation.get("last_activity"),
                            "total_messages": len(messages),
                            "source": "langflow_database",
                            "langflow_session_id": conversation["session_id"],
                            "langflow_flow_id": conversation.get("flow_id")
                        })
                
                print(f"[DEBUG] Added {len(langflow_history['conversations'])} historical conversations from Langflow")
            elif langflow_history.get("error"):
                print(f"[DEBUG] Could not fetch Langflow history for user {user_id}: {langflow_history['error']}")
            else:
                print(f"[DEBUG] No Langflow conversations found for user {user_id}")
        
        except Exception as e:
            print(f"[ERROR] Failed to fetch Langflow history: {e}")
            # Continue with just in-memory conversations
        
        # Deduplicate conversations by response_id (in-memory takes priority over database)
        deduplicated_conversations = {}
        
        for conversation in all_conversations:
            response_id = conversation.get("response_id")
            if response_id:
                if response_id not in deduplicated_conversations:
                    # First occurrence - add it
                    deduplicated_conversations[response_id] = conversation
                else:
                    # Duplicate found - prioritize in-memory (more recent) over database
                    existing = deduplicated_conversations[response_id]
                    current_source = conversation.get("source")
                    existing_source = existing.get("source")
                    
                    if current_source == "openrag_memory" and existing_source == "langflow_database":
                        # Replace database version with in-memory version
                        deduplicated_conversations[response_id] = conversation
                        print(f"[DEBUG] Replaced database conversation {response_id} with in-memory version")
                    # Otherwise keep existing (in-memory has priority, or first database entry)
            else:
                # No response_id - add with unique key based on content and timestamp
                unique_key = f"no_id_{hash(conversation.get('title', ''))}{conversation.get('created_at', '')}"
                if unique_key not in deduplicated_conversations:
                    deduplicated_conversations[unique_key] = conversation
        
        final_conversations = list(deduplicated_conversations.values())
        
        # Sort by last activity (most recent first)
        final_conversations.sort(key=lambda c: c.get("last_activity", ""), reverse=True)
        
        # Calculate source statistics after deduplication
        sources = {
            "memory": len([c for c in final_conversations if c.get("source") == "openrag_memory"]),
            "langflow_db": len([c for c in final_conversations if c.get("source") == "langflow_database"]),
            "duplicates_removed": len(all_conversations) - len(final_conversations)
        }
        
        if sources["duplicates_removed"] > 0:
            print(f"[DEBUG] Removed {sources['duplicates_removed']} duplicate conversations")
        
        return {
            "user_id": user_id,
            "endpoint": "langflow",
            "conversations": final_conversations,
            "total_conversations": len(final_conversations),
            "sources": sources
        }
