"""Provider validation utilities for testing API keys and models during onboarding."""

import httpx
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def validate_provider_setup(
    provider: str,
    api_key: str = None,
    embedding_model: str = None,
    llm_model: str = None,
    endpoint: str = None,
    project_id: str = None,
) -> None:
    """
    Validate provider setup by testing completion with tool calling and embedding.

    Args:
        provider: Provider name ('openai', 'watsonx', 'ollama')
        api_key: API key for the provider (optional for ollama)
        embedding_model: Embedding model to test
        llm_model: LLM model to test
        endpoint: Provider endpoint (required for ollama and watsonx)
        project_id: Project ID (required for watsonx)

    Raises:
        Exception: If validation fails with message "Setup failed, please try again or select a different provider."
    """
    provider_lower = provider.lower()

    try:
        logger.info(f"Starting validation for provider: {provider_lower}")

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
        

        logger.info(f"Validation successful for provider: {provider_lower}")

    except Exception as e:
        logger.error(f"Validation failed for provider {provider_lower}: {str(e)}")
        raise Exception("Setup failed, please try again or select a different provider.")


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
async def _test_openai_completion_with_tools(api_key: str, llm_model: str) -> None:
    """Test OpenAI completion with tool calling."""
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Simple tool calling test
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
            "max_tokens": 50,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"OpenAI completion test failed: {response.status_code} - {response.text}")
                raise Exception(f"OpenAI API error: {response.status_code}")

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
                logger.error(f"OpenAI embedding test failed: {response.status_code} - {response.text}")
                raise Exception(f"OpenAI API error: {response.status_code}")

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
                logger.error(f"IBM IAM token request failed: {token_response.status_code}")
                raise Exception("Failed to authenticate with IBM Watson")

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
                logger.error(f"IBM Watson completion test failed: {response.status_code} - {response.text}")
                raise Exception(f"IBM Watson API error: {response.status_code}")

            logger.info("IBM Watson completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("IBM Watson completion test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"IBM Watson completion test failed: {str(e)}")
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
                logger.error(f"IBM IAM token request failed: {token_response.status_code}")
                raise Exception("Failed to authenticate with IBM Watson")

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
                logger.error(f"IBM Watson embedding test failed: {response.status_code} - {response.text}")
                raise Exception(f"IBM Watson API error: {response.status_code}")

            data = response.json()
            if not data.get("results") or len(data["results"]) == 0:
                raise Exception("No embedding data returned")

            logger.info("IBM Watson embedding test passed")

    except httpx.TimeoutException:
        logger.error("IBM Watson embedding test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"IBM Watson embedding test failed: {str(e)}")
        raise


# Ollama validation functions
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
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"Ollama completion test failed: {response.status_code} - {response.text}")
                raise Exception(f"Ollama API error: {response.status_code}")

            logger.info("Ollama completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("Ollama completion test timed out")
        raise Exception("Request timed out")
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
                timeout=30.0,
            )

            if response.status_code != 200:
                logger.error(f"Ollama embedding test failed: {response.status_code} - {response.text}")
                raise Exception(f"Ollama API error: {response.status_code}")

            data = response.json()
            if not data.get("embedding"):
                raise Exception("No embedding data returned")

            logger.info("Ollama embedding test passed")

    except httpx.TimeoutException:
        logger.error("Ollama embedding test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"Ollama embedding test failed: {str(e)}")
        raise


# Anthropic validation functions
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
                logger.error(f"Anthropic completion test failed: {response.status_code} - {response.text}")
                raise Exception(f"Anthropic API error: {response.status_code}")

            logger.info("Anthropic completion with tool calling test passed")

    except httpx.TimeoutException:
        logger.error("Anthropic completion test timed out")
        raise Exception("Request timed out")
    except Exception as e:
        logger.error(f"Anthropic completion test failed: {str(e)}")
        raise
