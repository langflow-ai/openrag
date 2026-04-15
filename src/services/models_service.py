import httpx
import asyncio
from typing import Dict, List, Optional
from config.model_constants import (
    ANTHROPIC_DEFAULT_LANGUAGE_MODEL,
    ANTHROPIC_VALIDATION_MODELS,
    OLLAMA_DEFAULT_LANGUAGE_MODEL_PATTERN,
    OPENAI_DEFAULT_LANGUAGE_MODEL,
    OPENAI_VALIDATION_MODELS,
)
from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL, OPENAI_EMBEDDING_MODEL_PREFIX
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger

logger = get_logger(__name__)

KNOWN_PREFIXES = ["openai", "ollama", "watsonx", "anthropic"]

class ModelsService:
    """Service for fetching available models from different AI providers and managing a model registry."""

    # Registry for caching model-to-provider mapping
    _model_provider_registry: Dict[str, str] = {}
    _registry_lock = asyncio.Lock()

    def __init__(self):
        self.session_manager = None

    # Helper to add models to registry
    def add_models(self, models_res, provider, new_registry):
        if not models_res:
            return
        for m in models_res.get("language_models", []):
            new_registry[m["value"]] = provider
        for m in models_res.get("embedding_models", []):
            new_registry[m["value"]] = provider

    async def add_models_to_registry(self, models_res, provider):
        async with self._registry_lock:
            try:
                new_registry = ModelsService._model_provider_registry.copy()
                self.add_models(models_res, provider, new_registry)
                ModelsService._model_provider_registry = new_registry
            except Exception as e:
                logger.error(f"Error adding models to registry: {str(e)}")

    async def update_model_registry(self):
        """Fetch all models from all providers and update the internal registry.
        
        This method calls provider-specific methods to get the list of available
        models and stores the mapping in a registry for fast lookup.
        """
        from config.config_manager import config_manager
        
        async with self._registry_lock:
            try:
                config = config_manager.get_config()
                new_registry = {}

                # Fetch from providers
                
                # OpenAI
                if config.providers.openai.api_key:
                    try:
                        res = await self.get_openai_models(config.providers.openai.api_key, update_index=False)
                        self.add_models(res, "openai", new_registry)
                    except Exception as e:
                        logger.debug(f"Could not fetch OpenAI models for registry: {str(e)}")

                # Anthropic
                if config.providers.anthropic.api_key:
                    try:
                        res = await self.get_anthropic_models(config.providers.anthropic.api_key, update_index=False)
                        self.add_models(res, "anthropic", new_registry)
                    except Exception as e:
                        logger.debug(f"Could not fetch Anthropic models for registry: {str(e)}")

                # Ollama
                if config.providers.ollama.endpoint:
                    try:
                        res = await self.get_ollama_models(config.providers.ollama.endpoint, update_index=False)
                        self.add_models(res, "ollama", new_registry)
                    except Exception as e:
                        logger.debug(f"Could not fetch Ollama models for registry: {str(e)}")
                        
                # WatsonX
                if config.providers.watsonx.api_key:
                    try:
                        res = await self.get_ibm_models(
                            config.providers.watsonx.endpoint,
                            config.providers.watsonx.api_key,
                            config.providers.watsonx.project_id,
                            update_index=False
                        )
                        self.add_models(res, "watsonx", new_registry)
                    except Exception as e:
                        logger.debug(f"Could not fetch WatsonX models for registry: {str(e)}")

                ModelsService._model_provider_registry = new_registry
                logger.info(f"Model registry updated: {len(ModelsService._model_provider_registry)} models registered")
                
            except Exception as e:
                logger.error(f"Error updating model registry: {str(e)}")

    async def get_litellm_model_name(self, model_name: str, provider: Optional[str] = None) -> str:
        """Synchronous version of model formatting for when provider is already known.
        
        This is useful for synchronous contexts (like properties) where the provider
        information is already available and doesn't need to be looked up in the registry.
        """

        if not model_name:
            return ""
            
        # Skip formatting if already has a known provider prefix
        if any(model_name.startswith(p + "/") for p in KNOWN_PREFIXES):
            return model_name
            
        # Check if provider is explicitly given and not "openai"
        provider_lower = provider.lower() if provider else None
        
        if provider_lower is None:
            # Try looking in registry
            provider_lower = ModelsService._model_provider_registry.get(model_name)
            if provider_lower is None:
                await self.update_model_registry()
                provider_lower = ModelsService._model_provider_registry.get(model_name)

        if provider_lower is None:
            logger.warning(
                "Could not determine provider for model; using model name as-is",
                model_name=model_name,
            )
            return model_name  # OpenAI-compatible models work without a prefix
            
        return f"{provider_lower}/{model_name}" if provider_lower != "openai" else model_name

    async def get_openai_models(self, api_key: str, update_index: bool = True) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from OpenAI API with lightweight validation"""
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient() as client:
                # Lightweight validation: just check if API key is valid
                # This doesn't consume credits, only validates the key
                response = await client.get(
                    "https://api.openai.com/v1/models", headers=headers, timeout=10.0
                )

            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])

                # Filter for relevant models
                language_models = []
                embedding_models = []

                for model in models:
                    model_id = model.get("id", "")

                    # Language models (GPT models)
                    if model_id in OPENAI_VALIDATION_MODELS:
                        language_models.append(
                            {
                                "value": model_id,
                                "label": model_id,
                                "default": model_id == OPENAI_DEFAULT_LANGUAGE_MODEL,
                            }
                        )

                    # Embedding models
                    elif OPENAI_EMBEDDING_MODEL_PREFIX in model_id:
                        embedding_models.append(
                            {
                                "value": model_id,
                                "label": model_id,
                                "default": model_id == OPENAI_DEFAULT_EMBEDDING_MODEL,
                            }
                        )

                # Sort by name and ensure defaults are first
                language_models.sort(
                    key=lambda x: (not x.get("default", False), x["value"])
                )
                embedding_models.sort(
                    key=lambda x: (not x.get("default", False), x["value"])
                )

                if not language_models:
                    logger.warning(
                        "OpenAI API key is valid but no language models matched the validation list. "
                        "The API returned %d models, none matched OPENAI_VALIDATION_MODELS. "
                        "This may indicate a model naming scheme change.",
                        len(models),
                    )
                if not embedding_models:
                    logger.warning(
                        "OpenAI API key is valid but no embedding models were found matching prefix '%s'.",
                        OPENAI_EMBEDDING_MODEL_PREFIX,
                    )

                logger.info("OpenAI API key validated successfully without consuming credits")

                result = {
                    "language_models": language_models,
                    "embedding_models": embedding_models,
                }

                if update_index:
                    await self.add_models_to_registry(result, "openai")

                return result
            else:
                logger.error(f"Failed to fetch OpenAI models: {response.status_code}")
                raise Exception(
                    f"OpenAI API returned status code {response.status_code}, {response.text}"
                )

        except Exception as e:
            logger.error(f"Error fetching OpenAI models: {str(e)}")
            raise

    async def get_anthropic_models(self, api_key: str, update_index: bool = True) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from Anthropic API"""
        try:
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }

            # Validate API key with lightweight models endpoint and return curated models
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers=headers,
                    timeout=10.0,
                )

            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])

                # Filter for curated Anthropic models (same pattern as OpenAI validation list)
                language_models = []

                for model in models:
                    model_id = model.get("id", "")

                    if model_id in ANTHROPIC_VALIDATION_MODELS:
                        language_models.append(
                            {
                                "value": model_id,
                                "label": model_id,
                                "default": model_id == ANTHROPIC_DEFAULT_LANGUAGE_MODEL,
                            }
                        )

                # Sort by default first, then by name
                language_models.sort(
                    key=lambda x: (not x.get("default", False), x["value"])
                )

                if not language_models:
                    logger.warning(
                        "Anthropic API key is valid but no models matched the validation list. "
                        "The API returned %d models, none matched ANTHROPIC_VALIDATION_MODELS. "
                        "This may indicate a model naming scheme change.",
                        len(models),
                    )

                result = {
                    "language_models": language_models,
                    "embedding_models": [],
                }

                if update_index:
                    await self.add_models_to_registry(result, "anthropic")

                return result
            else:
                logger.error(f"Failed to validate Anthropic API key: {response.status_code}")
                raise Exception(
                    f"Anthropic API returned status code {response.status_code}, {response.text}"
                )

        except Exception as e:
            logger.error(f"Error fetching Anthropic models: {str(e)}")
            raise

    async def get_ollama_models(
        self, endpoint: str = None, update_index: bool = True
    ) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from Ollama API with tool calling capabilities for language models"""
        try:
            ollama_url = transform_localhost_url(endpoint)

            # API endpoints
            tags_url = f"{ollama_url}/api/tags"
            show_url = f"{ollama_url}/api/show"

            # Constants for JSON parsing
            JSON_MODELS_KEY = "models"
            JSON_NAME_KEY = "name"
            JSON_CAPABILITIES_KEY = "capabilities"
            DESIRED_CAPABILITY = "completion"
            TOOL_CALLING_CAPABILITY = "tools"

            async with httpx.AsyncClient() as client:
                # Fetch available models
                tags_response = await client.get(tags_url, timeout=10.0)
                tags_response.raise_for_status()
                models_data = tags_response.json()

                logger.debug(f"Available models: {models_data}")

                # Filter models based on capabilities
                language_models = []
                embedding_models = []

                models = models_data.get(JSON_MODELS_KEY, [])

                for model in models:
                    model_name = model.get(JSON_NAME_KEY, "")

                    if not model_name:
                        continue

                    logger.debug(f"Checking model: {model_name}")

                    # Check model capabilities
                    payload = {"model": model_name}
                    try:
                        show_response = await client.post(
                            show_url, json=payload, timeout=10.0
                        )
                        show_response.raise_for_status()
                        json_data = show_response.json()

                        capabilities = json_data.get(JSON_CAPABILITIES_KEY, [])
                        logger.debug(
                            f"Model: {model_name}, Capabilities: {capabilities}"
                        )

                        # Check if model has embedding capability
                        has_embedding = "embedding" in capabilities
                        # Check if model has required capabilities for language models
                        has_completion = DESIRED_CAPABILITY in capabilities
                        has_tools = TOOL_CALLING_CAPABILITY in capabilities

                        if has_embedding:
                            # Embedding models have embedding capability
                            embedding_models.append(
                                {
                                    "value": model_name,
                                    "label": model_name,
                                    "default": "nomic-embed-text" in model_name.lower(),
                                }
                            )
                        if has_completion and has_tools:
                            # Language models need both completion and tool calling
                            language_models.append(
                                {
                                    "value": model_name,
                                    "label": model_name,
                                    "default": OLLAMA_DEFAULT_LANGUAGE_MODEL_PATTERN
                                    in model_name.lower(),
                                }
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to check capabilities for model {model_name}: {str(e)}"
                        )
                        continue

                # Remove duplicates and sort
                language_models = list(
                    {m["value"]: m for m in language_models}.values()
                )
                embedding_models = list(
                    {m["value"]: m for m in embedding_models}.values()
                )

                language_models.sort(
                    key=lambda x: (not x.get("default", False), x["value"])
                )
                embedding_models.sort(key=lambda x: x["value"])

                logger.info(
                    f"Found {len(language_models)} language models with tool calling and {len(embedding_models)} embedding models"
                )

                result = {
                    "language_models": language_models,
                    "embedding_models": embedding_models,
                }

                if update_index:
                    await self.add_models_to_registry(result, "ollama")

                return result

        except Exception as e:
            logger.error(f"Error fetching Ollama models: {str(e)}")
            raise

    async def get_ibm_models(
        self, endpoint: str = None, api_key: str = None, project_id: str = None, update_index: bool = True
    ) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from IBM Watson API"""
        try:
            # Use provided endpoint or default
            watson_endpoint = endpoint

            # Get bearer token from IBM IAM
            bearer_token = None
            if api_key:
                async with httpx.AsyncClient() as client:
                    token_response = await client.post(
                        "https://iam.cloud.ibm.com/identity/token",
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data={
                            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                            "apikey": api_key,
                        },
                        timeout=10.0,
                    )

                    if token_response.status_code != 200:
                        raise Exception(
                            f"Failed to get IBM IAM token: {token_response.status_code} - {token_response.text}"
                        )

                    token_data = token_response.json()
                    bearer_token = token_data.get("access_token")

                    if not bearer_token:
                        raise Exception("No access_token in IBM IAM response")

            # Prepare headers for authentication
            headers = {
                "Content-Type": "application/json",
            }
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            if project_id:
                headers["Project-ID"] = project_id

            # Fetch foundation models using the correct endpoint
            models_url = f"{watson_endpoint}/ml/v1/foundation_model_specs"

            language_models = []
            embedding_models = []

            async with httpx.AsyncClient() as client:
                # Fetch text chat models
                text_params = {
                    "version": "2024-09-16",
                    "filters": "function_text_chat,!lifecycle_withdrawn",
                }
                if project_id:
                    text_params["project_id"] = project_id

                text_response = await client.get(
                    models_url, params=text_params, headers=headers, timeout=10.0
                )

                if text_response.status_code == 200:
                    text_data = text_response.json()
                    text_models = text_data.get("resources", [])
                    logger.info(f"Retrieved {len(text_models)} text chat models from Watson API")

                    for i, model in enumerate(text_models):
                        model_id = model.get("model_id", "")
                        model_name = model.get("name", model_id)

                        language_models.append(
                            {
                                "value": model_id,
                                "label": model_name or model_id,
                                "default": i == 0,  # First model is default
                            }
                        )
                else:
                    logger.warning(
                        f"Failed to retrieve text chat models. Status: {text_response.status_code}, "
                        f"Response: {text_response.text[:200]}"
                    )

                # Fetch embedding models
                embed_params = {
                    "version": "2024-09-16",
                    "filters": "function_embedding,!lifecycle_withdrawn",
                }
                if project_id:
                    embed_params["project_id"] = project_id

                embed_response = await client.get(
                    models_url, params=embed_params, headers=headers, timeout=10.0
                )

                if embed_response.status_code == 200:
                    embed_data = embed_response.json()
                    embed_models = embed_data.get("resources", [])
                    logger.info(f"Retrieved {len(embed_models)} embedding models from Watson API")

                    for i, model in enumerate(embed_models):
                        model_id = model.get("model_id", "")
                        model_name = model.get("name", model_id)

                        embedding_models.append(
                            {
                                "value": model_id,
                                "label": model_name or model_id,
                                "default": i == 0,  # First model is default
                            }
                        )
                else:
                    logger.warning(
                        f"Failed to retrieve embedding models. Status: {embed_response.status_code}, "
                        f"Response: {embed_response.text[:200]}"
                    )

            # Lightweight validation: API key is already validated by successfully getting bearer token
            # No need to make a generation request that consumes credits
            if bearer_token:
                logger.info("IBM Watson API key validated successfully without consuming credits")
            else:
                logger.warning("No bearer token available - API key validation may have failed")

            if not language_models and not embedding_models:
                # Provide more specific error message about missing models
                error_msg = (
                    "API key is valid, but no models are available. "
                    "This usually means your Watson Machine Learning (WML) project is not properly configured. "
                    "Please ensure: (1) Your watsonx.ai project is associated with a WML service instance, "
                    "and (2) The project has access to foundation models. "
                    "Visit your watsonx.ai project settings to configure the WML service association."
                )
                raise Exception(error_msg)

            result = {
                "language_models": language_models,
                "embedding_models": embedding_models,
            }

            if update_index:
                await self.add_models_to_registry(result, "watsonx")

            return result

        except Exception as e:
            logger.error(f"Error fetching IBM models: {str(e)}")
            raise
