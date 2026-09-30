"""LiteLLM's routing contract for Azure AI Foundry, pinned.

OpenRAG's Foundry support rests on three facts about how LiteLLM turns an
operator's `api_base` into a request. None of them is part of LiteLLM's public
API, and all three have changed inside a minor release before:

1. The native `azure_ai` chat route rewrites the path, inserting `/models/`
   whenever the host looks like a Foundry resource. That is correct for the
   legacy inference route and wrong for the OpenAI-compatible `/openai/v1`
   surface Microsoft recommends for new integrations — which is why the v1 form
   cannot be served by `azure_ai` at all.
2. The OpenAI-compatible route (`openai_like`) appends nothing but
   `/chat/completions`, so it serves *both* Foundry endpoint forms correctly.
   That is what makes it the route target for the v1 form.
3. `azure_ai/<model>` stays on the Foundry provider. On litellm 1.84.0 it did
   not: OpenAI-family deployment names were silently rerouted to the Azure
   OpenAI provider, which then called a Foundry hostname with the wrong
   handler. That regression is fixed in the pinned floor and must stay fixed.

`pyproject.toml` allows a range (`litellm>=1.96.2,<2.0.0`) rather than a pin, so
a lock refresh can move any of this without a line of OpenRAG changing. These
assertions exist to make that refresh fail loudly instead of silently changing
the URL we send to a customer's Azure resource.

**A failure here is a signal, not a bug in this file.** It means LiteLLM's
behaviour moved and the Foundry routing decision has to be re-made against the
new version — not that an assertion should be relaxed to make CI green. Re-run
the matrices below by hand against the new version, decide whether the routing
still holds, and only then update these expectations. An ImportError at
collection means the internals were renamed, which needs the same review.
"""

from importlib.metadata import version

import pytest
from litellm import get_llm_provider
from litellm.llms.azure_ai.chat.transformation import AzureAIStudioConfig
from litellm.llms.azure_ai.embed.handler import AzureAIEmbedding
from litellm.llms.openai.openai import OpenAIChatCompletion
from litellm.llms.openai_like.chat.transformation import OpenAILikeChatConfig

#: Named in assertion messages so a failure says which version it was measured
#: against without the reader digging through the lockfile.
LITELLM_VERSION = version("litellm")

#: The resource root Azure hands an operator, and the two inference surfaces
#: hanging off it. `legacy_models` is the older `/models` inference route;
#: `resource_openai_v1` and `project_openai_v1` are the OpenAI-compatible
#: surface Microsoft recommends for new integrations.
RESOURCE_ROOT = "https://contoso.services.ai.azure.com"
LEGACY_MODELS = f"{RESOURCE_ROOT}/models"
RESOURCE_OPENAI_V1 = f"{RESOURCE_ROOT}/openai/v1"
PROJECT_OPENAI_V1 = f"{RESOURCE_ROOT}/api/projects/proj-1/openai/v1"

#: An Azure OpenAI Service resource. A Foundry resource can host Azure OpenAI
#: deployments, so the hostname does not decide the provider key — but it does
#: decide LiteLLM's path rewriting, which is the point of the first test.
AZURE_OPENAI_V1 = "https://contoso.openai.azure.com/openai/v1"


def _chat_url(config, api_base: str, model: str = "my-deployment") -> str:
    return config.get_complete_url(
        api_base=api_base,
        api_key="test-key",
        model=model,
        optional_params={},
        litellm_params={},
        stream=False,
    )


def _headers(config, api_base: str) -> dict:
    return config.validate_environment(
        headers={},
        model="my-deployment",
        messages=[],
        optional_params={},
        litellm_params={},
        api_key="test-key",
        api_base=api_base,
    )


@pytest.mark.parametrize(
    "api_base, expected",
    [
        (RESOURCE_ROOT, f"{RESOURCE_ROOT}/models/chat/completions"),
        (LEGACY_MODELS, f"{RESOURCE_ROOT}/models/chat/completions"),
        # Not a dedupe: `/openai/v1` does not overlap `models/chat/completions`,
        # so the rewrite lands *after* the operator's path.
        (RESOURCE_OPENAI_V1, f"{RESOURCE_OPENAI_V1}/models/chat/completions"),
        (PROJECT_OPENAI_V1, f"{PROJECT_OPENAI_V1}/models/chat/completions"),
        # An Azure OpenAI host is exempt from the rewrite.
        (AZURE_OPENAI_V1, f"{AZURE_OPENAI_V1}/chat/completions"),
    ],
)
def test_the_native_foundry_route_rewrites_the_path_by_hostname(api_base, expected) -> None:
    """`azure_ai` inserts `/models/` for any `*.services.ai.azure.com` host.

    Right for the legacy inference route, wrong for `/openai/v1` — and there is
    no `api_base` spelling that opts out, because the rewrite keys on the
    hostname rather than on the path already present.
    """
    assert _chat_url(AzureAIStudioConfig(), api_base) == expected, (
        f"litellm {LITELLM_VERSION} changed the azure_ai chat path for {api_base}"
    )


