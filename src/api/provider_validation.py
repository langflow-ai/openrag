"""Provider validation utilities for testing API keys and models during onboarding."""

import json
import httpx
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _parse_json_error_message(error_text: str) -> str:
    """Parse JSON error message and extract just the message field."""
    try:
        # Try to parse as JSON
        error_data = json.loads(error_text)
        
        if isinstance(error_data, dict):
            # WatsonX format: {"errors": [{"code": "...", "message": "..."}], ...}
            if "errors" in error_data and isinstance(error_data["errors"], list):
                errors = error_data["errors"]
                if len(errors) > 0 and isinstance(errors[0], dict):
                    message = errors[0].get("message", "")
                    if message:
                        return message
                    code = errors[0].get("code", "")
                    if code:
                        return f"Error: {code}"
            
            # OpenAI format: {"error": {"message": "...", "type": "...", "code": "..."}}
            if "error" in error_data:
                error_obj = error_data["error"]
                if isinstance(error_obj, dict):
                    message = error_obj.get("message", "")
                    if message:
                        return message
            
            # Direct message field
            if "message" in error_data:
                return error_data["message"]
            
            # Generic format: {"detail": "..."}
            if "detail" in error_data:
                return error_data["detail"]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    
    # Return original text if not JSON or can't parse
    return error_text


def _extract_error_details(response: httpx.Response) -> str:
    """Extract detailed error message from API response."""
    try:
        # Try to parse JSON error response
        error_data = response.json()
        
        # Common error response formats
        if isinstance(error_data, dict):
            # WatsonX format: {"errors": [{"code": "...", "message": "..."}], ...}
            if "errors" in error_data and isinstance(error_data["errors"], list):
                errors = error_data["errors"]
                if len(errors) > 0 and isinstance(errors[0], dict):
                    # Extract just the message from the first error
                    message = errors[0].get("message", "")
                    if message:
                        return message
                    # Fallback to code if no message
                    code = errors[0].get("code", "")
                    if code:
                        return f"Error: {code}"
            
            # OpenAI format: {"error": {"message": "...", "type": "...", "code": "..."}}
            if "error" in error_data:
                error_obj = error_data["error"]
                if isinstance(error_obj, dict):
                    message = error_obj.get("message", "")
                    error_type = error_obj.get("type", "")
                    code = error_obj.get("code", "")
                    if message:
                        details = message
                        if error_type:
                            details += f" (type: {error_type})"
                        if code:
                            details += f" (code: {code})"
                        return details
            
            # Anthropic format: {"error": {"message": "...", "type": "..."}}
            if "message" in error_data:
                return error_data["message"]
            
            # Generic format: {"message": "..."}
            if "detail" in error_data:
                return error_data["detail"]
        
        # If JSON parsing worked but no structured error found, try parsing text
        response_text = response.text[:500]
        parsed = _parse_json_error_message(response_text)
        if parsed != response_text:
            return parsed
        return response_text
        
    except (json.JSONDecodeError, ValueError):
        # If JSON parsing fails, try parsing the text as JSON string
        response_text = response.text[:500] if response.text else f"HTTP {response.status_code}"
        parsed = _parse_json_error_message(response_text)
        if parsed != response_text:
            return parsed
        return response_text


async def validate_provider_setup(
    provider: str,
    api_key: str = None,
    embedding_model: str = None,
    llm_model: str = None,
    endpoint: str = None,
    project_id: str = None,
    test_completion: bool = False,
) -> None:
    """
    Validate provider setup by testing completion with tool calling and embedding.

    Args:
        provider: Provider name ('openai', 'watsonx', 'ollama', 'anthropic')
        api_key: API key for the provider (optional for ollama)
        embedding_model: Embedding model to test
        llm_model: LLM model to test
        endpoint: Provider endpoint (required for ollama and watsonx)
        project_id: Project ID (required for watsonx)
        test_completion: If True, performs full validation with completion/embedding tests (consumes credits).
                        If False, performs lightweight validation (no credits consumed). Default: False.

    Raises:
        Exception: If validation fails, raises the original exception with the actual error message.
    """
    provider_lower = provider.lower()

    try:
        logger.info(f"Starting validation for provider: {provider_lower} (test_completion={test_completion})")

        if test_completion:
            # Full validation with completion/embedding tests (consumes credits)
            if embedding_model:
                # Test embedding
                await test_embedding(
                    provider=provider_lower,
                    api_key=api_key,
                    embedding_model=embedding_model,
                    endpoint=endpoint,
                    project_id=project_id,
                )
            elif llm_model:
                # Test completion with tool calling
                await test_completion_with_tools(
                    provider=provider_lower,
                    api_key=api_key,
                    llm_model=llm_model,
                    endpoint=endpoint,
                    project_id=project_id,
                )
        else:
            # Lightweight validation (no credits consumed)
            await test_lightweight_health(
                provider=provider_lower,
                api_key=api_key,
                endpoint=endpoint,
                project_id=project_id,
            )

        logger.info(f"Validation successful for provider: {provider_lower}")

    except Exception as e:
        logger.error(f"Validation failed for provider {provider_lower}: {str(e)}")
        # Preserve the original error message instead of replacing it with a generic one
        raise


