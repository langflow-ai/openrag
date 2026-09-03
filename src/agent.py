import uuid
from typing import Any

from config.config_manager import DEFAULT_SYSTEM_PROMPT
from services.conversation_persistence_service import conversation_persistence
from utils.langflow_utils import parse_knowledge_chunks, strip_untrusted_fence_recursive
from utils.logging_config import get_logger

logger = get_logger(__name__)

# In-memory storage for active conversation threads (preserves function calls)
active_conversations: dict[str, dict[str, Any]] = {}


def _format_provider_error_message(exc: BaseException) -> str:
    """Return a concise, user-facing provider error string from an exception."""
    from api.provider_validation import sanitize_provider_error_content

    return sanitize_provider_error_content(str(exc))


def _provider_error_display_text(error_text: str, partial_response: str = "") -> str:
    """Combine any streamed partial answer with the provider error for display/history.

    If the mid-stream text is itself a provider failure dump (often raw JSON), keep
    only the sanitized error — do not paste the dump above the clean message.
    """
    from api.provider_validation import looks_like_provider_error_content

    partial = (partial_response or "").strip()
    if not partial:
        return error_text
    if looks_like_provider_error_content(partial) or "{" in partial:
        return error_text
    if error_text in partial:
        return partial
    return f"{partial}\n\n{error_text}"


def _conversation_thread_in_memory(user_id: str, response_id: str | None) -> bool:
    """True when response_id is already keyed in the in-process conversation cache."""
    return bool(
        response_id
        and user_id in active_conversations
        and response_id in active_conversations[user_id]
    )


def _resolve_conversation_store_id(
    response_id: str | None,
    thread_id: str | None,
    *,
    previous_loaded_from_memory: bool,
    mint_if_missing: bool = False,
) -> str | None:
    """Resolve the OpenRAG conversation id used for persistence.

    Prefer an in-memory thread id so follow-ups stay on one sidebar entry.
    Never reuse a cold thread id (would overwrite metadata with empty state).
    Fall back to the stream id, then optionally mint a UUID for failed first turns.
    """
    if previous_loaded_from_memory and thread_id:
        return thread_id
    if response_id:
        return response_id
    if mint_if_missing:
        return str(uuid.uuid4())
    return None


def _conversation_ended_with_error(user_id: str, response_id: str | None) -> bool:
    """True when the in-memory thread's last assistant message is a provider error."""
    if not response_id or user_id not in active_conversations:
        return False
    messages = active_conversations[user_id].get(response_id, {}).get("messages") or []
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return bool(message.get("error"))
    return False


async def _claim_session(user_id: str, session_id: str) -> None:
    """Record `user_id` as the owner of `session_id`, best effort.

    Required for threading: `_assert_owns` returns 404 (session_not_found) for
    an unclaimed session, so the next message in the thread fails. Never raise —
    a claim failure must not lose a reply the user already saw.
    """
    if not session_id:
        return
    try:
        from services.session_ownership_service import session_ownership_service

        await session_ownership_service.claim_session(user_id, session_id)
        logger.debug(f"Claimed session {session_id} for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to claim session ownership: {e}")


async def _persist_error_conversation(
    user_id: str, store_id: str, conversation_state: dict
) -> None:
    """Store a failed turn and claim session ownership.

    Claiming is required: otherwise the client may retry with this response_id and
    ``_assert_owns`` returns 404 (session_not_found) for an unclaimed session.
    """
    from datetime import datetime

    conversation_state["last_activity"] = datetime.now()
    await store_conversation_thread(user_id, store_id, conversation_state)
    await _claim_session(user_id, store_id)


def _extract_delta_text(delta) -> str:
    """Text carried by a streamed delta, for either shape.

    Langflow's SSE wraps deltas as {"content": "..."}; the OpenAI Responses SDK
    sends a bare string. Testing `"content" in delta` against a string is a
    substring check that silently yields nothing, which left the langflowless
    transcript empty even though the UI rendered the reply fine.

    Never falls back to str(dict): that pollutes the transcript with
    "{'content': ''}" prefixes on empty error chunks.
    """
    if isinstance(delta, dict):
        raw = delta.get("content")
        if raw is None:
            raw = delta.get("text")
        return raw if isinstance(raw, str) else ""
    return delta if isinstance(delta, str) else ""


