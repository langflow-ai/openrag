"""OpenAI-compatible chat model that talks to the OpenRAG LLM proxy.

Langflow never holds upstream vendor keys. At runtime OpenRAG injects:

- ``OPENRAG_LLM_TOKEN`` — short-lived hop token (Authorization Bearer)
- ``OPENRAG_LLM_BASE_URL`` — the backend's ``/v1`` base or the router's
  private unversioned base
- ``SELECTED_LANGUAGE_MODEL`` — configured chat model id

``ChatOpenAI`` posts to ``{base_url}/chat/completions``. The backend gateway
then calls the real vendor (OpenAI, Anthropic, Watsonx, Ollama, or any other
LiteLLM provider). Embeddings use the same base URL and hop token; see
``openai_compatible_embedding.py``.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI
from lfx.base.models.model import LCModelComponent
from lfx.field_typing.constants import LanguageModel
from lfx.field_typing.range_spec import RangeSpec
from lfx.inputs.inputs import BoolInput, StrInput
from lfx.io import IntInput, MessageInput, MultilineInput, SecretStrInput, SliderInput

# Names must match src/api/settings/langflow_sync.py + src/utils/langflow_headers.py
OPENRAG_LLM_BASE_URL_VAR = "OPENRAG_LLM_BASE_URL"
OPENRAG_LLM_TOKEN_VAR = "OPENRAG_LLM_TOKEN"
SELECTED_LANGUAGE_MODEL_VAR = "SELECTED_LANGUAGE_MODEL"


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    text = str(value).strip()
    return text or None


class OpenAICompatibleLLMComponent(LCModelComponent):
    display_name = "OpenRAG LLM"
    description = (
        "Chat model via OpenRAG's OpenAI-compatible proxy. "
        "Base URL and hop token come from global variables at runtime."
    )
    icon = "OpenRAG"
    name = "OpenAICompatibleLLM"

    inputs = [
        MessageInput(
            name="input_value",
            display_name="Input",
            info="The input text to send to the model",
        ),
        MultilineInput(
            name="system_message",
            display_name="System Message",
            info="A system message that helps set the behavior of the assistant",
            advanced=False,
        ),
        BoolInput(
            name="stream",
            display_name="Stream",
            info="Whether to stream the response",
            value=False,
            advanced=True,
        ),
        StrInput(
            name="model_name",
            display_name="Model Name",
            info="Chat model id. Bound to SELECTED_LANGUAGE_MODEL at runtime.",
            value=SELECTED_LANGUAGE_MODEL_VAR,
            load_from_db=True,
        ),
        SecretStrInput(
            name="api_key",
            display_name="OpenRAG LLM Token",
            info="Hop token from OPENRAG_LLM_TOKEN. OpenRAG injects this per Langflow run.",
            value=OPENRAG_LLM_TOKEN_VAR,
            required=False,
            load_from_db=True,
        ),
        StrInput(
            name="api_base",
            display_name="OpenAI API Base",
            info=(
                "Bound to OPENRAG_LLM_BASE_URL at runtime. It is either the public "
                "/v1 base or the private router base. Same URL as embeddings."
            ),
            value=OPENRAG_LLM_BASE_URL_VAR,
            load_from_db=True,
        ),
        SliderInput(
            name="temperature",
            display_name="Temperature",
            value=0.1,
            info="Controls randomness in responses",
            range_spec=RangeSpec(min=0, max=1, step=0.01),
            advanced=True,
        ),
        IntInput(
            name="max_tokens",
            display_name="Max Tokens",
            info="Maximum number of tokens to generate. Leave empty for the model default.",
            advanced=True,
        ),
        IntInput(
            name="seed",
            display_name="Seed",
            info="The seed controls the reproducibility of the job.",
            advanced=True,
            value=1,
        ),
    ]

    def build_model(self) -> LanguageModel:
        api_key = _as_str(self.api_key)
        api_base = _as_str(self.api_base)
        if api_base:
            api_base = api_base.rstrip("/")

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "api_key": api_key,
            "base_url": api_base or None,
            "streaming": bool(getattr(self, "stream", False)),
        }
        max_tokens = getattr(self, "max_tokens", None)
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        temperature = getattr(self, "temperature", None)
        if temperature is not None:
            kwargs["temperature"] = temperature
        seed = getattr(self, "seed", None)
        if seed is not None:
            kwargs["seed"] = seed
        return ChatOpenAI(**kwargs)