async def test_lightweight_health(
    provider: str,
    api_key: str = None,
    endpoint: str = None,
    project_id: str = None,
) -> None:
    """Test provider health with lightweight check (no credits consumed)."""

    if provider == "openai":
        await _test_openai_lightweight_health(api_key)
    elif provider == "watsonx":
        await _test_watsonx_lightweight_health(api_key, endpoint, project_id)
    elif provider == "ollama":
        await _test_ollama_lightweight_health(endpoint)
    elif provider == "anthropic":
        await _test_anthropic_lightweight_health(api_key)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def test_completion_with_tools(
    provider: str,
    api_key: str = None,
    llm_model: str = None,
    endpoint: str = None,
    project_id: str = None,
) -> None:
    """Test completion with tool calling for the provider."""

    if provider == "openai":
        await _test_openai_completion_with_tools(api_key, llm_model)
    elif provider == "watsonx":
        await _test_watsonx_completion_with_tools(api_key, llm_model, endpoint, project_id)
    elif provider == "ollama":
        await _test_ollama_completion_with_tools(llm_model, endpoint)
    elif provider == "anthropic":
        await _test_anthropic_completion_with_tools(api_key, llm_model)
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def test_embedding(
    provider: str,
    api_key: str = None,
    embedding_model: str = None,
    endpoint: str = None,
    project_id: str = None,
) -> None:
    """Test embedding generation for the provider."""

    if provider == "openai":
        await _test_openai_embedding(api_key, embedding_model)
    elif provider == "watsonx":
        await _test_watsonx_embedding(api_key, embedding_model, endpoint, project_id)
    elif provider == "ollama":
        await _test_ollama_embedding(embedding_model, endpoint)
    else:
        raise ValueError(f"Unknown provider: {provider}")


# OpenAI validation functions
async def _test_openai_lightweight_health(api_key: str) -> None:
    """Test OpenAI API key validity with lightweight check.
    
    Only checks if the API key is valid without consuming credits.
    Uses the /v1/models endpoint which doesn't consume credits.
    """
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient() as client:
            # Use /v1/models endpoint which validates the key without consuming credits
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers=headers,
                timeout=10.0,  # Short timeout for lightweight check
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"OpenAI lightweight health check failed: {response.status_code} - {error_details}")
                raise Exception(f"OpenAI API key validation failed: {error_details}")

            logger.info("OpenAI lightweight health check passed")

    except httpx.TimeoutException:
        logger.error("OpenAI lightweight health check timed out")
        raise Exception("OpenAI API request timed out")
    except Exception as e:
        logger.error(f"OpenAI lightweight health check failed: {str(e)}")
        raise


async def _test_openai_completion_with_tools(api_key: str, llm_model: str) -> None:
    """Test OpenAI completion with tool calling."""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Simple tool calling test
        base_payload = {
            "model": llm_model,
            "messages": [
                {"role": "user", "content": "What tools do you have available?"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {
                                    "type": "string",
                                    "description": "The city and state"
                                }
                            },
                            "required": ["location"]
                        }
                    }
                }
            ],
        }

        async with httpx.AsyncClient() as client:
            # Try with max_tokens first
            payload = {**base_payload, "max_tokens": 50}
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            # If max_tokens doesn't work, try with max_completion_tokens
            if response.status_code != 200:
                logger.info("max_tokens parameter failed, trying max_completion_tokens instead")
                payload = {**base_payload, "max_completion_tokens": 50}
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30.0,
                )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"OpenAI completion test failed: {response.status_code} - {error_details}")
                raise Exception(f"OpenAI API error: {error_details}")

            logger.info("OpenAI completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("OpenAI completion test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"OpenAI completion test failed: {str(e)}")
        raise


