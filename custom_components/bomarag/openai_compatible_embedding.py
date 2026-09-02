"""OpenAI-compatible embeddings that talk to the BomaRAG `/v1` proxy.

Embeddings work the same way as chat: Langflow never holds upstream vendor
keys. At runtime BomaRAG injects:

- ``BOMARAG_LLM_TOKEN`` — the same short-lived hop token as chat
- ``BOMARAG_LLM_BASE_URL`` — the same ``http://<backend>/v1`` base URL
- ``SELECTED_EMBEDDING_MODEL`` — configured embedding model id

``OpenAIEmbeddings`` posts to ``{base_url}/embeddings``. The backend gateway
routes by the configured embedding provider (which can differ from the chat
provider).
"""

from __future__ import annotations

from typing import Any

from langchain_openai import OpenAIEmbeddings
from lfx.base.embeddings.model import LCEmbeddingsModel
from lfx.field_typing import Embeddings
from lfx.io import IntInput, SecretStrInput, StrInput

# Names must match src/api/settings/langflow_sync.py + src/utils/langflow_headers.py
BOMARAG_LLM_BASE_URL_VAR = "BOMARAG_LLM_BASE_URL"
BOMARAG_LLM_TOKEN_VAR = "BOMARAG_LLM_TOKEN"
SELECTED_EMBEDDING_MODEL_VAR = "SELECTED_EMBEDDING_MODEL"


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    text = str(value).strip()
    return text or None


class OpenAICompatibleEmbeddingComponent(LCEmbeddingsModel):
    display_name = "BomaRAG Embeddings"
    description = (
        "Embeddings via BomaRAG's OpenAI-compatible /v1 proxy. "
        "Uses the same base URL and hop token as the chat component."
    )
    icon = "BomaRAG"
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
            display_name="BomaRAG LLM Token",
            info="Hop token from BOMARAG_LLM_TOKEN. Same token as the chat component.",
            value=BOMARAG_LLM_TOKEN_VAR,
            required=False,
            load_from_db=True,
        ),
        StrInput(
            name="api_base",
            display_name="OpenAI API Base",
            info=(
                "Must end with /v1 (for example http://bomarag-backend:8000/v1). "
                "Bound to BOMARAG_LLM_BASE_URL at runtime. Same URL as chat."
            ),
            value=BOMARAG_LLM_BASE_URL_VAR,
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

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            # `OpenAIEmbeddings.deployment` defaults to the class-level default of
            # `model` — the literal "text-embedding-ada-002" — for every instance,
            # whatever model is actually configured. The OpenSearch component keys
            # its embedding lookup on `deployment` as well as `model`, so leaving
            # the default in place registers this object under ada-002 too, and a
            # 768-dim vector then gets aimed at a 1536-dim ada-002 vector field.
            # Only Azure reads this field, so pinning it to the real model is inert
            # at request time and keeps the component's identity honest.
            "deployment": self.model_name,
            "api_key": api_key,
            "base_url": api_base or None,
            # Skip tiktoken context checks so non-OpenAI model ids still work.
            "check_embedding_ctx_length": False,
        }
        chunk_size = getattr(self, "chunk_size", None)
        if chunk_size:
            kwargs["chunk_size"] = chunk_size
        dimensions = getattr(self, "dimensions", None)
        if dimensions:
            kwargs["dimensions"] = dimensions
        return OpenAIEmbeddings(**kwargs)
