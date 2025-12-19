from http.client import HTTPException

from utils.logging_config import get_logger

logger = get_logger(__name__)

# Import persistent storage
from services.conversation_persistence_service import conversation_persistence

# In-memory storage for active conversation threads (preserves function calls)
active_conversations = {}


def get_user_conversations(user_id: str):
    """Get conversation metadata for a user from persistent storage"""
    return conversation_persistence.get_user_conversations(user_id)


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
                "content": "You are the OpenRAG Agent. You answer questions using retrieval, reasoning, and tool use.\nYou have access to several tools. Your job is to determine **which tool to use and when**.\n### Available Tools\n- OpenSearch Retrieval Tool:\n  Use this to search the indexed knowledge base. Use when the user asks about product details, internal concepts, processes, architecture, documentation, roadmaps, or anything that may be stored in the index.\n- Conversation History:\n  Use this to maintain continuity when the user is referring to previous turns. \n  Do not treat history as a factual source.\n- Conversation File Context:\n  Use this when the user asks about a document they uploaded or refers directly to its contents.\n  **IMPORTANT**: If you receive confirmation that a file was uploaded (e.g., \"Confirm that you received this file\"), the file content is already available in the conversation context. Do NOT attempt to ingest it as a URL.\n  Simply acknowledge the file and answer questions about it directly from the context.\n- URL Ingestion Tool:\n  Use this **only** when the user explicitly asks you to read, summarize, or analyze the content of a web URL (http:// or https://).\n  **Do NOT use this tool for filenames** (e.g., README.md, document.pdf, data.txt). These are file uploads, not URLs.\n  Only use this tool for actual web addresses that the user explicitly provides.\n  If unclear → ask a clarifying question.\n- Calculator / Expression Evaluation Tool:\n  Use this when the user asks to compare numbers, compute estimates, calculate totals, analyze pricing, or answer any question requiring mathematics or quantitative reasoning.\n  If the answer requires arithmetic, call the calculator tool rather than calculating internally.\n### Retrieval Decision Rules\nUse OpenSearch **whenever**:\n1. The question may be answered from internal or indexed data.\n2. The user references team names, product names, release plans, configurations, requirements, or official information.\n3. The user needs a factual, grounded answer.\nDo **not** use retrieval if:\n- The question is purely creative (e.g., storytelling, analogies) or personal preference.\n- The user simply wants text reformatted or rewritten from what is already present in the conversation.\nWhen uncertain → **Retrieve.** Retrieval is low risk and improves grounding.\n### File Upload vs URL Distinction\n**File uploads** (already in context):\n- Filenames like: README.md, document.pdf, notes.txt, data.csv\n- When you see file confirmation messages\n- Use conversation context directly - do NOT call URL tool\n**Web URLs** (need ingestion):\n- Start with http:// or https://\n- Examples: https://example.com, http://docs.site.org\n- User explicitly asks to fetch from web\n### Calculator Usage Rules\nUse the calculator when:\n- Performing arithmetic\n- Estimating totals\n- Comparing values\n- Modeling cost, time, effort, scale, or projections\nDo not perform math internally. **Call the calculator tool instead.**\n### Answer Construction Rules\n1. When asked: \"What is OpenRAG\", answer the following:\n\"OpenRAG is an open-source package for building agentic RAG systems. It supports integration with a wide range of orchestration tools, vector databases, and LLM providers. OpenRAG connects and amplifies three popular, proven open-source projects into one powerful platform:\n**Langflow** – Langflow is a powerful tool to build and deploy AI agents and MCP servers. [Read more](https://www.langflow.org/)\n**OpenSearch** – OpenSearch is an open source, search and observability suite that brings order to unstructured data at scale. [Read more](https://opensearch.org/)\n**Docling** – Docling simplifies document processing with advanced PDF understanding, OCR support, and seamless AI integrations. Parse PDFs, DOCX, PPTX, images & more. [Read more](https://www.docling.ai/)\"\n2. Synthesize retrieved or ingested content in your own words.\n3. Support factual claims with citations in the format:\n   (Source: <document_name_or_id>)\n4. If no supporting evidence is found:\n   Say: \"No relevant supporting sources were found for that request.\"\n5. Never invent facts or hallucinate details.\n6. Be concise, direct, and confident. \n7. Do not reveal internal chain-of-thought.",
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

    metadata_only = {
        "response_id": response_id,
        "title": title,
        "endpoint": "langflow",
        "created_at": conversation_state.get("created_at"),
        "last_activity": conversation_state.get("last_activity"),
        "previous_response_id": conversation_state.get("previous_response_id"),
        "filter_id": conversation_state.get("filter_id"),
        "total_messages": len(
            [msg for msg in messages if msg.get("role") in ["user", "assistant"]]
        ),
        # Don't store actual messages - Langflow has them
    }

    await conversation_persistence.store_conversation_thread(
        user_id, response_id, metadata_only
    )


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

    # Fallback to metadata-only conversations
    conversations = get_user_conversations(user_id)
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
        detected_tool_call = False  # Track if we've detected a tool call
        async for chunk in response:
            chunk_count += 1
            logger.debug(
                "Stream chunk received", chunk_count=chunk_count, chunk=str(chunk)
            )

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
            
            # Enhanced logging for tool call detection (Granite 3.3 8b investigation)
            chunk_attrs = dir(chunk) if hasattr(chunk, '__dict__') else []
            tool_related_attrs = [attr for attr in chunk_attrs if 'tool' in attr.lower() or 'call' in attr.lower() or 'retrieval' in attr.lower()]
            if tool_related_attrs:
                logger.info(
                    "Tool-related attributes found in chunk",
                    chunk_count=chunk_count,
                    attributes=tool_related_attrs,
                    chunk_type=type(chunk).__name__
                )

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
                
                # Log detailed chunk structure for investigation (especially for Granite 3.3 8b)
                if isinstance(chunk_data, dict):
                    # Check for any fields that might indicate tool usage
                    potential_tool_fields = {
                        k: v for k, v in chunk_data.items() 
                        if any(keyword in str(k).lower() for keyword in ['tool', 'call', 'retrieval', 'function', 'result', 'output'])
                    }
                    if potential_tool_fields:
                        logger.info(
                            "Potential tool-related fields in chunk",
                            chunk_count=chunk_count,
                            fields=list(potential_tool_fields.keys()),
                            sample_data=str(potential_tool_fields)[:500]
                        )

                # Middleware: Detect implicit tool calls and inject standardized events
                # This helps Granite 3.3 8b and other models that don't emit standard markers
                if isinstance(chunk_data, dict) and not detected_tool_call:
                    # Check if this chunk contains retrieval results
                    has_results = any([
                        'results' in chunk_data and isinstance(chunk_data.get('results'), list),
                        'outputs' in chunk_data and isinstance(chunk_data.get('outputs'), list),
                        'retrieved_documents' in chunk_data,
                        'retrieval_results' in chunk_data,
                    ])
                    
                    if has_results:
                        logger.info(
                            "Detected implicit tool call in backend, injecting synthetic event",
                            chunk_fields=list(chunk_data.keys())
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
                                "results": chunk_data.get('results') or chunk_data.get('outputs') or 
                                         chunk_data.get('retrieved_documents') or 
                                         chunk_data.get('retrieval_results') or []
                            }
                        }
                        # Send the synthetic event first
                        yield (json.dumps(synthetic_event, default=str) + "\n").encode("utf-8")
                        detected_tool_call = True  # Mark that we've injected a tool call
                
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

        # Check if response has output_text using getattr to avoid issues with special objects
        output_text = getattr(response, "output_text", None)
        if output_text is not None:
            response_text = output_text
            logger.info("Response generated", log_prefix=log_prefix, response=response_text)

            # Extract and store response_id if available
            response_id = getattr(response, "id", None) or getattr(
                response, "response_id", None
            )

            return response_text, response_id, response
        else:
            msg = "Nudge response missing output_text"
            error = getattr(response, "error", None)
            if error:
                error_msg = getattr(error, "message", None)
                if error_msg:
                    msg = error_msg
            raise ValueError(msg)
    except Exception as e:
        logger.error("Exception in non-streaming response", error=str(e))
        import traceback

        traceback.print_exc()
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
    filter_id: str = None,
):
    logger.debug(
        "async_chat called", user_id=user_id, previous_response_id=previous_response_id
    )

    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, previous_response_id)
    logger.debug(
        "Got conversation state", message_count=len(conversation_state["messages"])
    )

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)
    logger.debug(
        "Added user message", message_count=len(conversation_state["messages"])
    )

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
    logger.debug(
        "Got response", response_preview=response_text[:50], response_id=response_id
    )

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
    logger.debug(
        "Added assistant message", message_count=len(conversation_state["messages"])
    )

    # Store the conversation thread with its response_id
    if response_id:
        conversation_state["last_activity"] = datetime.now()
        await store_conversation_thread(user_id, response_id, conversation_state)
        logger.debug(
            "Stored conversation thread", user_id=user_id, response_id=response_id
        )

        # Debug: Check what's in user_conversations now
        conversations = get_user_conversations(user_id)
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
):
    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, previous_response_id)

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)

    # Store filter_id in conversation state if provided
    if filter_id:
        conversation_state["filter_id"] = filter_id

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
            await store_conversation_thread(user_id, response_id, conversation_state)
            logger.debug(
                f"Stored conversation thread for user {user_id} with response_id: {response_id}"
            )