def _stream_error_chunk(message: str, response_id: str | None = None) -> bytes:
    """NDJSON error event consumed by the chat streaming client."""
    import json

    payload: dict[str, Any] = {
        "status": "failed",
        "finish_reason": "error",
        "error": {"message": message},
    }
    if response_id:
        payload["id"] = response_id
        payload["response_id"] = response_id
    return (json.dumps(payload) + "\n").encode("utf-8")


async def get_user_conversations(user_id: str):
    """Get conversation metadata for a user from persistent storage."""
    return await conversation_persistence.get_user_conversations(user_id)


def get_conversation_thread(user_id: str, previous_response_id: str = None):
    """Get or create a specific conversation thread with function call preservation"""
    from datetime import datetime

    # Create user namespace if it doesn't exist
    if user_id not in active_conversations:
        active_conversations[user_id] = {}

    # If we have a previous_response_id, try to get the existing conversation
    if previous_response_id and previous_response_id in active_conversations[user_id]:
        logger.debug(
            f"Retrieved existing conversation for user {user_id}, response_id {previous_response_id}"
        )
        return active_conversations[user_id][previous_response_id]

    # Create new conversation thread
    new_conversation = {
        "messages": [
            {
                "role": "system",
                "content": DEFAULT_SYSTEM_PROMPT,
            }
        ],
        "previous_response_id": previous_response_id,  # Parent response_id for branching
        "created_at": datetime.now(),
        "last_activity": datetime.now(),
    }

    return new_conversation


async def store_conversation_thread(user_id: str, response_id: str, conversation_state: dict):
    """Store conversation both in memory (with function calls) and persist metadata to disk (async, non-blocking)"""
    # 1. Store full conversation in memory for function call preservation
    if user_id not in active_conversations:
        active_conversations[user_id] = {}
    active_conversations[user_id][response_id] = conversation_state

    # 2. Store only essential metadata to disk (simplified JSON)
    messages = conversation_state.get("messages", [])
    first_user_msg = next((msg for msg in messages if msg.get("role") == "user"), None)
    title = "New Chat"
    if first_user_msg:
        content = first_user_msg.get("content", "")
        title = content[:50] + "..." if len(content) > 50 else content

    user_assistant_messages = [msg for msg in messages if msg.get("role") in ["user", "assistant"]]
    metadata_only = {
        "response_id": response_id,
        "title": title,
        "endpoint": "langflow",
        "created_at": conversation_state.get("created_at"),
        "last_activity": conversation_state.get("last_activity"),
        "previous_response_id": conversation_state.get("previous_response_id"),
        "filter_id": conversation_state.get("filter_id"),
        "total_messages": len(user_assistant_messages),
    }
    # Snapshot error-thread turns: Langflow history is incomplete after fresh-session retries.
    if any(msg.get("error") for msg in user_assistant_messages):
        metadata_only["messages"] = [
            {
                "role": msg.get("role"),
                "content": msg.get("content"),
                "timestamp": msg.get("timestamp"),
                "error": bool(msg.get("error")),
            }
            for msg in user_assistant_messages
        ]

    await conversation_persistence.store_conversation_thread(user_id, response_id, metadata_only)


