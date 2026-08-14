from typing import Optional

from fastapi import Depends
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import get_openrag_config, is_azure_ai_enabled
from dependencies import get_models_service, get_current_user
from session_manager import User

logger = get_logger(__name__)


class OpenAIBody(BaseModel):
    api_key: Optional[str] = None


class AnthropicBody(BaseModel):
    api_key: Optional[str] = None


class IBMBody(BaseModel):
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    project_id: Optional[str] = None


class AzureAIFoundryBody(BaseModel):
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    api_version: Optional[str] = None
    deployment_name: Optional[str] = None
    llm_deployment_name: Optional[str] = None
    embedding_deployment_name: Optional[str] = None
    test_completion: bool = False


async def get_openai_models(
    body: Optional[OpenAIBody] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
):
    """Get available OpenAI models"""
    try:
        api_key = body.api_key if body else None
        if not api_key:
            try:
                config = get_openrag_config()
                api_key = config.providers.openai.api_key
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not api_key:
            return JSONResponse(
                {"error": "OpenAI API key is required either in request body or in configuration"},
                status_code=400,
            )

        models = await models_service.get_openai_models(api_key=api_key)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get OpenAI models: {str(e)}")
        return JSONResponse({"error": f"Failed to retrieve OpenAI models: {str(e)}"}, status_code=500)


async def get_anthropic_models(
    body: Optional[AnthropicBody] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
):
    """Get available Anthropic models"""
    try:
        api_key = body.api_key if body else None
        if not api_key:
            try:
                config = get_openrag_config()
                api_key = config.providers.anthropic.api_key
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not api_key:
            return JSONResponse(
                {"error": "Anthropic API key is required either in request body or in configuration"},
                status_code=400,
            )

        models = await models_service.get_anthropic_models(api_key=api_key)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get Anthropic models: {str(e)}")
        return JSONResponse({"error": f"Failed to retrieve Anthropic models: {str(e)}"}, status_code=500)


async def get_ollama_models(
    endpoint: Optional[str] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
):
    """Get available Ollama models"""
    try:
        if not endpoint:
            try:
                config = get_openrag_config()
                endpoint = config.providers.ollama.endpoint
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not endpoint:
            return JSONResponse(
                {"error": "Endpoint is required either as query parameter or in configuration"},
                status_code=400,
            )

        models = await models_service.get_ollama_models(endpoint=endpoint)
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get Ollama models: {str(e)}")
        return JSONResponse({"error": f"Failed to retrieve Ollama models: {str(e)}"}, status_code=500)


async def get_ibm_models(
    body: Optional[IBMBody] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
):
    """Get available IBM Watson models"""
    try:
        api_key = body.api_key if body else None
        endpoint = body.endpoint if body else None
        project_id = body.project_id if body else None

        config = get_openrag_config()
        if not api_key:
            try:
                api_key = config.providers.watsonx.api_key
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not api_key:
            return JSONResponse(
                {"error": "WatsonX API key is required either in request body or in configuration"},
                status_code=400,
            )

        if not endpoint:
            try:
                endpoint = config.providers.watsonx.endpoint
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not endpoint:
            return JSONResponse(
                {"error": "Endpoint is required either in request body or in configuration"},
                status_code=400,
            )

        if not project_id:
            try:
                project_id = config.providers.watsonx.project_id
            except Exception as e:
                logger.error(f"Failed to get config: {e}")

        if not project_id:
            return JSONResponse(
                {"error": "Project ID is required either in request body or in configuration"},
                status_code=400,
            )

        models = await models_service.get_ibm_models(
            endpoint=endpoint, api_key=api_key, project_id=project_id
        )
        return JSONResponse(models)
    except Exception as e:
        logger.error(f"Failed to get IBM models: {str(e)}")
        return JSONResponse({"error": f"Failed to retrieve IBM models: {str(e)}"}, status_code=500)