@pytest.mark.parametrize("api_base", [RESOURCE_OPENAI_V1, PROJECT_OPENAI_V1])
def test_the_openai_v1_form_is_unroutable_on_the_native_foundry_provider(api_base) -> None:
    """The v1 surface cannot be served by `azure_ai`, which is why we alias it.

    Spelled out separately from the matrix above because this single fact is
    what the whole routing design turns on: the emitted URL contains a `/models`
    segment the v1 surface does not serve, so the request 404s.
    """
    url = _chat_url(AzureAIStudioConfig(), api_base)

    assert "/models/chat/completions" in url, (
        f"litellm {LITELLM_VERSION} no longer injects /models into the v1 form. "
        "If azure_ai now serves /openai/v1 directly, the alias in the Foundry "
        "enhancement can be dropped — re-make the routing decision."
    )
    assert url != f"{api_base}/chat/completions"


@pytest.mark.parametrize(
    "api_base",
    [RESOURCE_OPENAI_V1, PROJECT_OPENAI_V1, LEGACY_MODELS],
)
def test_the_openai_compatible_route_serves_every_foundry_endpoint_form(api_base) -> None:
    """`openai_like` appends `/chat/completions` and nothing else.

    This is why it is the route target for the v1 form, and why it would also
    work — at the cost of LiteLLM's Foundry-specific model handling — for the
    legacy one.
    """
    assert _chat_url(OpenAILikeChatConfig(), api_base) == f"{api_base}/chat/completions", (
        f"litellm {LITELLM_VERSION} changed the openai_like path for {api_base}"
    )


def test_the_two_routes_disagree_about_the_auth_header() -> None:
    """Switching route also switches how the credential is framed.

    `azure_ai` sends the key as `api-key`; `openai_like` sends it as a bearer
    token. Credential translation in the Foundry enhancement has to account for
    this, so a change here is a change to what reaches the customer's resource.
    """
    native = _headers(AzureAIStudioConfig(), RESOURCE_ROOT)
    compatible = _headers(OpenAILikeChatConfig(), RESOURCE_OPENAI_V1)

    assert native.get("api-key") == "test-key"
    assert "Authorization" not in native

    assert compatible.get("Authorization") == "Bearer test-key"
    assert "api-key" not in compatible


@pytest.mark.parametrize(
    "deployment",
    [
        # OpenAI-family names: these are the ones litellm 1.84.0 rerouted to the
        # `azure` provider, and the two most likely first picks for an operator.
        "gpt-4.1-nano",
        "text-embedding-3-small",
        "gpt-4o",
        "gpt-5",
        # Names that always stayed put, kept so the test covers both sides.
        "claude-sonnet-4-5",
        "Phi-4",
        "mistral-large",
        # Operator-chosen deployment names, which is what Foundry actually sends.
        "my-deployment",
        "prod-llm-01",
    ],
)
def test_a_foundry_model_id_stays_on_the_foundry_provider(deployment) -> None:
    """`azure_ai/<name>` must not be rerouted by model name.

    Regression guard. On litellm 1.84.0 an OpenAI-family name silently resolved
    to the `azure` provider, so a Foundry hostname was called with the Azure
    OpenAI handler — which needs an `api_version` the Foundry credential form
    cannot collect. It surfaced as an opaque auth or 404 failure.
    """
    _model, provider, _key, _base = get_llm_provider(model=f"azure_ai/{deployment}")

    assert provider == "azure_ai", (
        f"litellm {LITELLM_VERSION} reroutes azure_ai/{deployment} to {provider!r}. "
        "This is the 1.84.0 regression returning; Foundry requests would be built "
        "by the wrong handler."
    )


def test_foundry_embeddings_do_no_path_rewriting_of_their_own() -> None:
    """Chat and embeddings take different handlers, so they need separate tests.

    Embeddings inherit the plain OpenAI implementation and post to
    `{api_base}/embeddings` — no `/models` insertion. That asymmetry means a
    single `api_base` behaves differently per call kind on the v1 form
    (embeddings work, chat does not), and a contract test that exercises only
    one of the two reaches the opposite conclusion of one that exercises the
    other.
    """
    assert issubclass(AzureAIEmbedding, OpenAIChatCompletion)
    assert "get_complete_url" not in vars(AzureAIEmbedding), (
        f"litellm {LITELLM_VERSION} gave the Foundry embedding handler its own URL "
        "construction; re-check the embedding path against every endpoint form."
    )