# Legacy function for backward compatibility
def get_user_conversation(user_id: str):
    """Get the most recent conversation for a user (for backward compatibility)"""
    # Check in-memory conversations first (with function calls)
    if user_id in active_conversations and active_conversations[user_id]:
        latest_response_id = max(
            active_conversations[user_id].keys(),
            key=lambda k: active_conversations[user_id][k]["last_activity"],
        )
        return active_conversations[user_id][latest_response_id]

    # Fallback to metadata-only conversations. This is a SYNC legacy
    # caller, so we read the eagerly-loaded JSON cache directly instead
    # of awaiting the async service. The dict is populated in the
    # service's __init__ for all storage modes; in `db` mode it stays
    # empty but `active_conversations` above already covered fresh data.
    conversations = conversation_persistence._conversations.get(user_id, {})
    if not conversations:
        return get_conversation_thread(user_id)

    # Return the most recently active conversation metadata
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
        detected_tool_call = False
        async for chunk in response:
            chunk_count += 1

            import json

            # Also extract text content for logging
            if hasattr(chunk, "output_text") and chunk.output_text:
                full_response += chunk.output_text
            elif hasattr(chunk, "delta") and chunk.delta:
                full_response += _extract_delta_text(chunk.delta)

            # Enhanced logging for tool call detection (Granite 3.3 8b investigation)
            chunk_attrs = dir(chunk) if hasattr(chunk, "__dict__") else []
            tool_related_attrs = [
                attr
                for attr in chunk_attrs
                if "tool" in attr.lower() or "call" in attr.lower() or "retrieval" in attr.lower()
            ]
            if tool_related_attrs:
                logger.info(
                    "Tool-related attributes found in chunk",
                    chunk_count=chunk_count,
                    attributes=tool_related_attrs,
                    chunk_type=type(chunk).__name__,
                )

            # Send the raw event as JSON followed by newline for easy parsing
            try:
                # Try to serialize the chunk object
                if hasattr(chunk, "model_dump"):
                    # Pydantic model. Exclude "delta" from serialization since Langflow's
                    # /response SSE wraps text deltas as {"content": "..."} for every provider but
                    # openai SDK's event models declare/expect delta to be str so model_dump() will
                    # emit noisy logs (PydanticSerializationUnexpectedValue) for every chunk. Basically
                    # just reattach the raw (unvalidated) value afterwards to preserve same shape.
                    # TODO: replace this with just chunk.model_dump() if langflow's /response SSE matches openai's
                    # SDK's delta: str schema
                    chunk_data = chunk.model_dump(exclude={"delta"})
                    if hasattr(chunk, "delta"):
                        chunk_data["delta"] = chunk.delta
                elif hasattr(chunk, "__dict__"):
                    chunk_data = chunk.__dict__
                else:
                    chunk_data = str(chunk)

                # VULN-13906: the live chat UI always streams, so this is the only place
                # retrieved/uploaded text (fenced in flows/components/opensearch_multimodal.py
                # and src/agent.py's fence_untrusted_text) reaches the client — strip fence
                # markers here, before anything is yielded. Frontend surfaces (tool-call trace
                # panel, citation click-through popup) read this raw streamed payload directly.
                strip_untrusted_fence_recursive(chunk_data)

                # Log detailed chunk structure for investigation (especially for Granite 3.3 8b)
                if isinstance(chunk_data, dict):
                    # Check for any fields that might indicate tool usage
                    potential_tool_fields = {
                        k: v
                        for k, v in chunk_data.items()
                        if any(
                            keyword in str(k).lower()
                            for keyword in [
                                "tool",
                                "call",
                                "retrieval",
                                "function",
                                "result",
                                "output",
                            ]
                        )
                    }
                    if potential_tool_fields:
                        logger.info(
                            "Potential tool-related fields in chunk",
                            chunk_count=chunk_count,
                            fields=list(potential_tool_fields.keys()),
                            sample_data=str(potential_tool_fields)[:500],
                        )

                # Detect response.completed event and log usage
                if isinstance(chunk_data, dict) and chunk_data.get("type") == "response.completed":
                    response_data = chunk_data.get("response", {})
                    usage = response_data.get("usage")
                    if usage:
                        logger.info(
                            "Stream usage data",
                            input_tokens=usage.get("input_tokens"),
                            output_tokens=usage.get("output_tokens"),
                            total_tokens=usage.get("total_tokens"),
                        )

                # Format native tool call results
                if isinstance(chunk_data, dict):
                    # Format: {"type": "response.output_item.added", "item": {"type": "tool_call", "results": ...}}
                    item = chunk_data.get("item")
                    if (
                        isinstance(item, dict)
                        and item.get("type") == "tool_call"
                        and "results" in item
                    ):
                        item["results"] = parse_knowledge_chunks(item["results"])

                    # Also check for direct tool_call chunks
                    elif chunk_data.get("type") == "tool_call" and "results" in chunk_data:
                        chunk_data["results"] = parse_knowledge_chunks(chunk_data["results"])

                # Middleware: Detect implicit tool calls and inject standardized events
                # This helps Granite 3.3 8b and other models that don't emit standard markers
                if isinstance(chunk_data, dict) and not detected_tool_call:
                    # Check if this chunk contains retrieval results
                    has_results = any(
                        [
                            bool(chunk_data.get("results")),
                            bool(chunk_data.get("outputs")),
                            bool(chunk_data.get("retrieved_documents")),
                            bool(chunk_data.get("retrieval_results")),
                        ]
                    )

                    if has_results:
                        logger.info(
                            "Detected implicit tool call in backend, injecting synthetic event",
                            chunk_fields=list(chunk_data.keys()),
                        )
                        # Inject a synthetic tool call event before this chunk
                        synthetic_event = {
                            "type": "response.output_item.done",
                            "item": {
                                "type": "retrieval_call",
                                "id": f"synthetic_{chunk_count}",
                                "name": "Retrieval",
                                "tool_name": "Retrieval",
                                "status": "completed",
                                "inputs": {"implicit": True, "backend_detected": True},
                                "results": parse_knowledge_chunks(
                                    chunk_data.get("results")
                                    or chunk_data.get("outputs")
                                    or chunk_data.get("retrieved_documents")
                                    or chunk_data.get("retrieval_results")
                                ),
                            },
                        }
                        # Send the synthetic event first
                        yield (json.dumps(synthetic_event, default=str) + "\n").encode("utf-8")
                        detected_tool_call = True  # Mark that we've injected a tool call

                yield (json.dumps(chunk_data, default=str) + "\n").encode("utf-8")
            except Exception as e:
                # Fallback to string representation
                logger.warning("JSON serialization failed", error=str(e))
                yield (
                    json.dumps({"error": f"Serialization failed: {e}", "raw": str(chunk)}) + "\n"
                ).encode("utf-8")

        logger.debug("Stream complete", total_chunks=chunk_count)
        logger.info("Response generated", log_prefix=log_prefix, response=full_response)

    except Exception:
        logger.exception("[AGENT] Streaming failed")
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
    # extra_headers/request_params carry raw secrets (JWT, provider API keys,
    # x-api-key — see langflow_headers.py). Never pass them to a logger call
    # (e.g. logger.info(..., extra_headers=extra_headers)) — that logs the
    # secrets directly, bypassing the show_locals=False traceback protection
    # in utils/logging_config.py.
    try:
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

        if "x-api-key" not in client.default_headers:
            if hasattr(client, "api_key") and extra_headers is not None:
                extra_headers["x-api-key"] = client.api_key

        response = await client.responses.create(**request_params)

        try:
            output_text = response.output_text
        except (AttributeError, TypeError):
            output_text = None

        if output_text is not None:
            response_text = output_text
            logger.info("Response generated", log_prefix=log_prefix, response=response_text)

            # Extract and store response_id if available
            response_id = getattr(response, "id", None) or getattr(response, "response_id", None)

            return response_text, response_id, response
        else:
            msg = "Nudge response missing output_text"
            error = getattr(response, "error", None)
            if error:
                error_msg = getattr(error, "message", None)
                if error_msg:
                    msg = error_msg
            raise ValueError(msg)
    except Exception:
        logger.exception("[AGENT] Non-streaming response failed")
        raise


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
    response_text, response_id, response_obj = await async_response(
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
            logger.debug(
                "Yielding chunk from langflow stream",
                chunk_preview=chunk[:100].decode("utf-8", errors="replace"),
            )
            yield chunk
        logger.debug("Langflow stream completed")
    except Exception:
        logger.exception("[AGENT] Langflow stream failed")
        raise


# Async chat function (non-streaming only)
async def async_chat(
    async_client,
    prompt: str,
    user_id: str,
    model: str = "gpt-4.1-mini",
    previous_response_id: str = None,
    filter_id: str = None,
    conversation_id: str = None,
):
    logger.debug("async_chat called", user_id=user_id, previous_response_id=previous_response_id)

    # See async_chat_stream: conversation_id is the stable sidebar thread id.
    thread_id = conversation_id or previous_response_id
    previous_loaded_from_memory = _conversation_thread_in_memory(user_id, thread_id)
    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, thread_id)
    logger.debug("Got conversation state", message_count=len(conversation_state["messages"]))

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)
    logger.debug("Added user message", message_count=len(conversation_state["messages"]))

    # Store filter_id in conversation state if provided
    if filter_id:
        conversation_state["filter_id"] = filter_id

    response_text, response_id, response_obj = await async_response(
        async_client,
        prompt,
        model,
        previous_response_id=previous_response_id,
        log_prefix="agent",
    )
    logger.debug("Got response", response_preview=response_text[:50], response_id=response_id)

    # Add assistant response to conversation with response_id, timestamp, and full response object
    assistant_message = {
        "role": "assistant",
        "content": response_text,
        "response_id": response_id,
        "timestamp": datetime.now(),
        "response_data": response_obj.model_dump()
        if hasattr(response_obj, "model_dump")
        else str(response_obj),  # Store complete response for function calls
    }
    conversation_state["messages"].append(assistant_message)
    logger.debug("Added assistant message", message_count=len(conversation_state["messages"]))

    # Store the conversation thread with its response_id
    if response_id:
        conversation_state["last_activity"] = datetime.now()
        store_id = (
            _resolve_conversation_store_id(
                response_id,
                thread_id,
                previous_loaded_from_memory=previous_loaded_from_memory,
            )
            or response_id
        )
        await store_conversation_thread(user_id, store_id, conversation_state)
        await _claim_session(user_id, store_id)
        if store_id != response_id:
            await _claim_session(user_id, response_id)
        logger.debug("Stored conversation thread", user_id=user_id, store_id=store_id)

        # Debug: Check what's in user_conversations now
        conversations = await get_user_conversations(user_id)
        logger.debug(
            "User conversations updated",
            user_id=user_id,
            conversation_count=len(conversations),
            conversation_ids=list(conversations.keys()),
        )
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
    filter_id: str = None,
    conversation_id: str = None,
):
    # conversation_id keeps the OpenRAG sidebar thread; previous_response_id
    # chains the provider session. Mirrors async_langflow_chat_stream — without
    # a stable thread id every turn is stored under its own response id and the
    # sidebar grows one duplicate entry per message.
    thread_id = conversation_id or previous_response_id
    previous_loaded_from_memory = _conversation_thread_in_memory(user_id, thread_id)
    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, thread_id)

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)

    # Store filter_id in conversation state if provided
    if filter_id:
        conversation_state["filter_id"] = filter_id

    full_response = ""
    response_id = None
    usage_data = None
    try:
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
                full_response += _extract_delta_text(chunk_data.get("delta"))
                # Extract response_id from chunk
                if "id" in chunk_data:
                    response_id = chunk_data["id"]
                elif "response_id" in chunk_data:
                    response_id = chunk_data["response_id"]
                # Capture usage and the response id from the terminal event.
                # An OpenAI Responses stream carries no top-level id — it lives
                # on the response object here — so without this the direct
                # (langflowless) path never resolves one and the conversation is
                # silently dropped instead of stored, leaving the sidebar empty.
                # Langflow's SSE wrapper does send a top-level id, which is why
                # only the direct path was affected.
                if chunk_data.get("type") == "response.completed":
                    response_obj = chunk_data.get("response", {})
                    usage_data = response_obj.get("usage")
                    response_id = response_obj.get("id") or response_id
            except Exception:
                pass
            yield chunk

        # Add the complete assistant response to message history with response_id and timestamp
        assistant_message = {
            "role": "assistant",
            "content": full_response,
            "response_id": response_id,
            "timestamp": datetime.now(),
        }
        # Store usage data if available (from response.completed event)
        if usage_data:
            assistant_message["response_data"] = {"usage": usage_data}
        conversation_state["messages"].append(assistant_message)

        # Store the conversation thread with its response_id
        if response_id:
            conversation_state["last_activity"] = datetime.now()
            store_id = (
                _resolve_conversation_store_id(
                    response_id,
                    thread_id,
                    previous_loaded_from_memory=previous_loaded_from_memory,
                )
                or response_id
            )
            await store_conversation_thread(user_id, store_id, conversation_state)
            await _claim_session(user_id, store_id)
            # The provider's response id still has to be claimed: the client
            # sends it back as previous_response_id on the next turn, and
            # _assert_owns 404s on an unclaimed session.
            if store_id != response_id:
                await _claim_session(user_id, response_id)
            logger.debug(
                f"Stored conversation thread for user {user_id} under {store_id}"
                f" (response_id: {response_id})"
            )
    except Exception as e:
        logger.error(f"Error in chat stream: {e}", exc_info=True)
        from api.provider_validation import resolve_chat_stream_error_message_async

        error_text = await resolve_chat_stream_error_message_async(e)
        display_text = _provider_error_display_text(error_text, full_response)
        conversation_state["messages"].append(
            {
                "role": "assistant",
                "content": display_text,
                "timestamp": datetime.now(),
                "error": True,
            }
        )
        store_id = _resolve_conversation_store_id(
            response_id,
            thread_id,
            previous_loaded_from_memory=previous_loaded_from_memory,
            mint_if_missing=True,
        )
        try:
            await _persist_error_conversation(user_id, store_id, conversation_state)
        except Exception as store_error:
            logger.error(f"Failed to store error conversation: {store_error}")
        yield _stream_error_chunk(display_text, store_id)


