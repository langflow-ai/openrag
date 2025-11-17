import json
from config.settings import NUDGES_FLOW_ID, clients, LANGFLOW_URL, LANGFLOW_CHAT_FLOW_ID
from agent import async_chat, async_langflow, async_chat_stream
from auth_context import set_auth_context
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

        if not LANGFLOW_URL or not LANGFLOW_CHAT_FLOW_ID:
            raise ValueError(
                "LANGFLOW_URL and LANGFLOW_CHAT_FLOW_ID environment variables are required"
            )

        # Prepare extra headers for JWT authentication
        extra_headers = {}
        if jwt_token:
            extra_headers["X-LANGFLOW-GLOBAL-VAR-JWT"] = jwt_token

        # Get context variables for filters, limit, and threshold
        from auth_context import (
            get_score_threshold,
            get_search_filters,
            get_search_limit,
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
        logger.info(
            "Sending OpenRAG query filter to Langflow",
            filter_expression=filter_expression,
        )
        extra_headers["X-LANGFLOW-GLOBAL-VAR-OPENRAG-QUERY-FILTER"] = json.dumps(
            filter_expression
        )
        logger.info(f"[LF] Extra headers {extra_headers}")
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
                LANGFLOW_CHAT_FLOW_ID,
                prompt,
                user_id,
                extra_headers=extra_headers,
                previous_response_id=previous_response_id,
            )
        else:
            from agent import async_langflow_chat

            response_text, response_id = await async_langflow_chat(
                langflow_client,
                LANGFLOW_CHAT_FLOW_ID,
                prompt,
                user_id,
                extra_headers=extra_headers,
                previous_response_id=previous_response_id,
            )
            response_data = {"response": response_text}
            if response_id:
                response_data["response_id"] = response_id
            return response_data

    async def langflow_nudges_chat(
        self,
        user_id: str = None,
        jwt_token: str = None,
        previous_response_id: str = None,
        filters: dict = None,
        limit: int = None,
        score_threshold: float = None,
    ):
        """Handle Langflow nudges chat requests with knowledge filters"""

        if not LANGFLOW_URL or not NUDGES_FLOW_ID:
            raise ValueError(
                "LANGFLOW_URL and NUDGES_FLOW_ID environment variables are required"
            )

        # Prepare extra headers for JWT authentication
        extra_headers = {}
        if jwt_token:
            extra_headers["X-LANGFLOW-GLOBAL-VAR-JWT"] = jwt_token

        # Build the complete filter expression like the chat service does
        filter_expression = {}
        has_user_filters = False
        filter_clauses = []

        if filters:
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
                has_user_filters = True

        # If no user filters are active, exclude sample data from nudges
        if not has_user_filters:
            # Add a bool query with must_not to exclude sample data
            filter_clauses.append({
                "bool": {
                    "must_not": [
                        {"term": {"is_sample_data": "true"}}
                    ]
                }
            })
            logger.info("Excluding sample data from nudges (no user filters active)")

        # Set the filter clauses if we have any
        if filter_clauses:
            filter_expression["filter"] = filter_clauses

        # Add limit and score threshold to the filter expression (only if different from defaults)
        if limit and limit != 10:  # 10 is the default limit
            filter_expression["limit"] = limit

        if score_threshold and score_threshold != 0:  # 0 is the default threshold
            filter_expression["score_threshold"] = score_threshold

        # Pass the complete filter expression as a single header to Langflow (only if we have something to send)
        logger.info(
            "Sending OpenRAG query filter to Langflow nudges",
            filter_expression=filter_expression,
        )
        extra_headers["X-LANGFLOW-GLOBAL-VAR-OPENRAG-QUERY-FILTER"] = json.dumps(
            filter_expression
        )
        logger.info(f"[NUDGES] Extra headers {extra_headers}")

        # Ensure the Langflow client exists; try lazy init if needed
        langflow_client = await clients.ensure_langflow_client()
        if not langflow_client:
            raise ValueError(
                "Langflow client not initialized. Ensure LANGFLOW is reachable or set LANGFLOW_KEY."
            )
        prompt = ""
        if previous_response_id:
            from agent import get_conversation_thread

            conversation_history = get_conversation_thread(
                user_id, previous_response_id
            )
            if conversation_history:
                conversation_history = "\n".join(
                    [
                        f"{msg['role']}: {msg['content']}"
                        for msg in conversation_history["messages"]
                        if msg["role"] in ["user", "assistant"]
                    ]
                )
                prompt = f"{conversation_history}"

        from agent import async_langflow_chat


        response_text, response_id = await async_langflow_chat(
            langflow_client,
            NUDGES_FLOW_ID,
            prompt,
            user_id,
            extra_headers=extra_headers,
            store_conversation=False,
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
                langflow_client=langflow_client,
                flow_id=LANGFLOW_CHAT_FLOW_ID,
                prompt=document_prompt,
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
        from agent import active_conversations, get_user_conversations

        if not user_id:
            return {"error": "User ID is required", "conversations": []}

        # Get metadata from persistent storage
        conversations_dict = get_user_conversations(user_id)

        # Get in-memory conversations (with function calls)
        in_memory_conversations = active_conversations.get(user_id, {})

        logger.debug(
            "Getting chat history for user",
            user_id=user_id,
            persistent_count=len(conversations_dict),
            in_memory_count=len(in_memory_conversations),
        )

        # Convert conversations dict to list format with metadata
        conversations = []

        # First, process in-memory conversations (they have function calls)
        for response_id, conversation_state in in_memory_conversations.items():
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

                    # Include function call data if present
                    if msg.get("chunks"):
                        message_data["chunks"] = msg["chunks"]
                    if msg.get("response_data"):
                        message_data["response_data"] = msg["response_data"]

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
                        "source": "in_memory",
                    }
                )

        # Then, add any persistent metadata that doesn't have in-memory data
        for response_id, metadata in conversations_dict.items():
            if response_id not in in_memory_conversations:
                # This is metadata-only conversation (no function calls)
                conversations.append(
                    {
                        "response_id": response_id,
                        "title": metadata.get("title", "New Chat"),
                        "endpoint": "chat",
                        "messages": [],  # No messages in metadata-only
                        "created_at": metadata.get("created_at"),
                        "last_activity": metadata.get("last_activity"),
                        "previous_response_id": metadata.get("previous_response_id"),
                        "total_messages": metadata.get("total_messages", 0),
                        "source": "metadata_only",
                    }
                )

        # Sort by last activity (most recent first)
        conversations.sort(key=lambda c: c.get("last_activity", ""), reverse=True)

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

        if not user_id:
            return {"error": "User ID is required", "conversations": []}

        all_conversations = []

        try:
            # 1. Get local conversation metadata (no actual messages stored here)
            conversations_dict = get_user_conversations(user_id)
            local_metadata = {}

            for response_id, conversation_metadata in conversations_dict.items():
                # Store metadata for later use with Langflow data
                local_metadata[response_id] = conversation_metadata

            # 2. Get actual conversations from Langflow database (source of truth for messages)
            logger.debug(f"Attempting to fetch Langflow history for user: {user_id}")
            langflow_history = (
                await langflow_history_service.get_user_conversation_history(
                    user_id, flow_id=LANGFLOW_CHAT_FLOW_ID
                )
            )

            if langflow_history.get("conversations"):
                for conversation in langflow_history["conversations"]:
                    session_id = conversation["session_id"]

                    # Only process sessions that belong to this user (exist in local metadata)
                    if session_id not in local_metadata:
                        continue

                    # Use Langflow messages (with function calls) as source of truth
                    messages = []
                    for msg in conversation.get("messages", []):
                        message_data = {
                            "role": msg["role"],
                            "content": msg["content"],
                            "timestamp": msg.get("timestamp"),
                            "langflow_message_id": msg.get("langflow_message_id"),
                            "source": "langflow",
                        }

                        # Include function call data if present
                        if msg.get("chunks"):
                            message_data["chunks"] = msg["chunks"]
                        if msg.get("response_data"):
                            message_data["response_data"] = msg["response_data"]

                        messages.append(message_data)

                    if messages:
                        # Use local metadata if available, otherwise generate from Langflow data
                        metadata = local_metadata.get(session_id, {})

                        if not metadata.get("title"):
                            first_user_msg = next(
                                (msg for msg in messages if msg["role"] == "user"), None
                            )
                            title = (
                                first_user_msg["content"][:50] + "..."
                                if first_user_msg
                                and len(first_user_msg["content"]) > 50
                                else first_user_msg["content"]
                                if first_user_msg
                                else "Langflow chat"
                            )
                        else:
                            title = metadata["title"]

                        all_conversations.append(
                            {
                                "response_id": session_id,
                                "title": title,
                                "endpoint": "langflow",
                                "messages": messages,  # Function calls preserved from Langflow
                                "created_at": metadata.get("created_at")
                                or conversation.get("created_at"),
                                "last_activity": metadata.get("last_activity")
                                or conversation.get("last_activity"),
                                "total_messages": len(messages),
                                "source": "langflow_enhanced",
                                "langflow_session_id": session_id,
                                "langflow_flow_id": conversation.get("flow_id"),
                            }
                        )

            if langflow_history.get("conversations"):
                logger.debug(
                    f"Added {len(langflow_history['conversations'])} historical conversations from Langflow"
                )
            elif langflow_history.get("error"):
                logger.debug(
                    f"Could not fetch Langflow history for user {user_id}: {langflow_history['error']}"
                )
            else:
                logger.debug(f"No Langflow conversations found for user {user_id}")

        except Exception as e:
            logger.error(f"Failed to fetch Langflow history: {e}")
            # Continue with just in-memory conversations

        # Sort by last activity (most recent first)
        all_conversations.sort(key=lambda c: c.get("last_activity", ""), reverse=True)

        logger.debug(
            f"[DEBUG] Returning {len(all_conversations)} conversations ({len(local_metadata)} from local metadata)"
        )

        return {
            "user_id": user_id,
            "endpoint": "langflow",
            "conversations": all_conversations,
            "total_conversations": len(all_conversations),
        }

    async def delete_session(self, user_id: str, session_id: str):
        """Delete a session from both local storage and Langflow"""
        try:
            # Delete from local conversation storage
            from agent import delete_user_conversation
            local_deleted = delete_user_conversation(user_id, session_id)

            # Delete from Langflow using the monitor API
            langflow_deleted = await self._delete_langflow_session(session_id)

            success = local_deleted or langflow_deleted
            error_msg = None

            if not success:
                error_msg = "Session not found in local storage or Langflow"

            return {
                "success": success,
                "local_deleted": local_deleted,
                "langflow_deleted": langflow_deleted,
                "error": error_msg
            }

        except Exception as e:
            logger.error(f"Error deleting session {session_id} for user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _delete_langflow_session(self, session_id: str):
        """Delete a session from Langflow using the monitor API"""
        try:
            response = await clients.langflow_request(
                "DELETE",
                f"/api/v1/monitor/messages/session/{session_id}"
            )

            if response.status_code == 200 or response.status_code == 204:
                logger.info(f"Successfully deleted session {session_id} from Langflow")
                return True
            else:
                logger.warning(
                    f"Failed to delete session {session_id} from Langflow: "
                    f"{response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error deleting session {session_id} from Langflow: {e}")
            return False