async def _test_openai_embedding(api_key: str, embedding_model: str) -> None:
    """Test OpenAI embedding generation."""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": embedding_model,
            "input": "test embedding",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"OpenAI embedding test failed: {response.status_code} - {error_details}")
                raise Exception(f"OpenAI API error: {error_details}")

            data = response.json()
            if not data.get("data") or len(data["data"]) == 0:
                raise Exception("No embedding data returned")

            logger.info("OpenAI embedding test passed")

    except httpx.TimeoutException:
        logger.error("OpenAI embedding test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"OpenAI embedding test failed: {str(e)}")
        raise


# IBM Watson validation functions
async def _test_watsonx_lightweight_health(
    api_key: str, endpoint: str, project_id: str
) -> None:
    """Test WatsonX API key validity with lightweight check.
    
    Only checks if the API key is valid by getting a bearer token.
    Does not consume credits by avoiding model inference requests.
    """
    try:
        # Get bearer token from IBM IAM - this validates the API key without consuming credits
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://iam.cloud.ibm.com/identity/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
                timeout=10.0,  # Short timeout for lightweight check
            )

            if token_response.status_code != 200:
                error_details = _extract_error_details(token_response)
                logger.error(f"IBM IAM token request failed: {token_response.status_code} - {error_details}")
                raise Exception(f"Failed to authenticate with IBM Watson: {error_details}")

            bearer_token = token_response.json().get("access_token")
            if not bearer_token:
                raise Exception("No access token received from IBM")

            logger.info("WatsonX lightweight health check passed - API key is valid")

    except httpx.TimeoutException:
        logger.error("WatsonX lightweight health check timed out")
        raise Exception("WatsonX API request timed out")
    except Exception as e:
        logger.error(f"WatsonX lightweight health check failed: {str(e)}")
        raise


async def _test_watsonx_completion_with_tools(
    api_key: str, llm_model: str, endpoint: str, project_id: str
) -> None:
    """Test IBM Watson completion with tool calling."""
    try:
        # Get bearer token from IBM IAM
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://iam.cloud.ibm.com/identity/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
                timeout=30.0,
            )

            if token_response.status_code != 200:
                error_details = _extract_error_details(token_response)
                logger.error(f"IBM IAM token request failed: {token_response.status_code} - {error_details}")
                raise Exception(f"Failed to authenticate with IBM Watson: {error_details}")

            bearer_token = token_response.json().get("access_token")
            if not bearer_token:
                raise Exception("No access token received from IBM")

        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }

        # Test completion with tools
        url = f"{endpoint}/ml/v1/text/chat"
        params = {"version": "2024-09-16"}
        payload = {
            "model_id": llm_model,
            "project_id": project_id,
            "messages": [
                {"role": "user", "content": "What tools do you have available?"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {
                                    "type": "string",
                                    "description": "The city and state"
                                }
                            },
                            "required": ["location"]
                        }
                    }
                }
            ],
            "max_tokens": 50,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"IBM Watson completion test failed: {response.status_code} - {error_details}")
                # If error_details is still JSON, parse it to extract just the message
                parsed_details = _parse_json_error_message(error_details)
                raise Exception(f"IBM Watson API error: {parsed_details}")

            logger.info("IBM Watson completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("IBM Watson completion test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"IBM Watson completion test failed: {str(e)}")
        # If the error message contains JSON, parse it to extract just the message
        error_str = str(e)
        if "IBM Watson API error: " in error_str:
            json_part = error_str.split("IBM Watson API error: ", 1)[1]
            parsed_message = _parse_json_error_message(json_part)
            if parsed_message != json_part:
                raise Exception(f"IBM Watson API error: {parsed_message}")
        raise


async def _test_watsonx_embedding(
    api_key: str, embedding_model: str, endpoint: str, project_id: str
) -> None:
    """Test IBM Watson embedding generation."""
    try:
        # Get bearer token from IBM IAM
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://iam.cloud.ibm.com/identity/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
                timeout=30.0,
            )

            if token_response.status_code != 200:
                error_details = _extract_error_details(token_response)
                logger.error(f"IBM IAM token request failed: {token_response.status_code} - {error_details}")
                raise Exception(f"Failed to authenticate with IBM Watson: {error_details}")

            bearer_token = token_response.json().get("access_token")
            if not bearer_token:
                raise Exception("No access token received from IBM")

        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }

        # Test embedding
        url = f"{endpoint}/ml/v1/text/embeddings"
        params = {"version": "2024-09-16"}
        payload = {
            "model_id": embedding_model,
            "project_id": project_id,
            "inputs": ["test embedding"],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"IBM Watson embedding test failed: {response.status_code} - {error_details}")
                # If error_details is still JSON, parse it to extract just the message
                parsed_details = _parse_json_error_message(error_details)
                raise Exception(f"IBM Watson API error: {parsed_details}")

            data = response.json()
            if not data.get("results") or len(data["results"]) == 0:
                raise Exception("No embedding data returned")

            logger.info("IBM Watson embedding test passed")

    except httpx.TimeoutException:
        logger.error("IBM Watson embedding test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"IBM Watson embedding test failed: {str(e)}")
        # If the error message contains JSON, parse it to extract just the message
        error_str = str(e)
        if "IBM Watson API error: " in error_str:
            json_part = error_str.split("IBM Watson API error: ", 1)[1]
            parsed_message = _parse_json_error_message(json_part)
            if parsed_message != json_part:
                raise Exception(f"IBM Watson API error: {parsed_message}")
        raise


# Ollama validation functions
async def _test_ollama_lightweight_health(endpoint: str) -> None:
    """Test Ollama availability with lightweight status check.
    
    Only checks if the endpoint returns a 200 status without fetching data.
    """
    try:
        ollama_url = transform_localhost_url(endpoint)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                ollama_url,
                timeout=10.0,  # Short timeout for lightweight check
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"Ollama lightweight health check failed: {response.status_code} - {error_details}")
                raise Exception(f"Ollama endpoint not responding: {error_details}")

            logger.info("Ollama lightweight health check passed")

    except httpx.TimeoutException:
        logger.error("Ollama lightweight health check timed out")
        raise Exception("Ollama endpoint timed out")
    except Exception as e:
        logger.error(f"Ollama lightweight health check failed: {str(e)}")
        raise


