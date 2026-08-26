"""LiteLLM model/provider catalogue for the settings picker and /v1/models.

Two things come out of LiteLLM's own bundled data, so the list never has to be
hand-maintained the way the four-provider live fetches used to be:

- **models** from `litellm.model_cost` — models for OpenRAG's supported
  providers, tagged with the provider they belong to. Chat/completion/responses
  modes feed the agent picker; embedding mode feeds the ingest picker.
- **credential fields** from `litellm/proxy/public_endpoints/provider_create_fields.json`
  — the per-provider form spec. Unknown providers fall back to an API key and
  a base URL.

Both are read lazily and cached: `model_cost` is a few thousand entries and the
JSON is ~100KB, so paying for it once per process beats a re-read per request.

`function_calling` and `vision` are published as capability flags so the UI can
filter (agent vs VLM) without a second live provider call.

The public catalogue is limited to the providers this run mode exposes, per
``config/model_providers.yaml`` (see ``config.model_providers``). Generic
credential helpers remain available for every other provider, and a model that
is not in the catalogue can still be typed by hand.
"""

from __future__ import annotations

import datetime
import json
from functools import lru_cache
from typing import Any

from config.model_providers import visible_provider_entries
from utils.logging_config import get_logger

logger = get_logger(__name__)

TEXT_GENERATION_MODES = frozenset({"chat", "completion", "responses"})
EMBEDDING_MODE = "embedding"

CAPABILITY_FLAGS: dict[str, str] = {
    "supports_function_calling": "function_calling",
    "supports_vision": "vision",
    "supports_reasoning": "reasoning",
    "supports_response_schema": "structured_output",
    "supports_prompt_caching": "prompt_caching",
    "supports_pdf_input": "pdf_input",
    "supports_web_search": "web_search",
    "supports_audio_input": "audio_input",
    "supports_computer_use": "computer_use",
    "supports_parallel_function_calling": "parallel_tools",
}

NUMERIC_FIELDS = (
    "max_input_tokens",
    "max_output_tokens",
    "input_cost_per_token",
    "output_cost_per_token",
    "cache_read_input_token_cost",
)

GENERIC_CREDENTIAL_FIELDS: list[dict[str, Any]] = [
    {
        "key": "api_key",
        "label": "API key",
        "placeholder": None,
        "tooltip": None,
        "required": False,
        "field_type": "password",
        "options": None,
        "default_value": None,
    },
    {
        "key": "api_base",
        "label": "API base",
        "placeholder": "https://...",
        "tooltip": "Only needed for a self-hosted or proxied endpoint.",
        "required": False,
        "field_type": "text",
        "options": None,
        "default_value": None,
    },
]

KNOWN_FIELD_TYPES = frozenset({"text", "password", "select", "textarea", "upload"})


class CatalogUnavailableError(RuntimeError):
    """LiteLLM is not importable, so no catalogue can be built.

    Its text names server-side deployment detail, so routes log it and return
    ``CATALOG_UNAVAILABLE_MESSAGE`` to callers instead.
    """


# Client-facing stand-in for CatalogUnavailableError text.
CATALOG_UNAVAILABLE_MESSAGE = "The model catalogue is temporarily unavailable."


def _parse_deprecation(value: Any) -> datetime.date | None:
    """LiteLLM's `deprecation_date`, when it is a real YYYY-MM-DD."""
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _provider_field_specs() -> dict[str, dict[str, Any]]:
    """provider key -> the raw entry from LiteLLM's provider_create_fields.json.

    First entry wins on a duplicate `litellm_provider`. The file lists
    `openai` twice — once as "OpenAI" and once as "OpenAI-Compatible
    Endpoints", the latter marking api_base *required*. Keeping the last would
    make plain OpenAI demand a base URL nobody needs to set.
    """
    from importlib.resources import files

    path = (
        files("litellm")
        .joinpath("proxy")
        .joinpath("public_endpoints")
        .joinpath("provider_create_fields.json")
    )
    entries = json.loads(path.read_text(encoding="utf-8"))

    specs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry.get("litellm_provider")
        if not key or key in specs:
            continue
        specs[key] = entry
    return specs


def _normalize_field(field: dict[str, Any]) -> dict[str, Any]:
    field_type = str(field.get("field_type") or "text")
    return {
        "key": str(field.get("key") or ""),
        "label": str(field.get("label") or field.get("key") or ""),
        "placeholder": field.get("placeholder"),
        "tooltip": field.get("tooltip"),
        "required": bool(field.get("required")),
        "field_type": field_type if field_type in KNOWN_FIELD_TYPES else "text",
        "options": field.get("options"),
        "default_value": field.get("default_value"),
    }


def credential_fields(provider: str) -> list[dict[str, Any]]:
    """The form spec for `provider`, normalized, never empty."""
    try:
        spec = _provider_field_specs().get((provider or "").strip().lower())
    except Exception:
        logger.warning("Could not read LiteLLM's provider field specs", exc_info=True)
        return [dict(field) for field in GENERIC_CREDENTIAL_FIELDS]
    if not spec:
        return [dict(field) for field in GENERIC_CREDENTIAL_FIELDS]
    fields = [_normalize_field(field) for field in spec.get("credential_fields") or []]
    fields = [field for field in fields if field["key"]]
    return fields or [dict(field) for field in GENERIC_CREDENTIAL_FIELDS]


def secret_field_keys(provider: str) -> set[str]:
    return {
        field["key"]
        for field in credential_fields(provider)
        if field["field_type"] in {"password", "textarea", "upload"}
    }