async def get_azure_ai_foundry_models(
    body: Optional[AzureAIFoundryBody] = None,
    models_service=Depends(get_models_service),
    user: User = Depends(get_current_user),
):
    """Get available Azure AI Foundry models.

    For MVP, Azure AI Foundry deployment names are user-managed (no catalog API).
    This endpoint validates credentials with a lightweight call and returns the
    provided deployment_name as the available model entry.

    When test_completion=True, runs real inference calls against the deployment
    names to verify end-to-end connectivity (consumes credits).
    """
    if not is_azure_ai_enabled():
        return JSONResponse({"error": "Azure AI providers are not enabled"}, status_code=404)

    import httpx

    from api.provider_validation import (
        _build_azure_ai_foundry_url,
        _test_azure_ai_foundry_completion,
        _test_azure_ai_foundry_embedding,
    )

    try:
        config = get_openrag_config()

        api_key = (body.api_key if body else None) or config.providers.azure_ai_foundry.api_key
        endpoint = (body.endpoint if body else None) or config.providers.azure_ai_foundry.endpoint
        api_version = (
            body.api_version if body else None
        ) or config.providers.azure_ai_foundry.api_version
        deployment_name = body.deployment_name if body else None
        llm_deployment_name = (body.llm_deployment_name if body else None) or deployment_name
        embedding_deployment_name = body.embedding_deployment_name if body else None
        test_completion = body.test_completion if body else False

        if not api_key:
            return JSONResponse(
                {
                    "error": "Azure AI Foundry API key is required either in request body or in configuration"
                },
                status_code=400,
            )
        if not endpoint:
            return JSONResponse(
                {
                    "error": "Azure AI Foundry endpoint is required either in request body or in configuration"
                },
                status_code=400,
            )

        # Full inference test path — validates deployment names with real calls
        if test_completion:
            if not llm_deployment_name and not embedding_deployment_name:
                return JSONResponse(
                    {"error": "At least one deployment name is required to test the connection."},
                    status_code=400,
                )

            language_models = []
            embedding_models = []
            errors = []

            if llm_deployment_name:
                try:
                    await _test_azure_ai_foundry_completion(
                        api_key, llm_deployment_name, endpoint, api_version
                    )
                    language_models.append(
                        {"value": llm_deployment_name, "label": llm_deployment_name}
                    )
                    logger.info(f"Azure AI Foundry LLM test passed for '{llm_deployment_name}'")
                except Exception as e:
                    errors.append(f"LLM deployment '{llm_deployment_name}': {str(e)}")

            if embedding_deployment_name:
                try:
                    await _test_azure_ai_foundry_embedding(
                        api_key, embedding_deployment_name, endpoint, api_version
                    )
                    embedding_models.append(
                        {"value": embedding_deployment_name, "label": embedding_deployment_name}
                    )
                    logger.info(
                        f"Azure AI Foundry embedding test passed for '{embedding_deployment_name}'"
                    )
                except Exception as e:
                    errors.append(f"Embedding deployment '{embedding_deployment_name}': {str(e)}")

            if errors:
                return JSONResponse({"error": "; ".join(errors)}, status_code=400)

            return JSONResponse(
                {"language_models": language_models, "embedding_models": embedding_models}
            )

        # Lightweight credential check — validates endpoint + API key without consuming credits
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    _build_azure_ai_foundry_url(endpoint, api_version=api_version),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )
                # 200 or 404 (no models listed yet) both indicate valid credentials
                if response.status_code == 401:
                    return JSONResponse(
                        {"error": "Invalid API key. Verify the key in Azure AI Foundry portal."},
                        status_code=400,
                    )
                if response.status_code == 403:
                    return JSONResponse(
                        {
                            "error": "Access denied. Verify the API key has the required permissions."
                        },
                        status_code=400,
                    )
        except httpx.TimeoutException:
            return JSONResponse(
                {"error": "Azure AI Foundry endpoint did not respond. Check the endpoint URL."},
                status_code=400,
            )
        except Exception as e:
            return JSONResponse(
                {"error": f"Could not connect to Azure AI Foundry endpoint: {str(e)}"},
                status_code=400,
            )

        # Try to fetch the deployed model list from the resource endpoint.
        # Azure AI Foundry resource-level endpoints return an OpenAI-compatible
        # GET /models response: {"data": [{"id": "<deployment>", ...}, ...]}
        language_models = []
        embedding_models = []

        try:
            async with httpx.AsyncClient() as client:
                list_response = await client.get(
                    _build_azure_ai_foundry_url(endpoint, api_version=api_version),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )
                logger.info(f"Azure AI Foundry GET /models status: {list_response.status_code}")
                logger.debug(f"Azure AI Foundry GET /models body: {list_response.text[:500]}")
                if list_response.status_code == 200:
                    data = list_response.json()
                    entries = data.get("data", [])
                    for entry in entries:
                        model_id = entry.get("id", "")
                        if not model_id:
                            continue
                        item = {"value": model_id, "label": model_id}
                        # Heuristic: names containing "embed" go to embedding; rest to language.
                        if "embed" in model_id.lower():
                            embedding_models.append(item)
                        else:
                            language_models.append(item)
                    logger.info(
                        f"Azure AI Foundry models parsed: {len(language_models)} LLM, {len(embedding_models)} embedding"
                    )
        except Exception as e:
            logger.warning(f"Azure AI Foundry GET /models failed: {e}")
            pass  # Fall through to config-based fallback below

        # If the dynamic list came back empty, fall back to stored deployment names.
        # These are persisted in the provider config independently of the active
        # llm_provider/embedding_provider so they survive provider switches.
        if not language_models and not embedding_models:
            if deployment_name:
                entry = {"value": deployment_name, "label": deployment_name}
                language_models.append(entry)
                embedding_models.append(entry)
            else:
                stored_llm = config.providers.azure_ai_foundry.llm_deployment_name
                stored_embed = config.providers.azure_ai_foundry.embedding_deployment_name
                if stored_llm:
                    language_models.append({"value": stored_llm, "label": stored_llm})
                if stored_embed:
                    embedding_models.append({"value": stored_embed, "label": stored_embed})

        return JSONResponse(
            {"language_models": language_models, "embedding_models": embedding_models}
        )
    except Exception as e:
        logger.error(f"Failed to get Azure AI Foundry models: {str(e)}")
        return JSONResponse(
            {"error": "Failed to retrieve Azure AI Foundry models"}, status_code=500
        )
