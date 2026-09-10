"""Live Azure smoke test for the onboarding / Settings validation path.

Azure reaches the network through two independent routes, and they do not share
their routing code:

    onboarding, Settings, health probe
        -> api.provider_validation.validate_provider_setup
        -> _test_litellm_provider           builds f"{provider}/{model}" inline

    chat, ingest, search
        -> services.llm_gateway.chat_completions / embeddings
        -> resolve_call                     handles provider:, space:, aliases

`azure` is not in validate_provider_setup's `{openai, watsonx, ollama,
anthropic}` set, so it takes the generic branch and calls LiteLLM directly --
with its own model string, without `drop_params`, and with different error
shaping. That divergence is how "validation passed during onboarding, then chat
404s" happens. `test_azure_live_smoke.py` covers the gateway; this module covers
the other route, and one test here checks that the two agree.

Note: `test_completion=True` has no effect for Azure. The generic branch is
checked before the `test_completion` branch, so onboarding always makes a real
provider call. These tests document that; changing it is todo-azure.md's
"generic provider validation consumes real calls" item, not this suite's job.
"""

import pytest

from api.provider_validation import sanitize_provider_error_content, validate_provider_setup
from services.llm_gateway import embeddings

from .conftest import LiveProvider, assert_actionable_error

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.openrag_skip_app_onboard,
    pytest.mark.live_provider,
]

_EMBEDDING_INPUT = ["OpenRAG live provider smoke test"]


async def _validate(target: LiveProvider, *, llm_model=None, embedding_model=None) -> None:
    """Reproduce the call `api/settings/endpoints.py` makes after onboarding.

    Argument construction is copied from the call site rather than simplified:
    `api_key` / `endpoint` / `project_id` are read off the provider config with
    `getattr`, which returns None for a `GenericProviderConfig`, so `credentials`
    is the only channel carrying Azure's `api_base`. A test that passed the key
    directly would not be exercising what onboarding does.
    """
    config = target.config
    provider = (
        config.agent.llm_provider.lower()
        if llm_model
        else config.knowledge.embedding_provider.lower()
    )
    provider_config = (
        config.get_llm_provider_config() if llm_model else config.get_embedding_provider_config()
    )

    await validate_provider_setup(
        provider=provider,
        api_key=getattr(provider_config, "api_key", None),
        llm_model=llm_model,
        embedding_model=embedding_model,
        endpoint=getattr(provider_config, "endpoint", None),
        project_id=getattr(provider_config, "project_id", None),
        test_completion=True,
        credentials=config.providers.credential_values(provider),
    )


async def test_validate_provider_setup_accepts_chat_deployment(azure_target: LiveProvider):
    """What onboarding runs when a user finishes the Azure LLM tab."""
    await _validate(azure_target, llm_model=azure_target.require_chat_model())


async def test_validate_provider_setup_accepts_embedding_deployment(azure_target: LiveProvider):
    """What onboarding runs when a user finishes the Azure embedding tab."""
    await _validate(azure_target, embedding_model=azure_target.require_embedding_model())


async def test_onboarding_and_runtime_agree_on_the_same_deployment(azure_target: LiveProvider):
    """One credential set must satisfy both routes, not either one alone.

    Each route builds its own Azure model string. If they ever disagree about
    what `azure/<deployment>` means, every other test in this directory still
    passes -- they only ever exercise one route each. This is the one that
    fails.
    """
    model = azure_target.require_embedding_model()

    await _validate(azure_target, embedding_model=model)

    payload = await embeddings(
        {"model": f"{azure_target.provider}:{model}", "input": _EMBEDDING_INPUT},
        config=azure_target.config,
    )
    data = payload.get("data") or []
    assert data and data[0]["embedding"], (
        f"validation accepted {model!r} but the gateway got no vector for it: {payload}"
    )


async def test_validation_failure_message_is_actionable(azure_target: LiveProvider):
    """A bad base URL must fail onboarding with something a user can act on.

    Consumes no credits. Asserts on `sanitize_provider_error_content(exc)` --
    the endpoint returns exactly that in its 400 body, so this is the text the
    user actually sees, not the raw exception.
    """
    model = azure_target.require_chat_model()
    broken = azure_target.with_credentials(
        api_base=azure_target.credentials["api_base"].rstrip("/") + "/openai/v1"
    )

    with pytest.raises(Exception) as excinfo:  # noqa: B017 - provider decides the type
        await _validate(broken, llm_model=model)

    assert_actionable_error(
        sanitize_provider_error_content(excinfo.value),
        broken.credentials["api_key"],
        # The gateway rewrites source paths out of its messages; this path's
        # sanitiser strips JSON bodies but makes no such promise.
        require_no_source_paths=False,
    )
