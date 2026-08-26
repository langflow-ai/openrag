"""Which model providers this deployment offers, per run mode.

``model_providers.yaml`` (next to this module) lists every provider OpenRAG can
show and, for each one, whether it is visible in ``oss``, ``on_prem`` and
``saas``. The backend filters that list by ``OPENRAG_RUN_MODE`` and serves the
result; Settings cards, the Onboarding tabs and the model catalogue all read
that one list, so per-deployment policy is a config row rather than a denylist
scattered across the frontend.

Two rules keep the file safe to extend:

- a mode key that is missing (or not a boolean-ish value) means *hidden*, so a
  new run mode cannot silently expose a provider;
- a provider absent from the file is not offered anywhere, though a model id
  for it can still be typed by hand if the gateway already routes it.

A row may also declare `models` / `embedding_models`. LiteLLM's bundled table
covers the public vendors, but a self-hosted OpenAI-compatible gateway serves
whatever its operator deployed, so those ids can only come from here. Declared
ids are added to whatever the table already knows for that provider.

``OPENRAG_MODEL_PROVIDERS_CONFIG`` points at an alternate YAML file for a single
deployment. If that file is missing or unreadable the shipped default is used;
if the shipped default is unreadable too, ``_FALLBACK_PROVIDERS`` below keeps
the process serving the pre-config behavior instead of hiding every provider.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from utils.logging_config import get_logger
from utils.run_mode_utils import RUN_MODE_ON_PREM, RUN_MODE_OSS, RUN_MODE_SAAS, get_run_mode

logger = get_logger(__name__)

CONFIG_PATH_ENV = "OPENRAG_MODEL_PROVIDERS_CONFIG"
DEFAULT_CONFIG_PATH = Path(__file__).with_name("model_providers.yaml")

KNOWN_RUN_MODES: tuple[str, ...] = (RUN_MODE_OSS, RUN_MODE_ON_PREM, RUN_MODE_SAAS)

# Last-resort table, used only when no YAML file can be read at all. It matches
# the visibility OpenRAG shipped before this config existed.
_FALLBACK_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "name": "openai",
        "display_name": "OpenAI",
        "modes": {RUN_MODE_OSS: True, RUN_MODE_ON_PREM: True, RUN_MODE_SAAS: True},
        "models": (),
        "embedding_models": (),
    },
    {
        "name": "ollama",
        "display_name": "Ollama",
        "modes": {RUN_MODE_OSS: True, RUN_MODE_ON_PREM: True, RUN_MODE_SAAS: False},
        "models": (),
        "embedding_models": (),
    },
    {
        "name": "watsonx",
        "display_name": "IBM watsonx.ai",
        "modes": {RUN_MODE_OSS: True, RUN_MODE_ON_PREM: True, RUN_MODE_SAAS: True},
        "models": (),
        "embedding_models": (),
    },
    {
        "name": "anthropic",
        "display_name": "Anthropic",
        "modes": {RUN_MODE_OSS: True, RUN_MODE_ON_PREM: True, RUN_MODE_SAAS: True},
        "models": (),
        "embedding_models": (),
    },
)

_TRUTHY = {"true", "1", "yes", "on"}


def _as_bool(value: Any) -> bool:
    """Whether a YAML `modes` value means "visible".

    Anything that is not a boolean or a recognised truthy string is False, so a
    typo hides a provider rather than exposing it.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return False


def _model_ids(value: Any) -> tuple[str, ...]:
    """A YAML `models:` list as clean, de-duplicated, order-preserving ids."""
    if not isinstance(value, list):
        return ()
    ids = []
    for item in value:
        name = str(item).strip()
        if name and name not in ids:
            ids.append(name)
    return tuple(ids)


