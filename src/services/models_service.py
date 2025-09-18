import httpx
import os
from typing import Dict, List
from utils.logging_config import get_logger

logger = get_logger(__name__)


class ModelsService:
    """Service for fetching available models from different AI providers"""

    def __init__(self):
        self.session_manager = None

    async def get_openai_models(self) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from OpenAI API"""
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set, using default models")
                return self._get_default_openai_models()

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
                logger.warning(f"Failed to fetch OpenAI models: {response.status_code}")
                return self._get_default_openai_models()

        except Exception as e:
            logger.error(f"Error fetching OpenAI models: {str(e)}")
            return self._get_default_openai_models()

    async def get_ollama_models(
        self, endpoint: str = None
    ) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from Ollama API"""
        try:
            # Use provided endpoint or default
            ollama_url = endpoint or os.getenv(
                "OLLAMA_BASE_URL", "http://localhost:11434"
            )

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
                    "embedding_models": embedding_models
                    if embedding_models
                    else [
                        {
                            "value": "nomic-embed-text",
                            "label": "nomic-embed-text",
                            "default": True,
                        }
                    ],
                }
            else:
                logger.warning(f"Failed to fetch Ollama models: {response.status_code}")
                return self._get_default_ollama_models()

        except Exception as e:
            logger.error(f"Error fetching Ollama models: {str(e)}")
            return self._get_default_ollama_models()

    async def get_ibm_models(
        self, endpoint: str = None
    ) -> Dict[str, List[Dict[str, str]]]:
        """Fetch available models from IBM Watson API"""
        try:
            # Use provided endpoint or default
            watson_endpoint = endpoint or os.getenv("IBM_WATSON_ENDPOINT", "https://us-south.ml.cloud.ibm.com")

            # Fetch foundation models using the correct endpoint
            models_url = f"{watson_endpoint}/ml/v1/foundation_model_specs"

            language_models = []
            embedding_models = []

            async with httpx.AsyncClient() as client:
                # Fetch text chat models
                text_params = {
                    "version": "2024-09-16",
                    "filters": "function_text_chat,!lifecycle_withdrawn"
                }
                text_response = await client.get(models_url, params=text_params, timeout=10.0)

                if text_response.status_code == 200:
                    text_data = text_response.json()
                    text_models = text_data.get("resources", [])

                    for i, model in enumerate(text_models):
                        model_id = model.get("model_id", "")
                        model_name = model.get("name", model_id)

                        language_models.append({
                            "value": model_id,
                            "label": model_name or model_id,
                            "default": i == 0  # First model is default
                        })

                # Fetch embedding models
                embed_params = {
                    "version": "2024-09-16",
                    "filters": "function_embedding,!lifecycle_withdrawn"
                }
                embed_response = await client.get(models_url, params=embed_params, timeout=10.0)

                if embed_response.status_code == 200:
                    embed_data = embed_response.json()
                    embed_models = embed_data.get("resources", [])

                    for i, model in enumerate(embed_models):
                        model_id = model.get("model_id", "")
                        model_name = model.get("name", model_id)

                        embedding_models.append({
                            "value": model_id,
                            "label": model_name or model_id,
                            "default": i == 0  # First model is default
                        })

            return {
                "language_models": language_models if language_models else self._get_default_ibm_models()["language_models"],
                "embedding_models": embedding_models if embedding_models else self._get_default_ibm_models()["embedding_models"]
            }

        except Exception as e:
            logger.error(f"Error fetching IBM models: {str(e)}")
            return self._get_default_ibm_models()

    def _get_default_openai_models(self) -> Dict[str, List[Dict[str, str]]]:
        """Default OpenAI models when API is not available"""
        return {
            "language_models": [
                {"value": "gpt-4o-mini", "label": "gpt-4o-mini", "default": True},
                {"value": "gpt-4o", "label": "gpt-4o", "default": False},
                {"value": "gpt-4-turbo", "label": "gpt-4-turbo", "default": False},
                {"value": "gpt-3.5-turbo", "label": "gpt-3.5-turbo", "default": False},
            ],
            "embedding_models": [
                {
                    "value": "text-embedding-3-small",
                    "label": "text-embedding-3-small",
                    "default": True,
                },
                {
                    "value": "text-embedding-3-large",
                    "label": "text-embedding-3-large",
                    "default": False,
                },
                {
                    "value": "text-embedding-ada-002",
                    "label": "text-embedding-ada-002",
                    "default": False,
                },
            ],
        }

    def _get_default_ollama_models(self) -> Dict[str, List[Dict[str, str]]]:
        """Default Ollama models when API is not available"""
        return {
            "language_models": [
                {"value": "llama3.2", "label": "llama3.2", "default": True},
                {"value": "llama3.1", "label": "llama3.1", "default": False},
                {"value": "llama3", "label": "llama3", "default": False},
                {"value": "mistral", "label": "mistral", "default": False},
                {"value": "codellama", "label": "codellama", "default": False},
            ],
            "embedding_models": [
                {
                    "value": "nomic-embed-text",
                    "label": "nomic-embed-text",
                    "default": True,
                },
                {"value": "all-minilm", "label": "all-minilm", "default": False},
            ],
        }

    def _get_default_ibm_models(self) -> Dict[str, List[Dict[str, str]]]:
        """Default IBM Watson models when API is not available"""
        return {
            "language_models": [
                {
                    "value": "meta-llama/llama-3-1-70b-instruct",
                    "label": "Llama 3.1 70B Instruct",
                    "default": True,
                },
                {
                    "value": "meta-llama/llama-3-1-8b-instruct",
                    "label": "Llama 3.1 8B Instruct",
                    "default": False,
                },
                {
                    "value": "ibm/granite-13b-chat-v2",
                    "label": "Granite 13B Chat v2",
                    "default": False,
                },
                {
                    "value": "ibm/granite-13b-instruct-v2",
                    "label": "Granite 13B Instruct v2",
                    "default": False,
                },
            ],
            "embedding_models": [
                {
                    "value": "ibm/slate-125m-english-rtrvr",
                    "label": "Slate 125M English Retriever",
                    "default": True,
                },
                {
                    "value": "sentence-transformers/all-minilm-l12-v2",
                    "label": "All-MiniLM L12 v2",
                    "default": False,
                },
            ],
        }
