from utils.logging_config import get_logger

logger = get_logger(__name__)

# Import persistent storage
from services.conversation_persistence_service import conversation_persistence


def get_user_conversations(user_id: str):
    """Get all conversations for a user"""
    return conversation_persistence.get_user_conversations(user_id)


def get_conversation_thread(user_id: str, previous_response_id: str = None):
    """Get or create a specific conversation thread"""
    conversations = get_user_conversations(user_id)

    if previous_response_id and previous_response_id in conversations:
        # Update last activity and return existing conversation
        conversations[previous_response_id]["last_activity"] = __import__(
            "datetime"
        ).datetime.now()
        return conversations[previous_response_id]

    # Create new conversation thread
    from datetime import datetime

    new_conversation = {
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant. Always use the search_tools to answer questions.",
            }
        ],
        "previous_response_id": previous_response_id,  # Parent response_id for branching
        "created_at": datetime.now(),
        "last_activity": datetime.now(),
    }

    return new_conversation


def store_conversation_thread(user_id: str, response_id: str, conversation_state: dict):
    """Store a conversation thread with its response_id"""
    conversation_persistence.store_conversation_thread(user_id, response_id, conversation_state)


# Legacy function for backward compatibility
def get_user_conversation(user_id: str):
    """Get the most recent conversation for a user (for backward compatibility)"""
    conversations = get_user_conversations(user_id)
    if not conversations:
        return get_conversation_thread(user_id)

    # Return the most recently active conversation
    latest_conversation = max(conversations.values(), key=lambda c: c["last_activity"])
    return latest_conversation


# Generic async response function for streaming
async def async_response_stream(
    client,
    prompt: str,
    model: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
    log_prefix: str = "response",
):
    logger.info("User prompt received", prompt=prompt)

    try:
        # Build request parameters
        request_params = {
            "model": model,
            "input": prompt,
            "stream": True,
            "include": ["tool_call.results"],
        }
        if previous_response_id is not None:
            request_params["previous_response_id"] = previous_response_id

        if "x-api-key" not in client.default_headers:
            if hasattr(client, "api_key") and extra_headers is not None:
                extra_headers["x-api-key"] = client.api_key

        if extra_headers:
            request_params["extra_headers"] = extra_headers

        response = await client.responses.create(**request_params)

        full_response = ""
        chunk_count = 0
        async for chunk in response:
            chunk_count += 1
            logger.debug("Stream chunk received", chunk_count=chunk_count, chunk=str(chunk))

            # Yield the raw event as JSON for the UI to process
            import json

            # Also extract text content for logging
            if hasattr(chunk, "output_text") and chunk.output_text:
                full_response += chunk.output_text
            elif hasattr(chunk, "delta") and chunk.delta:
                # Handle delta properly - it might be a dict or string
                if isinstance(chunk.delta, dict):
                    delta_text = (
                        chunk.delta.get("content", "")
                        or chunk.delta.get("text", "")
                        or str(chunk.delta)
                    )
                else:
                    delta_text = str(chunk.delta)
                full_response += delta_text

            # Send the raw event as JSON followed by newline for easy parsing
            try:
                # Try to serialize the chunk object
                if hasattr(chunk, "model_dump"):
                    # Pydantic model
                    chunk_data = chunk.model_dump()
                elif hasattr(chunk, "__dict__"):
                    chunk_data = chunk.__dict__
                else:
                    chunk_data = str(chunk)

                yield (json.dumps(chunk_data, default=str) + "\n").encode("utf-8")
            except Exception as e:
                # Fallback to string representation
                logger.warning("JSON serialization failed", error=str(e))
                yield (
                    json.dumps(
                        {"error": f"Serialization failed: {e}", "raw": str(chunk)}
                    )
                    + "\n"
                ).encode("utf-8")

        logger.debug("Stream complete", total_chunks=chunk_count)
        logger.info("Response generated", log_prefix=log_prefix, response=full_response)

    except Exception as e:
        logger.error("Exception in streaming", error=str(e))
        import traceback

        traceback.print_exc()
        raise


# Generic async response function for non-streaming
async def async_response(
    client,
    prompt: str,
    model: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
    log_prefix: str = "response",
):
    logger.info("User prompt received", prompt=prompt)

    # Build request parameters
    request_params = {
        "model": model,
        "input": prompt,
        "stream": False,
        "include": ["tool_call.results"],
    }
    if previous_response_id is not None:
        request_params["previous_response_id"] = previous_response_id
    if extra_headers:
        request_params["extra_headers"] = extra_headers

    response = await client.responses.create(**request_params)

    response_text = response.output_text
    logger.info("Response generated", log_prefix=log_prefix, response=response_text)

    # Extract and store response_id if available
    response_id = getattr(response, "id", None) or getattr(
        response, "response_id", None
    )

    return response_text, response_id