async def _test_ollama_completion_with_tools(llm_model: str, endpoint: str) -> None:
    """Test Ollama completion with tool calling."""
    try:
        ollama_url = transform_localhost_url(endpoint)
        url = f"{ollama_url}/api/chat"

        payload = {
            "model": llm_model,
            "messages": [
                {"role": "user", "content": "What tools do you have available?"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {
                                    "type": "string",
                                    "description": "The city and state"
                                }
                            },
                            "required": ["location"]
                        }
                    }
                }
            ],
            "stream": False,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                timeout=60.0,  # Increased timeout for Ollama when potentially busy
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"Ollama completion test failed: {response.status_code} - {error_details}")
                raise Exception(f"Ollama API error: {error_details}")

            logger.info("Ollama completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("Ollama completion test timed out")
        raise httpx.TimeoutException("Ollama is busy or model inference timed out")
    except Exception as e:
        logger.error(f"Ollama completion test failed: {str(e)}")
        raise


async def _test_ollama_embedding(embedding_model: str, endpoint: str) -> None:
    """Test Ollama embedding generation."""
    try:
        ollama_url = transform_localhost_url(endpoint)
        url = f"{ollama_url}/api/embeddings"

        payload = {
            "model": embedding_model,
            "prompt": "test embedding",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                timeout=60.0,  # Increased timeout for Ollama when potentially busy
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"Ollama embedding test failed: {response.status_code} - {error_details}")
                raise Exception(f"Ollama API error: {error_details}")

            data = response.json()
            if not data.get("embedding"):
                raise Exception("No embedding data returned")

            logger.info("Ollama embedding test passed")

    except httpx.TimeoutException:
        logger.error("Ollama embedding test timed out")
        raise httpx.TimeoutException("Ollama is busy or embedding generation timed out")
    except Exception as e:
        logger.error(f"Ollama embedding test failed: {str(e)}")
        raise


# Anthropic validation functions
async def _test_anthropic_lightweight_health(api_key: str) -> None:
    """Test Anthropic API key validity with lightweight check.
    
    Only checks if the API key is valid without consuming credits.
    Uses a minimal messages request with max_tokens=1 to validate the key.
    """
    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Minimal validation request - uses cheapest model with minimal tokens
        payload = {
            "model": "claude-3-5-haiku-latest",  # Cheapest model
            "max_tokens": 1,  # Minimum tokens to validate key
            "messages": [{"role": "user", "content": "test"}],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=10.0,  # Short timeout for lightweight check
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"Anthropic lightweight health check failed: {response.status_code} - {error_details}")
                raise Exception(f"Anthropic API key validation failed: {error_details}")

            logger.info("Anthropic lightweight health check passed")

    except httpx.TimeoutException:
        logger.error("Anthropic lightweight health check timed out")
        raise Exception("Anthropic API request timed out")
    except Exception as e:
        logger.error(f"Anthropic lightweight health check failed: {str(e)}")
        raise


async def _test_anthropic_completion_with_tools(api_key: str, llm_model: str) -> None:
    """Test Anthropic completion with tool calling."""
    try:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Simple tool calling test with Anthropic's format
        payload = {
            "model": llm_model,
            "max_tokens": 50,
            "messages": [
                {"role": "user", "content": "What tools do you have available?"}
            ],
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get the current weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state"
                            }
                        },
                        "required": ["location"]
                    }
                }
            ],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_details = _extract_error_details(response)
                logger.error(f"Anthropic completion test failed: {response.status_code} - {error_details}")
                raise Exception(f"Anthropic API error: {error_details}")

            logger.info("Anthropic completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("Anthropic completion test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"Anthropic completion test failed: {str(e)}")
        raise
