"""Azure AI Foundry: endpoint classification, transport selection, credentials.

`azure_ai` is the OpenRAG provider key throughout. `hosted_vllm` appears only
as the LiteLLM transport for the OpenAI-compatible `/openai/v1` surface, which
LiteLLM's own `azure_ai` handler cannot address — see the module docstring in
`enhancements/providers/azure/foundry.py` for the captured evidence.
"""

from __future__ import annotations

import pytest

from enhancements.providers.azure import foundry
from enhancements.providers.registry import get as get_enhancement
from enhancements.providers.registry import litellm_route_for, route_aliases

RESOURCE = "https://contoso.services.ai.azure.com"


class TestEndpointProfile:
    """The surface is classified from the path, never from the hostname.

    A Foundry resource can serve Azure OpenAI deployments too, so the host says
    nothing about which API is being addressed.
    """

    @pytest.mark.parametrize(
        "api_base, expected",
        [
            (f"{RESOURCE}/openai/v1", "resource_openai_v1"),
            (f"{RESOURCE}/openai/v1/", "resource_openai_v1"),
            (f"{RESOURCE}/api/projects/proj-1/openai/v1", "project_openai_v1"),
            (f"{RESOURCE}/api/projects/proj-1/openai/v1/", "project_openai_v1"),
            (f"{RESOURCE}/models", "legacy_models"),
            (f"{RESOURCE}/models/", "legacy_models"),
            # A bare resource root is the legacy route's own default: litellm's
            # azure_ai handler appends `/models/...` and reaches the right place.
            (RESOURCE, "legacy_models"),
            (f"{RESOURCE}/", "legacy_models"),
        ],
    )
    def test_the_supported_shapes(self, api_base, expected) -> None:
        assert foundry.endpoint_profile(api_base) == expected

    @pytest.mark.parametrize(
        "api_base",
        [
            # A deployment Target URI on a *Foundry* host never worked: the
            # native rewrite appends `/models/chat/completions` after it.
            f"{RESOURCE}/openai/deployments/gpt-4o",
            f"{RESOURCE}/openai/deployments/gpt-4o/chat/completions",
            f"{RESOURCE}/anthropic/v1",
            "not-a-url",
            "",
            None,
        ],
    )
    def test_anything_else_is_unknown_rather_than_guessed_at(self, api_base) -> None:
        assert foundry.endpoint_profile(api_base) == "unknown"

    @pytest.mark.parametrize(
        "api_base",
        [
            "https://contoso.openai.azure.com/openai/deployments/gpt-4o/chat/completions",
            "https://contoso.openai.azure.com/openai/deployments/gpt-4o",
        ],
    )
    def test_the_one_compatibility_shape_is_named_not_lumped_into_unknown(self, api_base) -> None:
        """LiteLLM's own placeholder told operators to paste this.

        On an `openai.azure.com` host it genuinely worked — the native
        rewrite collapses the `/chat/completions` overlap — so an install
        configured this way keeps routing. It is still refused at save time,
        because it serves exactly one deployment.
        """
        assert foundry.endpoint_profile(api_base) == "legacy_deployment_uri"


