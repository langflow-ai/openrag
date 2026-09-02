"""OpenAI-compatible embeddings that talk to the OpenRAG `/v1` proxy.

Embeddings work the same way as chat: Langflow never holds upstream vendor
keys. At runtime OpenRAG injects:

- ``OPENRAG_LLM_TOKEN`` — the same short-lived hop token as chat
- ``OPENRAG_LLM_BASE_URL`` — the same ``http://<backend>/v1`` base URL
- ``SELECTED_EMBEDDING_MODEL`` — configured embedding model id

``OpenAIEmbeddings`` posts to ``{base_url}/embeddings``. The backend gateway
routes by the configured embedding provider (which can differ from the chat
provider).
"""

from __future__ import annotations

from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from lfx.base.embeddings.model import LCEmbeddingsModel
from lfx.io import IntInput, SecretStrInput, StrInput

# Names must match src/api/settings/langflow_sync.py + src/utils/langflow_headers.py
OPENRAG_LLM_BASE_URL_VAR = "OPENRAG_LLM_BASE_URL"
OPENRAG_LLM_TOKEN_VAR = "OPENRAG_LLM_TOKEN"
SELECTED_EMBEDDING_MODEL_VAR = "SELECTED_EMBEDDING_MODEL"


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    text = str(value).strip()
    return text or None


class OpenRAGEmbeddings(Embeddings):
    """One immutable model route plus a factory for other retrieval routes."""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None,
        api_base: str | None,
        chunk_size: int | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.model = model_name
        self.deployment = model_name
        self._api_key = api_key
        self._api_base = api_base
        self._chunk_size = chunk_size

        kwargs: dict[str, Any] = {
            "model": self.model,
            # Keep identity aligned with ``model``. LangChain otherwise exposes
            # its ada-002 class default as the deployment for every instance.
            "deployment": self.model_name,
            "api_key": api_key,
            "base_url": api_base,
            "check_embedding_ctx_length": False,
        }
        if chunk_size:
            kwargs["chunk_size"] = chunk_size
        if dimensions:
            kwargs["dimensions"] = dimensions
        self._delegate = OpenAIEmbeddings(**kwargs)

    @property
    def model_name(self) -> str:
        return self.model

    def for_model(self, model_name: str) -> Embeddings:
        """Return a dedicated adapter; never mutate the selected ingestion model."""
        route = (model_name or "").strip()
        if not route:
            raise ValueError("Embedding model route is required")
        return OpenRAGEmbeddings(
            model_name=route,
            api_key=self._api_key,
            api_base=self._api_base,
            chunk_size=self._chunk_size,
            # A selected-model dimension override is not valid for other models.
            dimensions=None,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._delegate.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._delegate.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._delegate.aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return await self._delegate.aembed_query(text)


class OpenAICompatibleEmbeddingComponent(LCEmbeddingsModel):
    display_name = "OpenRAG Embeddings"
    description = (
        "Embeddings via OpenRAG's OpenAI-compatible /v1 proxy. "
        "Uses the same base URL and hop token as the chat component."
    )
    icon = "OpenRAG"
    name = "OpenAICompatibleEmbedding"

    inputs = [
        StrInput(
            name="model_name",
            display_name="Model Name",
            info="Embedding model id. Bound to SELECTED_EMBEDDING_MODEL at runtime.",
            value=SELECTED_EMBEDDING_MODEL_VAR,
            load_from_db=True,
        ),
        SecretStrInput(
            name="api_key",
            display_name="OpenRAG LLM Token",
            info="Hop token from OPENRAG_LLM_TOKEN. Same token as the chat component.",
            value=OPENRAG_LLM_TOKEN_VAR,
            required=False,
            load_from_db=True,
        ),
        StrInput(
            name="api_base",
            display_name="OpenAI API Base",
            info=(
                "Must end with /v1 (for example http://openrag-backend:8000/v1). "
                "Bound to OPENRAG_LLM_BASE_URL at runtime. Same URL as chat."
            ),
            value=OPENRAG_LLM_BASE_URL_VAR,
            load_from_db=True,
        ),
        IntInput(
            name="dimensions",
            display_name="Dimensions",
            info="Output dimensions when the embedding model supports it.",
            advanced=True,
        ),
        IntInput(
            name="chunk_size",
            display_name="Chunk Size",
            advanced=True,
            value=1000,
        ),
    ]

    def build_embeddings(self) -> Embeddings:
        api_key = _as_str(self.api_key)
        api_base = _as_str(self.api_base)
        if api_base:
            api_base = api_base.rstrip("/")
        return OpenRAGEmbeddings(
            model_name=self.model_name,
            api_key=api_key,
            api_base=api_base,
            chunk_size=getattr(self, "chunk_size", None),
            dimensions=getattr(self, "dimensions", None),
        )