# Async langflow function with conversation storage (non-streaming)
async def async_langflow_chat(
    langflow_client,
    flow_id: str,
    prompt: str,
    user_id: str,
    extra_headers: dict = None,
    previous_response_id: str = None,
    store_conversation: bool = True,
    filter_id: str = None,
):
    logger.debug(
        "async_langflow_chat called",
        user_id=user_id,
        previous_response_id=previous_response_id,
    )

    if store_conversation:
        # Get the specific conversation thread (or create new one)
        conversation_state = get_conversation_thread(user_id, previous_response_id)
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

    if not store_conversation:
        return response_text, response_id

    # Store the conversation thread with its response_id
    if response_id:
        conversation_state["last_activity"] = datetime.now()
        await store_conversation_thread(user_id, response_id, conversation_state)

        # Claim session ownership for this user
        try:
            from services.session_ownership_service import session_ownership_service

            session_ownership_service.claim_session(user_id, response_id)
            logger.debug(f"Claimed session {response_id} for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to claim session ownership: {e}")

        logger.debug(
            f"Stored langflow conversation thread for user {user_id} with response_id: {response_id}"
        )
        logger.debug(
            "Stored langflow conversation thread",
            user_id=user_id,
            response_id=response_id,
        )

        # Debug: Check what's in user_conversations now
        conversations = get_user_conversations(user_id)
        logger.debug(
            "User conversations updated",
            user_id=user_id,
            conversation_count=len(conversations),
            conversation_ids=list(conversations.keys()),
        )
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
    filter_id: str = None,
):
    logger.debug(
        "async_langflow_chat_stream called",
        user_id=user_id,
        previous_response_id=previous_response_id,
    )

    # Get the specific conversation thread (or create new one)
    conversation_state = get_conversation_thread(user_id, previous_response_id)

    # Add user message to conversation with timestamp
    from datetime import datetime

    user_message = {"role": "user", "content": prompt, "timestamp": datetime.now()}
    conversation_state["messages"].append(user_message)

    # Store filter_id in conversation state if provided
    if filter_id:
        conversation_state["filter_id"] = filter_id

    full_response = ""
    response_id = None
    collected_chunks = []  # Store all chunks for function call data

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
            collected_chunks.append(chunk_data)  # Collect all chunk data

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

    # Add the complete assistant response to message history with response_id, timestamp, and function call data
    if full_response:
        assistant_message = {
            "role": "assistant",
            "content": full_response,
            "response_id": response_id,
            "timestamp": datetime.now(),
            "chunks": collected_chunks,  # Store complete chunk data for function calls
        }
        conversation_state["messages"].append(assistant_message)

        # Store the conversation thread with its response_id
        if response_id:
            conversation_state["last_activity"] = datetime.now()
            await store_conversation_thread(user_id, response_id, conversation_state)

            # Claim session ownership for this user
        try:
            from services.session_ownership_service import session_ownership_service

            session_ownership_service.claim_session(user_id, response_id)
            logger.debug(f"Claimed session {response_id} for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to claim session ownership: {e}")

            logger.debug(
                f"Stored langflow conversation thread for user {user_id} with response_id: {response_id}"
            )


async def delete_user_conversation(user_id: str, response_id: str) -> bool:
    """Delete a conversation for a user from both memory and persistent storage (async, non-blocking)"""
    deleted = False

    try:
        # Delete from in-memory storage
        if user_id in active_conversations and response_id in active_conversations[user_id]:
            del active_conversations[user_id][response_id]
            logger.debug(f"Deleted conversation {response_id} from memory for user {user_id}")
            deleted = True

        # Delete from persistent storage
        conversation_deleted = await conversation_persistence.delete_conversation_thread(user_id, response_id)
        if conversation_deleted:
            logger.debug(f"Deleted conversation {response_id} from persistent storage for user {user_id}")
            deleted = True

        # Release session ownership
        try:
            from services.session_ownership_service import session_ownership_service
            session_ownership_service.release_session(user_id, response_id)
            logger.debug(f"Released session ownership for {response_id} for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to release session ownership: {e}")

        return deleted
    except Exception as e:
        logger.error(f"Error deleting conversation {response_id} for user {user_id}: {e}")
        return False