class TestNormalization:
    """Nothing is ever appended. Guessing a suffix confuses the two APIs."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            (f"{RESOURCE}/openai/v1/", f"{RESOURCE}/openai/v1"),
            (f"{RESOURCE}/models///", f"{RESOURCE}/models"),
            (f"{RESOURCE}/", RESOURCE),
            # Pasted from a curl example.
            (f"{RESOURCE}/openai/v1/chat/completions", f"{RESOURCE}/openai/v1"),
            (f"{RESOURCE}/openai/v1/embeddings", f"{RESOURCE}/openai/v1"),
            # Pasted from the portal's Target URI box, query and all.
            (
                f"{RESOURCE}/openai/v1/chat/completions?api-version=2024-05-01-preview",
                f"{RESOURCE}/openai/v1",
            ),
            # Already canonical: unchanged.
            (f"{RESOURCE}/openai/v1", f"{RESOURCE}/openai/v1"),
            ("  " + f"{RESOURCE}/models" + "  ", f"{RESOURCE}/models"),
        ],
    )
    def test_shapes_an_operator_actually_pastes(self, raw, expected) -> None:
        assert foundry.normalized_api_base(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "   "])
    def test_blank_stays_blank(self, raw) -> None:
        assert foundry.normalized_api_base(raw) == ""

    def test_a_non_url_is_left_alone_for_the_health_check_to_reject(self) -> None:
        """Rewriting a malformed value would hide what the operator typed."""
        assert foundry.normalized_api_base("not-a-url") == "not-a-url"

    def test_normalization_is_idempotent(self) -> None:
        once = foundry.normalized_api_base(f"{RESOURCE}/openai/v1/chat/completions?x=1")
        assert foundry.normalized_api_base(once) == once


class TestTransportSelection:
    """`hosted_vllm` is a transport. `azure_ai` stays the provider identity."""

    @pytest.mark.parametrize(
        "api_base, expected_route",
        [
            (f"{RESOURCE}/openai/v1", foundry.OPENAI_COMPATIBLE_ROUTE),
            (f"{RESOURCE}/openai/v1/", foundry.OPENAI_COMPATIBLE_ROUTE),
            (f"{RESOURCE}/api/projects/p/openai/v1", foundry.OPENAI_COMPATIBLE_ROUTE),
            (f"{RESOURCE}/openai/v1/chat/completions", foundry.OPENAI_COMPATIBLE_ROUTE),
            (f"{RESOURCE}/models", "azure_ai"),
            (RESOURCE, "azure_ai"),
        ],
    )
    def test_the_endpoint_picks_the_transport(self, api_base, expected_route) -> None:
        assert foundry.litellm_route({"api_base": api_base}) == expected_route

    @pytest.mark.parametrize(
        "stored",
        [
            {},
            None,
            {"api_base": ""},
            {"api_base": "not-a-url"},
            {"api_base": f"{RESOURCE}/anthropic/v1"},
            {"api_base": f"{RESOURCE}/openai/deployments/gpt-4o"},
        ],
    )
    def test_an_unclassifiable_endpoint_is_refused_not_routed(self, stored) -> None:
        """There is no safe default, so there is no fallback.

        The native handler builds a wrong URL for the v1 surface, and the
        OpenAI-compatible one builds a plausible-looking URL for literally any
        input — either guess turns a fixable configuration error into an
        opaque upstream failure.
        """
        with pytest.raises(foundry.UnsupportedEndpointError, match="/openai/v1"):
            foundry.litellm_route(stored)

    def test_the_compatibility_shape_still_routes_natively(self) -> None:
        """An install already configured this way must not break."""
        assert (
            foundry.litellm_route(
                {"api_base": "https://c.openai.azure.com/openai/deployments/gpt-4o"}
            )
            == "azure_ai"
        )

    def test_the_static_alias_is_the_native_route(self) -> None:
        """So every caller without stored credentials stays on the safe default."""
        assert route_aliases()["azure_ai"] == "azure_ai"

    def test_the_registry_resolves_the_dynamic_route(self) -> None:
        assert (
            litellm_route_for("azure_ai", {"api_base": f"{RESOURCE}/openai/v1"})
            == foundry.OPENAI_COMPATIBLE_ROUTE
        )
        assert litellm_route_for("azure_ai", {"api_base": f"{RESOURCE}/models"}) == "azure_ai"

    def test_a_provider_without_the_hook_keeps_its_static_alias(self) -> None:
        assert litellm_route_for("watsonx_onprem", {"api_base": "https://cpd.example.com"}) == (
            "watsonx"
        )

    def test_an_unknown_provider_has_no_route_of_its_own(self) -> None:
        assert litellm_route_for("openai", {}) is None

    def test_the_registry_propagates_the_refusal_rather_than_masking_it(self) -> None:
        """Substituting the static alias would turn a clear error into a wrong request."""
        with pytest.raises(foundry.UnsupportedEndpointError):
            litellm_route_for("azure_ai", {"api_base": "not-a-url"})

    def test_foundry_is_registered_under_its_openrag_key(self) -> None:
        assert get_enhancement("azure_ai") is foundry
        assert foundry.PROVIDER_KEY == "azure_ai"


class TestCredentials:
    def test_the_endpoint_is_normalized_on_the_way_to_litellm(self) -> None:
        credentials = foundry.litellm_credentials(
            {"api_base": f"{RESOURCE}/openai/v1/chat/completions", "api_key": "k"}
        )
        assert credentials["api_base"] == f"{RESOURCE}/openai/v1"
        assert credentials["api_key"] == "k"

    def test_api_version_is_dropped_on_the_versionless_v1_surface(self) -> None:
        """Forwarding it would append `?api-version=` to an API that has none."""
        credentials = foundry.litellm_credentials(
            {"api_base": f"{RESOURCE}/openai/v1", "api_key": "k", "api_version": "2024-05-01"}
        )
        assert "api_version" not in credentials

    def test_api_version_survives_on_the_legacy_route_that_dates_its_api(self) -> None:
        credentials = foundry.litellm_credentials(
            {"api_base": f"{RESOURCE}/models", "api_key": "k", "api_version": "2024-05-01"}
        )
        assert credentials["api_version"] == "2024-05-01"

    def test_local_only_fields_never_reach_the_request_body(self) -> None:
        """LiteLLM passes kwargs it does not recognise straight through."""
        credentials = foundry.litellm_credentials(
            {"api_base": f"{RESOURCE}/openai/v1", "api_key": "k", "deployment_names": "a\nb"}
        )
        assert "deployment_names" not in credentials

    @pytest.mark.parametrize("scheme", ["http", "ftp"])
    def test_a_cleartext_endpoint_is_refused(self, scheme) -> None:
        """Foundry is a public cloud service; there is no port-forward case.

        `openshift_ai` only warns, because a cluster-local predictor can
        legitimately be plain HTTP. Nothing here can be.
        """
        with pytest.raises(ValueError, match="https"):
            foundry.litellm_credentials(
                {"api_base": f"{scheme}://contoso.services.ai.azure.com/openai/v1", "api_key": "k"}
            )

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("a\nb", ("a", "b")),
            ("a, b,c", ("a", "b", "c")),
            ("  a  \n\n  b  ", ("a", "b")),
            ("a\na\nb", ("a", "b")),
            ("", ()),
            (None, ()),
        ],
    )
    def test_deployment_names_accept_what_people_paste(self, raw, expected) -> None:
        assert foundry.deployment_names({"deployment_names": raw}) == expected


class TestCredentialForm:
    def test_every_secret_is_typed_so_it_is_encrypted_at_rest(self) -> None:
        """Encryption keys off `field_type`, not off the field's name.

        A secret declared `text` is written to config.yaml in cleartext.
        """
        from services.model_catalog import secret_field_keys

        assert "api_key" in secret_field_keys("azure_ai")

    def test_deployment_names_are_configuration_not_a_credential(self) -> None:
        """`secret_field_keys` classifies by field type, not meaning.

        A `textarea` would be encrypted at rest, leaving ciphertext in
        config.yaml where plain configuration belongs. The form system has no
        non-secret multiline type, so this is `text` until it does.
        """
        from services.model_catalog import credential_fields, secret_field_keys

        assert "deployment_names" not in secret_field_keys("azure_ai")
        field = next(f for f in credential_fields("azure_ai") if f["key"] == "deployment_names")
        assert field["field_type"] == "text"

    def test_the_form_replaces_litellms_deployment_pinning_placeholder(self) -> None:
        """LiteLLM's own `api_base` placeholder is a per-deployment Target URI.

        Following it produces a provider that serves exactly one deployment:
        every model selected resolves to the one baked into the URL.
        """
        from services.model_catalog import credential_fields

        api_base = next(f for f in credential_fields("azure_ai") if f["key"] == "api_base")
        assert "/openai/v1" in (api_base["placeholder"] or "")
        assert "deployments/" not in (api_base["placeholder"] or "")

    def test_the_form_asks_for_deployment_names(self) -> None:
        from services.model_catalog import credential_fields

        keys = {field["key"] for field in credential_fields("azure_ai")}
        assert {"api_base", "api_key", "api_version", "deployment_names"} <= keys


class TestModelsUrl:
    @pytest.mark.parametrize(
        "api_base, expected",
        [
            (f"{RESOURCE}/openai/v1", f"{RESOURCE}/openai/v1/models"),
            (f"{RESOURCE}/api/projects/p/openai/v1", f"{RESOURCE}/api/projects/p/openai/v1/models"),
            # The legacy endpoint already *is* the listing path.
            (f"{RESOURCE}/models", f"{RESOURCE}/models"),
            (RESOURCE, f"{RESOURCE}/models"),
        ],
    )
    def test_the_listing_path_is_not_doubled(self, api_base, expected) -> None:
        assert foundry.models_url(api_base) == expected

    def test_both_auth_header_styles_are_sent(self) -> None:
        """litellm itself disagrees with itself here.

        Its `azure_ai` chat path sends `api-key` while its embedding path sends
        `Bearer` to the same endpoint, so the probe sends both rather than
        failing for a reason unrelated to credential validity.
        """
        headers = foundry.health_headers({"api_key": "k"})
        assert headers["api-key"] == "k"
        assert headers["Authorization"] == "Bearer k"

    def test_no_headers_without_a_key(self) -> None:
        assert foundry.health_headers({}) == {}


class TestLightweightHealthCheck:
    """The pre-save probe: authenticated, read-only, and never billed."""

    @pytest.mark.asyncio
    async def test_a_good_endpoint_and_key_pass_without_an_inference_call(
        self, monkeypatch
    ) -> None:
        requests: list[tuple[str, dict]] = []

        class _Response:
            status_code = 200
            text = ""

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers=None):
                requests.append((url, headers or {}))
                return _Response()

        monkeypatch.setattr("httpx.AsyncClient", lambda **_kw: _Client())

        await foundry.lightweight_health_check(
            {"api_base": f"{RESOURCE}/openai/v1", "api_key": "k"}
        )

        assert len(requests) == 1
        url, headers = requests[0]
        assert url == f"{RESOURCE}/openai/v1/models"
        # A listing, not a completion: nothing that bills a deployment.
        assert "chat/completions" not in url
        assert "embeddings" not in url
        assert headers["api-key"] == "k"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "stored, match",
        [
            ({"api_key": "k"}, "endpoint is required"),
            ({"api_base": f"{RESOURCE}/openai/v1"}, "API key is required"),
            (
                {"api_base": f"{RESOURCE}/openai/deployments/gpt-4o", "api_key": "k"},
                "/openai/v1",
            ),
            ({"api_base": "not-a-url", "api_key": "k"}, "/openai/v1"),
        ],
    )
    async def test_a_form_that_cannot_be_called_fails_before_any_request(
        self, monkeypatch, stored, match
    ) -> None:
        def _no_calls(**_kw):
            raise AssertionError("the health check must not reach the network here")

        monkeypatch.setattr("httpx.AsyncClient", _no_calls)

        with pytest.raises(ValueError, match=match):
            await foundry.lightweight_health_check(stored)

    @pytest.mark.asyncio
    async def test_a_403_is_a_permission_result_not_a_bad_credential(self, monkeypatch) -> None:
        """Listing deployments can need a permission inference does not.

        Reporting "invalid key" for it sends the operator after the wrong
        problem.
        """

        class _Response:
            status_code = 403
            text = "Forbidden"

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers=None):
                return _Response()

        monkeypatch.setattr("httpx.AsyncClient", lambda **_kw: _Client())

        with pytest.raises(PermissionError, match="cannot list deployments"):
            await foundry.lightweight_health_check(
                {"api_base": f"{RESOURCE}/openai/v1", "api_key": "k"}
            )

    @pytest.mark.asyncio
    async def test_a_rejected_credential_surfaces_the_upstream_detail(self, monkeypatch) -> None:
        class _Response:
            status_code = 401
            text = "Access denied due to invalid subscription key"

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers=None):
                return _Response()

        monkeypatch.setattr("httpx.AsyncClient", lambda **_kw: _Client())

        with pytest.raises(Exception, match="invalid subscription key"):
            await foundry.lightweight_health_check(
                {"api_base": f"{RESOURCE}/openai/v1", "api_key": "bad"}
            )


class TestTransportMetadataCost:
    """What routing as `hosted_vllm` gives up, pinned so it stays visible."""

    def test_the_native_route_keeps_litellms_foundry_price_row(self) -> None:
        import litellm

        assert "azure_ai/gpt-6-luna" in litellm.model_cost

    def test_the_transport_route_has_no_price_row_of_its_own(self) -> None:
        """Cost attribution is lost for a deployment named after a model.

        Harmless today — OpenRAG computes no cost — and recoverable when it
        does: `completion_cost(..., base_model="azure_ai/<model>")` returns the
        native figure exactly.
        """
        import litellm

        assert "hosted_vllm/gpt-6-luna" not in litellm.model_cost

    def test_base_model_restores_cost_attribution_on_the_transport_route(self) -> None:
        from litellm import completion_cost
        from litellm.types.utils import Choices, Message, ModelResponse, Usage

        def _response(model: str) -> ModelResponse:
            response = ModelResponse(
                id="1",
                model=model,
                object="chat.completion",
                created=0,
                choices=[
                    Choices(
                        index=0,
                        message=Message(role="assistant", content="ok"),
                        finish_reason="stop",
                    )
                ],
            )
            # `usage` is set after construction, not as a field: litellm
            # attaches it dynamically and its model does not declare it.
            response.usage = Usage(  # type: ignore[attr-defined]
                prompt_tokens=1000, completion_tokens=1000, total_tokens=2000
            )
            return response

        native = completion_cost(
            completion_response=_response("azure_ai/gpt-6-luna"), model="azure_ai/gpt-6-luna"
        )
        via_transport = completion_cost(
            completion_response=_response("hosted_vllm/prod-llm-01"),
            model="hosted_vllm/prod-llm-01",
            base_model="azure_ai/gpt-6-luna",
        )
        assert native > 0
        assert via_transport == native

    def test_transport_identity_and_metadata_identity_stay_separate(self) -> None:
        """`hosted_vllm/<model>` is how it is called; `azure_ai/<model>` is what it is.

        LiteLLM has no rows under the transport, so metadata is looked up under
        the logical provider key — which is also LiteLLM's own key for Foundry.
        """
        from services.llm_gateway import _model_info

        # Foundry-exclusive: the bare name matches nothing, so only the
        # logical identity resolves it.
        assert not _model_info("hosted_vllm/Phi-4")
        assert _model_info("hosted_vllm/Phi-4", "azure_ai")
        assert _model_info("hosted_vllm/Phi-4", "azure_ai") == _model_info("azure_ai/Phi-4")

    def test_the_logical_identity_is_preferred_over_a_public_vendors_row(self) -> None:
        """A shared name resolves either way, but not to the same numbers.

        `gpt-6-luna` exists bare (OpenAI's row) and under `azure_ai` (Azure's).
        Trying the logical id first is what keeps Azure's pricing from being
        reported as OpenAI's.
        """
        from services.llm_gateway import _model_info

        assert _model_info("hosted_vllm/gpt-6-luna", "azure_ai") == _model_info(
            "azure_ai/gpt-6-luna"
        )

    def test_an_operator_named_deployment_resolves_under_neither(self) -> None:
        """No table can know a name its owner invented. The remaining limitation."""
        from services.llm_gateway import _model_info

        assert not _model_info("hosted_vllm/prod-llm-01", "azure_ai")


def _config(api_base: str, **extra):
    """A config carrying one configured `azure_ai` provider."""
    from types import SimpleNamespace

    from config.config_manager import (
        AnthropicConfig,
        GenericProviderConfig,
        OllamaConfig,
        OpenAIConfig,
        ProvidersConfig,
        WatsonXConfig,
    )

    credentials = {"api_base": api_base, "api_key": "k", **extra}
    return SimpleNamespace(
        providers=ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
            custom={"azure_ai": GenericProviderConfig(credentials=credentials, configured=True)},
        ),
        agent=SimpleNamespace(llm_model="", llm_provider="openai"),
        knowledge=SimpleNamespace(embedding_model="", embedding_provider="openai"),
    )


class TestGatewayRouting:
    """`resolve_call` picks the transport from the stored endpoint."""

    @pytest.mark.parametrize("kind", ["chat", "embedding"])
    def test_the_v1_surface_is_routed_over_the_openai_compatible_transport(self, kind) -> None:
        from services.llm_gateway import resolve_call

        litellm_model, provider, credentials = resolve_call(
            "azure_ai:my-deployment", kind=kind, config=_config(f"{RESOURCE}/openai/v1")
        )

        assert litellm_model == "hosted_vllm/my-deployment"
        # The OpenRAG key is unchanged: it is what the caller, the credential
        # store and every indexed embedding space still see.
        assert provider == "azure_ai"
        assert credentials["api_base"] == f"{RESOURCE}/openai/v1"

    @pytest.mark.parametrize("kind", ["chat", "embedding"])
    def test_the_project_surface_is_routed_the_same_way(self, kind) -> None:
        from services.llm_gateway import resolve_call

        litellm_model, provider, _credentials = resolve_call(
            "azure_ai:my-deployment",
            kind=kind,
            config=_config(f"{RESOURCE}/api/projects/proj-1/openai/v1"),
        )

        assert litellm_model == "hosted_vllm/my-deployment"
        assert provider == "azure_ai"

    @pytest.mark.parametrize("api_base", [f"{RESOURCE}/models", RESOURCE])
    def test_the_legacy_surface_keeps_the_native_route(self, api_base) -> None:
        from services.llm_gateway import resolve_call

        litellm_model, provider, _credentials = resolve_call(
            "azure_ai:my-deployment", kind="chat", config=_config(api_base)
        )

        assert litellm_model == "azure_ai/my-deployment"
        assert provider == "azure_ai"

    def test_the_endpoint_reaches_litellm_normalized(self) -> None:
        from services.llm_gateway import resolve_call

        _model, _provider, credentials = resolve_call(
            "azure_ai:my-deployment",
            kind="chat",
            config=_config(f"{RESOURCE}/openai/v1/chat/completions"),
        )

        assert credentials["api_base"] == f"{RESOURCE}/openai/v1"

    def test_the_provider_id_round_trips_for_an_indexed_embedding_space(self) -> None:
        """`space:azure_ai:<model>` must still resolve after the transport change.

        The space id is persisted per chunk, so a change in routing that broke
        it would orphan indexed vectors.
        """
        from services.llm_gateway import resolve_call

        litellm_model, provider, _credentials = resolve_call(
            "space:azure_ai:my-deployment",
            kind="embedding",
            config=_config(f"{RESOURCE}/openai/v1"),
        )

        assert provider == "azure_ai"
        assert litellm_model == "hosted_vllm/my-deployment"


class TestRerouteGuard:
    """The guard compares against the route the gateway chose, not the key.

    For Foundry on `/openai/v1` the route and the provider key differ *by
    design*, so comparing against `azure_ai` would warn on every healthy call.
    """

    @staticmethod
    def _recorded_warnings(monkeypatch) -> list[str]:
        """Warnings the gateway emits, read off its module logger.

        Logging goes through structlog, which does not route to caplog.
        """
        from services import llm_gateway

        messages: list[str] = []

        class _Recorder:
            def warning(self, message, **fields):
                messages.append(f"{message} {fields}")

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        monkeypatch.setattr(llm_gateway, "logger", _Recorder())
        llm_gateway.forget_route_mismatches()
        return messages

    @pytest.mark.parametrize("api_base", [f"{RESOURCE}/openai/v1", f"{RESOURCE}/models"])
    def test_the_chosen_transport_is_never_reported_as_a_mismatch(
        self, monkeypatch, api_base
    ) -> None:
        """Including the v1 case, where route and provider key differ."""
        from services.llm_gateway import resolve_call

        warnings = self._recorded_warnings(monkeypatch)
        resolve_call("azure_ai:my-deployment", kind="chat", config=_config(api_base))

        assert not [w for w in warnings if "different provider" in w]

    def test_litellm_redeciding_underneath_us_is_reported(self, monkeypatch) -> None:
        """What the litellm 1.84.0 `azure_ai` -> `azure` reroute looked like.

        The floor this repo pins no longer does it. This makes a return
        visible rather than an opaque 404 against a Foundry hostname.
        """
        from services import llm_gateway

        warnings = self._recorded_warnings(monkeypatch)
        monkeypatch.setattr(
            "litellm.get_llm_provider",
            lambda model, **_kw: (model.split("/", 1)[-1], "azure", None, None),
        )

        llm_gateway.resolve_call(
            "azure_ai:my-deployment", kind="chat", config=_config(f"{RESOURCE}/models")
        )

        reported = [w for w in warnings if "different provider" in w]
        assert reported
        assert "'resolved_route': 'azure'" in reported[0]
        assert "'intended_route': 'azure_ai'" in reported[0]

    def test_a_mismatch_is_reported_once_not_per_request(self, monkeypatch) -> None:
        from services import llm_gateway

        warnings = self._recorded_warnings(monkeypatch)
        monkeypatch.setattr(
            "litellm.get_llm_provider",
            lambda model, **_kw: (model.split("/", 1)[-1], "azure", None, None),
        )
        config = _config(f"{RESOURCE}/models")

        for _ in range(3):
            llm_gateway.resolve_call("azure_ai:my-deployment", kind="chat", config=config)

        assert len([w for w in warnings if "different provider" in w]) == 1