def _normalize(entry: Any, seen: set[str]) -> dict[str, Any] | None:
    """One YAML provider row as a validated dict, or None if unusable."""
    if not isinstance(entry, dict):
        logger.warning("Ignoring a model provider entry that is not a mapping")
        return None
    name = str(entry.get("name") or "").strip().lower()
    if not name:
        logger.warning("Ignoring a model provider entry with no name")
        return None
    if name in seen:
        logger.warning("Ignoring a duplicate model provider entry", provider=name)
        return None
    seen.add(name)
    raw_modes = entry.get("modes")
    if not isinstance(raw_modes, dict):
        raw_modes = {}
    display_name = str(entry.get("display_name") or "").strip() or name
    return {
        "name": name,
        "display_name": display_name,
        # Missing keys stay missing here; `is_visible` reads them as False.
        "modes": {str(mode).strip().lower(): _as_bool(value) for mode, value in raw_modes.items()},
        # Optional: ids the catalogue cannot learn from LiteLLM's static table.
        "models": _model_ids(entry.get("models")),
        "embedding_models": _model_ids(entry.get("embedding_models")),
    }


def _parse(raw: Any, source: str) -> tuple[dict[str, Any], ...]:
    if isinstance(raw, dict):
        entries = raw.get("providers")
    else:
        entries = raw
    if not isinstance(entries, list):
        logger.error("Model providers config has no `providers` list", source=source)
        return ()
    seen: set[str] = set()
    parsed = [_normalize(entry, seen) for entry in entries]
    return tuple(entry for entry in parsed if entry is not None)


def _read(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Model providers config not found", path=str(path))
        return ()
    except (OSError, yaml.YAMLError) as exc:
        logger.error(
            "Model providers config could not be read",
            path=str(path),
            error=str(exc),
        )
        return ()
    return _parse(raw, str(path))


@lru_cache(maxsize=1)
def _configured(override: str, default_path: str) -> tuple[dict[str, Any], ...]:
    """Every provider in the config file, in file order, mode filtering aside.

    Cached on the resolved paths so the YAML is read once per process. Call
    `reload()` after changing the file or the override env var.
    """
    if override:
        providers = _read(Path(override))
        if providers:
            return providers
        logger.error(
            "Falling back to the shipped model providers config",
            override=override,
            env=CONFIG_PATH_ENV,
        )
    providers = _read(Path(default_path))
    if providers:
        return providers
    logger.error(
        "No usable model providers config; using built-in defaults",
        path=default_path,
    )
    return _FALLBACK_PROVIDERS


def configured_providers() -> tuple[dict[str, Any], ...]:
    """Every provider the config file lists, regardless of run mode."""
    return _configured((os.getenv(CONFIG_PATH_ENV) or "").strip(), str(DEFAULT_CONFIG_PATH))


def reload() -> None:
    """Drop the cached file so the next read re-parses it."""
    _configured.cache_clear()


def is_visible(provider: dict[str, Any], run_mode: str) -> bool:
    """Whether a parsed provider entry is shown in `run_mode`."""
    return bool(provider["modes"].get(run_mode, False))


def visible_providers(run_mode: str | None = None) -> tuple[dict[str, Any], ...]:
    """The providers shown in `run_mode` (the current one by default)."""
    mode = (run_mode or get_run_mode()).strip().lower()
    return tuple(entry for entry in configured_providers() if is_visible(entry, mode))


def visible_provider_entries(
    run_mode: str | None = None,
) -> tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...]:
    """`(name, display_name, models, embedding_models)` for the visible providers.

    Hashable all the way down, so callers can key a cache on it.
    """
    return tuple(
        (entry["name"], entry["display_name"], entry["models"], entry["embedding_models"])
        for entry in visible_providers(run_mode)
    )


def visible_provider_keys(run_mode: str | None = None) -> frozenset[str]:
    return frozenset(entry["name"] for entry in visible_providers(run_mode))


def is_provider_visible(provider: str, run_mode: str | None = None) -> bool:
    return (provider or "").strip().lower() in visible_provider_keys(run_mode)


def provider_visibility_payload(run_mode: str | None = None) -> dict[str, Any]:
    """The API body: the current run mode and the providers it exposes."""
    mode = (run_mode or get_run_mode()).strip().lower()
    return {
        "run_mode": mode,
        "providers": [
            {"name": entry["name"], "display_name": entry["display_name"]}
            for entry in visible_providers(mode)
        ],
    }