def required_field_keys(provider: str) -> list[str]:
    return [field["key"] for field in credential_fields(provider) if field["required"]]


def missing_required_fields(provider: str, supplied: set[str]) -> list[str]:
    return [key for key in required_field_keys(provider) if key not in supplied]


def _model_entry(name: str, info: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"model": name, "mode": info.get("mode")}
    for field in NUMERIC_FIELDS:
        value = info.get(field)
        if value is not None:
            entry[field] = value
    capabilities = [public for flag, public in CAPABILITY_FLAGS.items() if info.get(flag)]
    if capabilities:
        entry["capabilities"] = capabilities
    deprecation = _parse_deprecation(info.get("deprecation_date"))
    if deprecation is not None:
        entry["deprecation_date"] = deprecation.isoformat()
    return entry


@lru_cache(maxsize=8)
def _catalog(providers: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    """Payload for `providers`, given as `(key, display_name)` pairs.

    The pairs are the cache key, so flipping a provider's visibility (or the
    run mode, in a test) rebuilds instead of serving a stale list.
    """
    try:
        import litellm
    except Exception as exc:
        raise CatalogUnavailableError("litellm is not installed on the server") from exc

    specs = _provider_field_specs()
    keys = {key for key, _ in providers}
    chat_by_provider: dict[str, list[dict[str, Any]]] = {}
    embed_by_provider: dict[str, list[dict[str, Any]]] = {}

    for model_id, info in litellm.model_cost.items():
        if not isinstance(info, dict):
            continue
        provider = info.get("litellm_provider")
        mode = info.get("mode")
        if provider not in keys:
            continue
        if mode in TEXT_GENERATION_MODES:
            bucket = chat_by_provider
        elif mode == EMBEDDING_MODE:
            bucket = embed_by_provider
        else:
            continue
        name = model_id[len(provider) + 1 :] if model_id.startswith(f"{provider}/") else model_id
        if not name or name == "sample_spec":
            continue
        bucket.setdefault(provider, []).append(_model_entry(name, info))

    entries = []
    for key, display_name in providers:
        entries.append(
            {
                "key": key,
                # The config file names the provider; LiteLLM's own label is
                # the fallback for a row that left `display_name` out.
                "name": display_name or (specs.get(key) or {}).get("provider_display_name") or key,
                "credential_fields": credential_fields(key),
                "model_placeholder": (specs.get(key) or {}).get("default_model_placeholder"),
                "models": sorted(chat_by_provider.get(key, []), key=lambda entry: entry["model"]),
                "embedding_models": sorted(
                    embed_by_provider.get(key, []), key=lambda entry: entry["model"]
                ),
            }
        )
    return {"providers": entries}


@lru_cache(maxsize=8)
def _catalog_for(today: datetime.date, providers: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    """`_catalog()` with models the provider has already retired removed."""

    def _keep(model: dict[str, Any]) -> bool:
        retires = _parse_deprecation(model.get("deprecation_date"))
        return retires is None or retires > today

    entries = []
    for provider in _catalog(providers)["providers"]:
        entries.append(
            {
                **provider,
                "models": [model for model in provider["models"] if _keep(model)],
                "embedding_models": [
                    model for model in provider["embedding_models"] if _keep(model)
                ],
            }
        )
    return {"providers": entries}


def supported_provider_keys() -> frozenset[str]:
    """The providers this run mode publishes, per `config/model_providers.yaml`."""
    return frozenset(key for key, _ in visible_provider_entries())


def catalog(today: datetime.date | None = None) -> dict[str, Any]:
    """Picker payload for the providers this run mode exposes, and their models."""
    return _catalog_for(today or datetime.date.today(), visible_provider_entries())


def is_known_provider(provider: str) -> bool:
    """Whether LiteLLM recognises `provider` at all."""
    key = (provider or "").strip().lower()
    if not key:
        return False
    try:
        import litellm

        # `provider_list` holds LlmProviders enum members, and str() on one
        # yields "LlmProviders.OPENAI" — never the routable "openai". Reading
        # .value is what makes this branch match; without it the check fell
        # through to the credential-form specs below, which do not cover every
        # provider LiteLLM can route (zai, scaleway, chatgpt, ...). Those
        # prefixes were then left unsplit and called with the default
        # provider's credentials.
        if key in {getattr(value, "value", str(value)) for value in litellm.provider_list}:
            return True
    except Exception:
        logger.debug("Could not read litellm.provider_list", exc_info=True)
    try:
        return key in _provider_field_specs()
    except Exception:
        return False


def public_model_id(provider: str, model: str) -> str:
    """The routable id for `model` as served by `/v1/models`.

    `_catalog()` strips the provider prefix so the picker can show bare names,
    but an unprefixed id sent back to `/v1/chat/completions` is resolved against
    the *default* provider — an Anthropic model would then be called with the
    OpenAI credentials. Re-attach the prefix for every non-OpenAI provider so
    the id round-trips through `resolve_call()`. OpenAI keeps bare names because
    that is what OpenAI-compatible clients expect.
    """
    return model if provider == "openai" else f"{provider}/{model}"


def openai_models_list(today: datetime.date | None = None) -> dict[str, Any]:
    """OpenAI-compatible `GET /v1/models` body from the catalogue."""
    data = []
    for provider in catalog(today)["providers"]:
        owner = provider["key"]
        for entry in (*provider["models"], *provider["embedding_models"]):
            data.append(
                {
                    "id": public_model_id(owner, entry["model"]),
                    "object": "model",
                    "owned_by": owner,
                    "created": 0,
                }
            )
    return {"object": "list", "data": data}
