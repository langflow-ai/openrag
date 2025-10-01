import httpx
from typing import Dict, List
from utils.container_utils import transform_localhost_url
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ModelsService:
    """Service for fetching available models from different AI providers"""

    OLLAMA_EMBEDDING_MODELS = [
        "nomic-embed-text",
        "mxbai-embed-large",
        "snowflake-arctic-embed",
        "all-minilm",
        "bge-m3",
        "bge-large",
        "paraphrase-multilingual",
        "granite-embedding",
        "jina-embeddings-v2-base-en",
    ]

    def __init__(self):
        self.session_manager = None

    async def get_openai_models(self, api_key: str) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from OpenAI API"""
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient() as client:
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
                    if any(prefix in model_id for prefix in ["gpt-4", "gpt-3.5"]):
                        language_models.append(
                            {
                                "value": model_id,
                                "label": model_id,
                                "default": model_id == "gpt-4o-mini",
                            }
                        )

                    # Embedding models
                    elif "text-embedding" in model_id:
                        embedding_models.append(
                            {
                                "value": model_id,
                                "label": model_id,
                                "default": model_id == "text-embedding-3-small",
                            }
                        )

                # Sort by name and ensure defaults are first
                language_models.sort(
                    key=lambda x: (not x.get("default", False), x["value"])
                )
                embedding_models.sort(
                    key=lambda x: (not x.get("default", False), x["value"])
                )

                return {
                    "language_models": language_models,
                    "embedding_models": embedding_models,
                }
            else:
                logger.error(f"Failed to fetch OpenAI models: {response.status_code}")
                raise Exception(
                    f"OpenAI API returned status code {response.status_code}"
                )

        except Exception as e:
            logger.error(f"Error fetching OpenAI models: {str(e)}")
            raise

    async def get_ollama_models(
        self, endpoint: str = None
    ) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from Ollama API with tool calling capabilities for language models"""
        try:
            # Use provided endpoint or default
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

                        # Check if model has required capabilities
                        has_completion = DESIRED_CAPABILITY in capabilities
                        has_tools = TOOL_CALLING_CAPABILITY in capabilities

                        # Check if it's an embedding model
                        is_embedding = any(
                            embed_model in model_name.lower()
                            for embed_model in self.OLLAMA_EMBEDDING_MODELS
                        )

                        if is_embedding:
                            # Embedding models only need completion capability
                            embedding_models.append(
                                {
                                    "value": model_name,
                                    "label": model_name,
                                    "default": False,
                                }
                            )
                        elif not is_embedding and has_completion and has_tools:
                            # Language models need both completion and tool calling
                            language_models.append(
                                {
                                    "value": model_name,
                                    "label": model_name,
                                    "default": "llama3" in model_name.lower(),
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

                return {
                    "language_models": language_models,
                    "embedding_models": embedding_models,
                }

        except Exception as e:
            logger.error(f"Error fetching Ollama models: {str(e)}")
            raise

    async def get_ibm_models(
        self, endpoint: str = None, api_key: str = None, project_id: str = None
    ) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from IBM Watson API"""
        try:
            # Use provided endpoint or default
            watson_endpoint = endpoint

            # Prepare headers for authentication
            headers = {
                "Content-Type": "application/json",
            }
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
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

            if not language_models and not embedding_models:
                raise Exception("No IBM models retrieved from API")

            return {
                "language_models": language_models,
                "embedding_models": embedding_models,
            }

        except Exception as e:
            logger.error(f"Error fetching IBM models: {str(e)}")
            raise
