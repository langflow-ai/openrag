"""Gating and configuration for live provider smoke tests.

Everything in this directory calls a real model provider over the network. The
rest of the suite mocks LiteLLM, which pins how OpenRAG *builds* a request but
can never show that the result is one the provider accepts — and every Azure
bug we have hit lived exactly there: `Set 'AZURE_API_BASE' in .env` during
ingest, `resource not found` from a `/openai/v1` base URL, `azure` vs `azure_ai`
routing. These tests close that gap.

They are skipped unless BOTH:

  * ``OPENRAG_LIVE_PROVIDER_TESTS=true``, and
  * the provider's credentials are in the environment.

The explicit flag is required because ``tests/conftest.py`` calls
``load_dotenv()``: without it, any developer with Azure keys in ``.env`` would
hit the network on every ``make test``.

Variable names follow LiteLLM's ``{PROVIDER}_{FIELD}`` convention, the same one
``config.settings.provider_env_vars`` emits and ``test-ci.yml`` already uses for
``OPENAI_API_KEY`` / ``WATSONX_*``:

    AZURE_API_KEY, AZURE_API_BASE, AZURE_API_VERSION
    AZURE_CHAT_DEPLOYMENT, AZURE_EMBEDDING_DEPLOYMENT
    AZURE_AI_API_KEY, AZURE_AI_API_BASE
    AZURE_AI_CHAT_DEPLOYMENT, AZURE_AI_EMBEDDING_DEPLOYMENT
"""

import os
from dataclasses import dataclass, replace
from typing import Any

import pytest

from config.config_manager import OpenRAGConfig

LIVE_FLAG = "OPENRAG_LIVE_PROVIDER_TESTS"

#: LiteLLM provider key -> (environment prefix, chat default, embedding default).
#:
#: `azure` is Azure OpenAI Service, where the gpt-4.1 family lives; its model
#: names are the OpenAI ones often enough that defaults are useful. `azure_ai`
#: is the Foundry catalogue, whose deployment names are operator-chosen and
#: whose only embedding models are Cohere's -- so it gets no defaults and its
#: tests skip until the names are supplied.
AZURE_TARGETS: dict[str, tuple[str, str | None, str | None]] = {
    "azure": ("AZURE", "gpt-4.1", "text-embedding-3-small"),
    "azure_ai": ("AZURE_AI", None, None),
}

#: Everything LiteLLM might read as an Azure credential. The fixture removes all
#: of it from the environment; see `_scrub_provider_environment`.
_ENV_SCRUB_PREFIX = "AZURE_"


def live_tests_enabled() -> bool:
    return os.getenv(LIVE_FLAG, "").strip().lower() == "true"


@dataclass(frozen=True)
class LiveProvider:
    """One credentialed provider under test, and the config that reaches it."""

    provider: str
    env_prefix: str
    credentials: dict[str, str]
    chat_model: str | None
    embedding_model: str | None
    config: OpenRAGConfig

    def require_chat_model(self) -> str:
        if not self.chat_model:
            pytest.skip(f"{self.env_prefix}_CHAT_DEPLOYMENT is not set")
        return self.chat_model

    def require_embedding_model(self) -> str:
        if not self.embedding_model:
            pytest.skip(f"{self.env_prefix}_EMBEDDING_DEPLOYMENT is not set")
        return self.embedding_model

    def with_credentials(self, **overrides: str) -> "LiveProvider":
        """A copy whose credentials carry `overrides`, config rebuilt to match."""
        credentials = {**self.credentials, **overrides}
        return replace(
            self,
            credentials=credentials,
            config=build_config(self.provider, credentials, self.chat_model, self.embedding_model),
        )


def build_config(
    provider: str,
    credentials: dict[str, str],
    chat_model: str | None,
    embedding_model: str | None,
) -> OpenRAGConfig:
    """An OpenRAGConfig carrying `credentials` for `provider` and nothing else.

    Built through `from_dict` rather than by hand so the test exercises the same
    load path a saved `config.yaml` takes -- including alias canonicalisation
    (`azure_ai_foundry` -> `azure_ai`). `decrypt_secret` passes plaintext
    through, as `tests/unit/config/test_provider_env_export.py` also relies on.
    """
    data: dict[str, Any] = {
        "providers": {"custom": {provider: {"credentials": credentials, "configured": True}}},
        "agent": {"llm_provider": provider, "llm_model": chat_model or ""},
        "knowledge": {
            "embedding_provider": provider,
            "embedding_model": embedding_model or "",
        },
    }
    return OpenRAGConfig.from_dict(data)


def _scrub_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every AZURE_* variable from the test process.

    LiteLLM falls back to `AZURE_API_KEY` / `AZURE_API_BASE` (and friends) when
    a call does not carry them as kwargs. Leaving them set would make these
    tests pass even if OpenRAG stopped passing stored credentials through
    entirely -- which is the single most likely regression here, and the one
    class of bug this suite exists to catch. After this runs, the OpenRAGConfig
    handed to the gateway is the only credential source in the process.

    Both prefixes go regardless of which provider is under test, so the `azure`
    and `azure_ai` routes cannot borrow each other's credentials either.
    monkeypatch restores them when the test ends.
    """
    for name in [key for key in os.environ if key.startswith(_ENV_SCRUB_PREFIX)]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(params=list(AZURE_TARGETS), ids=["azure-openai", "azure-foundry"])
def azure_target(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> LiveProvider:
    """A credentialed Azure provider, or a skip naming what is missing."""
    if not live_tests_enabled():
        pytest.skip(f"live provider tests are opt-in; set {LIVE_FLAG}=true")

    provider = request.param
    prefix, chat_default, embedding_default = AZURE_TARGETS[provider]

    def env(field: str) -> str:
        return (os.getenv(f"{prefix}_{field}") or "").strip()

    credentials = {
        name: value
        for name, value in (
            ("api_key", env("API_KEY")),
            ("api_base", env("API_BASE")),
            ("api_version", env("API_VERSION")),
        )
        if value
    }
    chat_model = env("CHAT_DEPLOYMENT") or chat_default
    embedding_model = env("EMBEDDING_DEPLOYMENT") or embedding_default

    for field in ("api_key", "api_base"):
        if not credentials.get(field):
            pytest.skip(f"{prefix}_{field.upper()} is not set")

    _scrub_provider_environment(monkeypatch)

    return LiveProvider(
        provider=provider,
        env_prefix=prefix,
        credentials=credentials,
        chat_model=chat_model,
        embedding_model=embedding_model,
        config=build_config(provider, credentials, chat_model, embedding_model),
    )


def assert_actionable_error(
    message: str, secret: str, *, require_no_source_paths: bool = True
) -> None:
    """A failure a user can act on: explains itself, leaks neither key nor stack.

    Deliberately does not pin the wording. Azure base-URL normalisation and
    provider-specific validation messages are still to come (todo-azure.md
    must-do #3); this holds only the properties that must survive that work.

    `require_no_source_paths` is on for the gateway, whose
    `_sanitise_upstream_detail` rewrites source paths to `<path>`, and off for
    the onboarding path, where `sanitize_provider_error_content` strips JSON
    bodies but makes no such promise -- asserting it there would be testing a
    guarantee the code does not offer.
    """
    assert message and message.strip(), "upstream failure produced no message"
    assert "Traceback (most recent call last)" not in message
    if require_no_source_paths:
        assert ".py" not in message, f"message leaks a source path: {message}"
    if secret:
        assert secret not in message, "message leaks the API key"
