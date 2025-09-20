import httpx
from typing import Dict, List
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ModelsService:
    """Service for fetching available models from different AI providers"""

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
        """Fetch available models from Ollama API"""
        try:
            # Use provided endpoint or default
            ollama_url = endpoint

            async with httpx.AsyncClient() as client:
                response = await client.get(f"{ollama_url}/api/tags", timeout=10.0)

            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])

                # Extract model names
                language_models = []
                embedding_models = []

                for model in models:
                    model_name = model.get("name", "").split(":")[
                        0
                    ]  # Remove tag if present

                    if model_name:
                        # Most Ollama models can be used as language models
                        language_models.append(
                            {
                                "value": model_name,
                                "label": model_name,
                                "default": "llama3" in model_name.lower(),
                            }
                        )

                        # Some models are specifically for embeddings
                        if any(
                            embed in model_name.lower()
                            for embed in ["embed", "sentence", "all-minilm"]
                        ):
                            embedding_models.append(
                                {
                                    "value": model_name,
                                    "label": model_name,
                                    "default": False,
                                }
                            )

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

                return {
                    "language_models": language_models,
                    "embedding_models": embedding_models if embedding_models else [],
                }
            else:
                logger.error(f"Failed to fetch Ollama models: {response.status_code}")
                raise Exception(
                    f"Ollama API returned status code {response.status_code}"
                )

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
