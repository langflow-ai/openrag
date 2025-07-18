messages = [{"role": "system", "content": "You are a helpful assistant. Always use the search_tools to answer questions."}]

# Generic async response function for streaming
async def async_response_stream(client, prompt: str, model: str, previous_response_id: str = None, log_prefix: str = "response"):
    print(f"user ==> {prompt}")
    
    try:
        # Build request parameters
        request_params = {
            "model": model,
            "input": prompt,
            "stream": True
        }
        if previous_response_id is not None:
            request_params["previous_response_id"] = previous_response_id
        
        response = await client.responses.create(**request_params)
        
        full_response = ""
        chunk_count = 0
        async for chunk in response:
            chunk_count += 1
            print(f"[DEBUG] Chunk {chunk_count}: {chunk}")
            
            # Yield the raw event as JSON for the UI to process
            import json
            
            # Also extract text content for logging
            if hasattr(chunk, 'output_text') and chunk.output_text:
                full_response += chunk.output_text
            elif hasattr(chunk, 'delta') and chunk.delta:
                # Handle delta properly - it might be a dict or string
                if isinstance(chunk.delta, dict):
                    delta_text = chunk.delta.get('content', '') or chunk.delta.get('text', '') or str(chunk.delta)
                else:
                    delta_text = str(chunk.delta)
                full_response += delta_text
            
            # Send the raw event as JSON followed by newline for easy parsing
            try:
                # Try to serialize the chunk object
                if hasattr(chunk, 'model_dump'):
                    # Pydantic model
                    chunk_data = chunk.model_dump()
                elif hasattr(chunk, '__dict__'):
                    chunk_data = chunk.__dict__
                else:
                    chunk_data = str(chunk)
                
                yield (json.dumps(chunk_data, default=str) + '\n').encode('utf-8')
            except Exception as e:
                # Fallback to string representation
                print(f"[DEBUG] JSON serialization failed: {e}")
                yield (json.dumps({"error": f"Serialization failed: {e}", "raw": str(chunk)}) + '\n').encode('utf-8')
        
        print(f"[DEBUG] Stream complete. Total chunks: {chunk_count}")
        print(f"{log_prefix} ==> {full_response}")
        
    except Exception as e:
        print(f"[ERROR] Exception in streaming: {e}")
        import traceback
        traceback.print_exc()
        raise

# Generic async response function for non-streaming
async def async_response(client, prompt: str, model: str, previous_response_id: str = None, log_prefix: str = "response"):
    print(f"user ==> {prompt}")
    
    # Build request parameters
    request_params = {
        "model": model,
        "input": prompt,
        "stream": False
    }
    if previous_response_id is not None:
        request_params["previous_response_id"] = previous_response_id
    
    response = await client.responses.create(**request_params)
    
    response_text = response.output_text
    print(f"{log_prefix} ==> {response_text}")
    return response_text

# Unified streaming function for both chat and langflow
async def async_stream(client, prompt: str, model: str, previous_response_id: str = None, log_prefix: str = "response"):
    async for chunk in async_response_stream(client, prompt, model, previous_response_id=previous_response_id, log_prefix=log_prefix):
        yield chunk

# Async langflow function (non-streaming only)
async def async_langflow(langflow_client, flow_id: str, prompt: str):
    return await async_response(langflow_client, prompt, flow_id, log_prefix="langflow")

# Async langflow function for streaming (alias for compatibility)
async def async_langflow_stream(langflow_client, flow_id: str, prompt: str):
    print(f"[DEBUG] Starting langflow stream for prompt: {prompt}")
    try:
        async for chunk in async_stream(langflow_client, prompt, flow_id, log_prefix="langflow"):
            print(f"[DEBUG] Yielding chunk from langflow_stream: {chunk[:100]}...")
            yield chunk
        print(f"[DEBUG] Langflow stream completed")
    except Exception as e:
        print(f"[ERROR] Exception in langflow_stream: {e}")
        import traceback
        traceback.print_exc()
        raise

# Async chat function (non-streaming only)
async def async_chat(async_client, prompt: str, model: str = "gpt-4.1-mini", previous_response_id: str = None):
    global messages
    messages += [{"role": "user", "content": prompt}]
    return await async_response(async_client, prompt, model, previous_response_id=previous_response_id, log_prefix="agent")

# Async chat function for streaming (alias for compatibility)
async def async_chat_stream(async_client, prompt: str, model: str = "gpt-4.1-mini", previous_response_id: str = None):
    global messages
    messages += [{"role": "user", "content": prompt}]
    async for chunk in async_stream(async_client, prompt, model, previous_response_id=previous_response_id, log_prefix="agent"):
        yield chunk