# Async langflow function with conversation storage (non-streaming)
async def async_langflow_chat(
    langflow_client,
    flow_id: str,
    prompt: str,
    user_id: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
    conversation_id: str = None,
    store_conversation: bool = True,
    filter_id: str = None,
):
    logger.debug(
        "async_langflow_chat called",
        user_id=user_id,
        previous_response_id=previous_response_id,
        conversation_id=conversation_id,
    )

    thread_id = conversation_id or previous_response_id
    if store_conversation:
        # Get the specific conversation thread (or create new one)
        conversation_state = get_conversation_thread(user_id, thread_id)
        logger.debug(
            "Got langflow conversation state",
            message_count=len(conversation_state["messages"]),
        )

    # Add user message to conversation with timestamp
    from datetime import datetime

    if store_conversation:
        user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
        conversation_state["messages"].append(user_message)
        logger.debug(
            "Added user message to langflow",
            message_count=len(conversation_state["messages"]),
        )

        # Store filter_id in conversation state if provided
        if filter_id:
            conversation_state["filter_id"] = filter_id

    response_text, response_id, response_obj = await async_response(
        langflow_client,
        prompt,
        flow_id,
        extra_headers=extra_headers,
        previous_response_id=previous_response_id,
        log_prefix="langflow",
    )
    logger.debug(
        "Got langflow response",
        response_preview=response_text[:50],
        response_id=response_id,
    )
    logger.debug(
        "Got langflow response",
        response_preview=response_text[:50],
        response_id=response_id,
    )

    if store_conversation:
        # Add assistant response to conversation with response_id and timestamp
        assistant_message = {
            "role": "assistant",
            "content": response_text,
            "response_id": response_id,
            "timestamp": datetime.now(),
            "response_data": response_obj.model_dump()
            if hasattr(response_obj, "model_dump")
            else str(response_obj),  # Store complete response for function calls
        }
        conversation_state["messages"].append(assistant_message)
        logger.debug(
            "Added assistant message to langflow",
            message_count=len(conversation_state["messages"]),
        )

    # Extract sources from retrieval tool calls in the response
    sources = []

    # Layer 1: Structured output items (OpenAI Responses API format).
    # Relaxed: check for any output item with a non-empty `results` field,
    # regardless of `type` string (Langflow may use different type names).
    if hasattr(response_obj, "output") and response_obj.output:
        for output_item in response_obj.output:
            sources.extend(parse_knowledge_chunks(getattr(output_item, "results", None)))

    # Layer 2: Top-level dict inspection (mirrors streaming middleware in async_response_stream).
    # Langflow may embed retrieval results directly in the response dict rather than
    # inside typed output items.
    if not sources:
        resp_dict = (
            response_obj.model_dump()
            if hasattr(response_obj, "model_dump")
            else getattr(response_obj, "__dict__", {})
        )
        implicit_results = (
            resp_dict.get("results")
            or resp_dict.get("outputs")
            or resp_dict.get("retrieved_documents")
            or resp_dict.get("retrieval_results")
        )
        sources.extend(parse_knowledge_chunks(implicit_results))

    # Layer 3: Citation-text fallback.
    # Parse "(Source: filename)" patterns emitted by the LLM when it cites documents.
    # This is the last-resort fallback when Langflow's response object carries no
    # structured retrieval data.
    if not sources:
        import re

        for match in re.finditer(r"\(Source:\s*([^\)]+)\)", response_text):
            sources.append(
                {
                    "filename": match.group(1).strip(),
                    "text": "",
                    "score": 0,
                    "page": None,
                    "mimetype": None,
                }
            )

    if not store_conversation:
        return response_text, response_id, sources

    # Store the conversation thread with its response_id
    if response_id:
        conversation_state["last_activity"] = datetime.now()
        await store_conversation_thread(user_id, response_id, conversation_state)

        await _claim_session(user_id, response_id)

        logger.debug(
            "Stored langflow conversation thread",
            user_id=user_id,
            response_id=response_id,
        )
    else:
        logger.warning("No response_id received from langflow, conversation not stored")

    return response_text, response_id, sources