# Unified streaming function for both chat and langflow
async def async_stream(
    client,
    prompt: str,
    model: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
    log_prefix: str = "response",
):
    async for chunk in async_response_stream(
        client,
        prompt,
        model,
        extra_headers=extra_headers,
        previous_response_id=previous_response_id,
        log_prefix=log_prefix,
    ):
        yield chunk


# Async langflow function (non-streaming only)
async def async_langflow(
    langflow_client,
    flow_id: str,
    prompt: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
):
    response_text, response_id = await async_response(
        langflow_client,
        prompt,
        flow_id,
        extra_headers=extra_headers,
        previous_response_id=previous_response_id,
        log_prefix="langflow",
    )
    return response_text, response_id


# Async langflow function for streaming (alias for compatibility)
async def async_langflow_stream(
    langflow_client,
    flow_id: str,
    prompt: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
):
    logger.debug("Starting langflow stream", prompt=prompt)
    try:
        async for chunk in async_stream(
            langflow_client,
            prompt,
            flow_id,
            extra_headers=extra_headers,
            previous_response_id=previous_response_id,
            log_prefix="langflow",
        ):
            logger.debug("Yielding chunk from langflow stream", chunk_preview=chunk[:100].decode('utf-8', errors='replace'))
            yield chunk
        logger.debug("Langflow stream completed")
    except Exception as e:
        logger.error("Exception in langflow stream", error=str(e))
        import traceback

        traceback.print_exc()
        raise


# Async chat function (non-streaming only)
async def async_chat(
    async_client,
    prompt: str,
    user_id: str,
    model: str = "gpt-4.1-mini",
    previous_response_id: str = None,
):
    logger.debug("async_chat called", user_id=user_id, previous_response_id=previous_response_id)

    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, previous_response_id)
    logger.debug("Got conversation state", message_count=len(conversation_state['messages']))

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)
    logger.debug("Added user message", message_count=len(conversation_state['messages']))

    response_text, response_id = await async_response(
        async_client,
        prompt,
        model,
        previous_response_id=previous_response_id,
        log_prefix="agent",
    )
    logger.debug("Got response", response_preview=response_text[:50], response_id=response_id)

    # Add assistant response to conversation with response_id and timestamp
    assistant_message = {
        "role": "assistant",
        "content": response_text,
        "response_id": response_id,
        "timestamp": datetime.now(),
    }
    conversation_state["messages"].append(assistant_message)
    logger.debug("Added assistant message", message_count=len(conversation_state['messages']))

    # Store the conversation thread with its response_id
    if response_id:
        conversation_state["last_activity"] = datetime.now()
        store_conversation_thread(user_id, response_id, conversation_state)
        logger.debug("Stored conversation thread", user_id=user_id, response_id=response_id)

        # Debug: Check what's in user_conversations now
        conversations = get_user_conversations(user_id)
        logger.debug("User conversations updated", user_id=user_id, conversation_count=len(conversations), conversation_ids=list(conversations.keys()))
    else:
        logger.warning("No response_id received, conversation not stored")

    return response_text, response_id


# Async chat function for streaming (alias for compatibility)
async def async_chat_stream(
    async_client,
    prompt: str,
    user_id: str,
    model: str = "gpt-4.1-mini",
    previous_response_id: str = None,
):
    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, previous_response_id)

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)

    full_response = ""
    response_id = None
    async for chunk in async_stream(
        async_client,
        prompt,
        model,
        previous_response_id=previous_response_id,
        log_prefix="agent",
    ):
        # Extract text content to build full response for history
        try:
            import json

            chunk_data = json.loads(chunk.decode("utf-8"))
            if "delta" in chunk_data and "content" in chunk_data["delta"]:
                full_response += chunk_data["delta"]["content"]
            # Extract response_id from chunk
            if "id" in chunk_data:
                response_id = chunk_data["id"]
            elif "response_id" in chunk_data:
                response_id = chunk_data["response_id"]
        except:
            pass
        yield chunk

    # Add the complete assistant response to message history with response_id and timestamp
    if full_response:
        assistant_message = {
            "role": "assistant",
            "content": full_response,
            "response_id": response_id,
            "timestamp": datetime.now(),
        }
        conversation_state["messages"].append(assistant_message)

        # Store the conversation thread with its response_id
        if response_id:
            conversation_state["last_activity"] = datetime.now()
            store_conversation_thread(user_id, response_id, conversation_state)
            logger.debug("Stored conversation thread", user_id=user_id, response_id=response_id)