# Async langflow function with conversation storage (streaming)
async def async_langflow_chat_stream(
    langflow_client,
    flow_id: str,
    prompt: str,
    user_id: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
    conversation_id: str = None,
    filter_id: str = None,
):
    logger.debug(
        "async_langflow_chat_stream called",
        user_id=user_id,
        previous_response_id=previous_response_id,
        conversation_id=conversation_id,
    )

    # conversation_id keeps the OpenRAG sidebar thread; previous_response_id chains
    # the Langflow session. After errors the client omits previous_response_id.
    thread_id = conversation_id or previous_response_id
    previous_loaded_from_memory = _conversation_thread_in_memory(user_id, thread_id)
    conversation_state = get_conversation_thread(user_id, thread_id)

    from datetime import datetime

    conversation_state["messages"].append(
        {"role": "user", "content": prompt, "timestamp": datetime.now()}
    )
    if filter_id:
        conversation_state["filter_id"] = filter_id

    # Safety net: never continue a Langflow session that already ended in error.
    langflow_previous_response_id = previous_response_id
    if previous_response_id and _conversation_ended_with_error(user_id, thread_id):
        langflow_previous_response_id = None

    full_response = ""
    response_id = None
    usage_data = None
    collected_chunks = []  # Store all chunks for function call data
    error_occurred = False

    try:
        async for chunk in async_stream(
            langflow_client,
            prompt,
            flow_id,
            extra_headers=extra_headers,
            previous_response_id=langflow_previous_response_id,
            log_prefix="langflow",
        ):
            # Extract text content to build full response for history
            try:
                import json

                chunk_data = json.loads(chunk.decode("utf-8"))
                collected_chunks.append(chunk_data)  # Collect all chunk data

                full_response += _extract_delta_text(chunk_data.get("delta"))
                # Extract response_id from chunk
                if "id" in chunk_data:
                    response_id = chunk_data["id"]
                elif "response_id" in chunk_data:
                    response_id = chunk_data["response_id"]
                # Langflow supplies a top-level id today, but fall back to the
                # terminal event's response object so this path cannot break the
                # same way if that wrapper ever changes.
                elif chunk_data.get("type") == "response.completed":
                    response_id = chunk_data.get("response", {}).get("id") or response_id

                # Check for error status. Do not forward bare Langflow error
                # chunks — they often lack a useful message and the client would
                # show a generic failure before our sanitized terminal chunk.
                if (
                    chunk_data.get("finish_reason") == "error"
                    or chunk_data.get("status") == "failed"
                ):
                    error_occurred = True
                    logger.error("Error detected in Langflow stream chunk")
                    err = chunk_data.get("error")
                    if isinstance(err, dict):
                        err_msg = err.get("message")
                    else:
                        err_msg = err
                    if isinstance(err_msg, str) and err_msg.strip():
                        if err_msg not in full_response:
                            full_response = (
                                f"{full_response}\n\n{err_msg}" if full_response else err_msg
                            )
                    elif (
                        isinstance(chunk_data.get("message"), str) and chunk_data["message"].strip()
                    ):
                        msg = chunk_data["message"]
                        if msg not in full_response:
                            full_response = f"{full_response}\n\n{msg}" if full_response else msg
                    continue
                # Capture usage from response.completed event
                if chunk_data.get("type") == "response.completed":
                    response_obj = chunk_data.get("response", {})
                    usage_data = response_obj.get("usage")
            except Exception:
                pass
            yield chunk

        from api.provider_validation import (
            looks_like_provider_error_content,
            resolve_chat_stream_error_message_async,
        )

        # Credential failures are often streamed as plain assistant text with no
        # exception. Sanitize, mark as error, and emit a terminal error chunk so
        # the client shows the error card instead of raw JSON.
        if error_occurred or looks_like_provider_error_content(full_response):
            display_text = await resolve_chat_stream_error_message_async(full_response)
            conversation_state["messages"].append(
                {
                    "role": "assistant",
                    "content": display_text,
                    "response_id": response_id,
                    "timestamp": datetime.now(),
                    "chunks": collected_chunks,
                    "error": True,
                }
            )
            store_id = _resolve_conversation_store_id(
                response_id,
                thread_id,
                previous_loaded_from_memory=previous_loaded_from_memory,
                mint_if_missing=True,
            )
            try:
                await _persist_error_conversation(user_id, store_id, conversation_state)
            except Exception as store_error:
                logger.error(f"Failed to store error conversation: {store_error}")
            yield _stream_error_chunk(display_text, store_id)
            return

        if full_response:
            assistant_message = {
                "role": "assistant",
                "content": full_response,
                "response_id": response_id,
                "timestamp": datetime.now(),
                "chunks": collected_chunks,
                "error": error_occurred,
            }
            if usage_data:
                assistant_message["response_data"] = {"usage": usage_data}
            conversation_state["messages"].append(assistant_message)

        persist_id = _resolve_conversation_store_id(
            response_id,
            thread_id,
            previous_loaded_from_memory=previous_loaded_from_memory,
        )
        if persist_id:
            conversation_state["last_activity"] = datetime.now()
            await store_conversation_thread(user_id, persist_id, conversation_state)
            await _claim_session(user_id, persist_id)
    except Exception as e:
        logger.error(f"Error in langflow chat stream: {e}", exc_info=True)
        from api.provider_validation import resolve_chat_stream_error_message_async

        error_text = await resolve_chat_stream_error_message_async(e)
        display_text = _provider_error_display_text(error_text, full_response)
        if full_response:
            display_text = await resolve_chat_stream_error_message_async(display_text)

        conversation_state["messages"].append(
            {
                "role": "assistant",
                "content": display_text,
                "timestamp": datetime.now(),
                "error": True,
            }
        )
        store_id = _resolve_conversation_store_id(
            response_id,
            thread_id,
            previous_loaded_from_memory=previous_loaded_from_memory,
            mint_if_missing=True,
        )
        try:
            await _persist_error_conversation(user_id, store_id, conversation_state)
        except Exception as store_error:
            logger.error(f"Failed to store error conversation: {store_error}")
        yield _stream_error_chunk(display_text, store_id)


async def delete_user_conversation(user_id: str, response_id: str) -> bool:
    """Delete a conversation for a user from both memory and persistent storage.

    Returns:
        True  — conversation was found and deleted from at least one store.
        False — conversation did not exist in any store (confirmed not-found).

    Raises:
        Exception — on unexpected storage errors so callers can distinguish
                    a confirmed "not found" from a backend failure.
    """
    deleted = False

    # Delete from in-memory storage (cannot raise)
    if user_id in active_conversations and response_id in active_conversations[user_id]:
        del active_conversations[user_id][response_id]
        logger.debug(f"Deleted conversation {response_id} from memory for user {user_id}")
        deleted = True

    # Delete from persistent storage — let real errors propagate to the caller
    conversation_deleted = await conversation_persistence.delete_conversation_thread(
        user_id, response_id
    )
    if conversation_deleted:
        logger.debug(
            f"Deleted conversation {response_id} from persistent storage for user {user_id}"
        )
        deleted = True

    # Release session ownership (best-effort; never masks storage errors above)
    try:
        from services.session_ownership_service import session_ownership_service

        await session_ownership_service.release_session(user_id, response_id)
        logger.debug(f"Released session ownership for {response_id} for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to release session ownership: {e}")

    return deleted