# Async langflow function with conversation storage (non-streaming)
async def async_langflow_chat(
    langflow_client,
    flow_id: str,
    prompt: str,
    user_id: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
):
    logger.debug("async_langflow_chat called", user_id=user_id, previous_response_id=previous_response_id)

    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, previous_response_id)
    logger.debug("Got langflow conversation state", message_count=len(conversation_state['messages']))

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)
    logger.debug("Added user message to langflow", message_count=len(conversation_state['messages']))

    response_text, response_id = await async_response(
        langflow_client,
        prompt,
        flow_id,
        extra_headers=extra_headers,
        previous_response_id=previous_response_id,
        log_prefix="langflow",
    )
    logger.debug("Got langflow response", response_preview=response_text[:50], response_id=response_id)

    # Add assistant response to conversation with response_id and timestamp
    assistant_message = {
        "role": "assistant",
        "content": response_text,
        "response_id": response_id,
        "timestamp": datetime.now(),
    }
    conversation_state["messages"].append(assistant_message)
    logger.debug("Added assistant message to langflow", message_count=len(conversation_state['messages']))

    # Store the conversation thread with its response_id
    if response_id:
        conversation_state["last_activity"] = datetime.now()
        store_conversation_thread(user_id, response_id, conversation_state)
        
        # Claim session ownership for this user
        try:
            from services.session_ownership_service import session_ownership_service
            session_ownership_service.claim_session(user_id, response_id)
            print(f"[DEBUG] Claimed session {response_id} for user {user_id}")
        except Exception as e:
            print(f"[WARNING] Failed to claim session ownership: {e}")
        
        print(
            f"[DEBUG] Stored langflow conversation thread for user {user_id} with response_id: {response_id}"
        )
        logger.debug("Stored langflow conversation thread", user_id=user_id, response_id=response_id)

        # Debug: Check what's in user_conversations now
        conversations = get_user_conversations(user_id)
        logger.debug("User conversations updated", user_id=user_id, conversation_count=len(conversations), conversation_ids=list(conversations.keys()))
    else:
        logger.warning("No response_id received from langflow, conversation not stored")

    return response_text, response_id


# Async langflow function with conversation storage (streaming)
async def async_langflow_chat_stream(
    langflow_client,
    flow_id: str,
    prompt: str,
    user_id: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
):
    logger.debug("async_langflow_chat_stream called", user_id=user_id, previous_response_id=previous_response_id)

    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, previous_response_id)

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)

    full_response = ""
    response_id = None
    async for chunk in async_stream(
        langflow_client,
        prompt,
        flow_id,
        extra_headers=extra_headers,
        previous_response_id=previous_response_id,
        log_prefix="langflow",
    ):
        # Extract text content to build full response for history
        try:
            import json

            chunk_data = json.loads(chunk.decode("utf-8"))
            if "delta" in chunk_data and "content" in chunk_data["delta"]:
                full_response += chunk_data["delta"]["content"]
            # Extract response_id from chunk
            if "id" in chunk_data:
                response_id = chunk_data["id"]
            elif "response_id" in chunk_data:
                response_id = chunk_data["response_id"]
        except:
            pass
        yield chunk

    # Add the complete assistant response to message history with response_id and timestamp
    if full_response:
        assistant_message = {
            "role": "assistant",
            "content": full_response,
            "response_id": response_id,
            "timestamp": datetime.now(),
        }
        conversation_state["messages"].append(assistant_message)

        # Store the conversation thread with its response_id
        if response_id:
            conversation_state["last_activity"] = datetime.now()
            store_conversation_thread(user_id, response_id, conversation_state)
            
            # Claim session ownership for this user
        try:
            from services.session_ownership_service import session_ownership_service
            session_ownership_service.claim_session(user_id, response_id)
            print(f"[DEBUG] Claimed session {response_id} for user {user_id}")
        except Exception as e:
            print(f"[WARNING] Failed to claim session ownership: {e}")
            
            print(
                f"[DEBUG] Stored langflow conversation thread for user {user_id} with response_id: {response_id}"
            )
            logger.debug("Stored langflow conversation thread", user_id=user_id, response_id=response_id)
