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
    """The surface is classified from the path wherever the path says enough.

    A Foundry resource can serve Azure OpenAI deployments too, so a spelled-out
    path says which API is being addressed and the host does not. The host is
    consulted only for the shapes that carry no path to read.
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
            # A bare resource root is the legacy route's own default *on this
            # host*: litellm's azure_ai handler appends `/models/...` and
            # reaches the right place. See the host test below.
            (RESOURCE, "legacy_models"),
            (f"{RESOURCE}/", "legacy_models"),
            # The model *listing* URL names the same surface as its parent.
            # Pasted whole it used to match `/models` first and route as
            # legacy, so litellm built `.../openai/v1/models/chat/completions`.
            (f"{RESOURCE}/openai/v1/models", "resource_openai_v1"),
            (f"{RESOURCE}/openai/v1/models/", "resource_openai_v1"),
            (f"{RESOURCE}/api/projects/proj-1/openai/v1/models", "project_openai_v1"),
        ],
    )
    def test_the_supported_shapes(self, api_base, expected) -> None:
        assert foundry.endpoint_profile(api_base) == expected

    @pytest.mark.parametrize(
        "host, expected",
        [
            ("contoso.services.ai.azure.com", "legacy_models"),
            # LiteLLM picks the legacy call path by testing the hostname for
            # `services.ai.azure.com`. Off it, a bare root becomes plain
            # `/chat/completions` and 404s, and the auth header changes from
            # `api-key` to `Authorization` as well — so the root is refused
            # rather than routed on a host-dependent guess.
            ("contoso.cognitiveservices.azure.com", "unknown"),
            ("foundry.internal.example", "unknown"),
        ],
    )
    def test_a_bare_root_is_only_unambiguous_on_the_foundry_host(self, host, expected) -> None:
        assert foundry.endpoint_profile(f"https://{host}") == expected

    def test_an_explicit_models_path_routes_on_any_host(self) -> None:
        """Spelled out, the path is enough and the host stops mattering.

        This is what an operator on a non-Foundry hostname is asked for when
        the bare root is refused, so it has to keep working.
        """
        assert (
            foundry.endpoint_profile("https://contoso.cognitiveservices.azure.com/models")
            == "legacy_models"
        )

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
            # Credentials in the URL. httpx would send the userinfo as Basic
            # auth next to the real API key, and the value is stored as
            # ordinary non-secret configuration, so it is refused outright
            # rather than classified and used.
            "https://user:secret@contoso.services.ai.azure.com/openai/v1",
            "https://user@contoso.services.ai.azure.com/models",
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

    def test_a_query_string_secret_never_reaches_the_logs(self, monkeypatch) -> None:
        """The pasted value is not logged, only what it normalizes to.

        An operator's endpoint can carry credentials in its query string — a
        Target URI copied from the portal already carries `?api-version=`, and
        nothing stops a key being in there too. Logging the raw value would
        put it in plaintext in the application log.
        """
        records: list[tuple[str, dict]] = []

        class _Recorder:
            def debug(self, message, **fields):
                records.append((message, fields))

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        monkeypatch.setattr(foundry, "logger", _Recorder())

        secret = "super-secret-key-value"
        foundry.normalized_api_base(
            f"{RESOURCE}/openai/v1/chat/completions?api-version=2024-05-01&api-key={secret}"
        )

        assert records, "normalization should have been logged"
        rendered = repr(records)
        assert secret not in rendered
        assert "api-key" not in rendered
        assert "api-version" not in rendered
        _message, fields = records[0]
        assert fields == {
            "normalized": f"{RESOURCE}/openai/v1",
            "dropped_query": True,
        }

    def test_url_embedded_credentials_never_reach_the_logs(self, monkeypatch) -> None:
        """Stripping the query is only half of it.

        `user:password@` survives normalization — it lives in the netloc, not
        the query — so the diagnostic log has to take it off separately. The
        endpoint is refused elsewhere, but the log runs first and has to be
        safe on its own.
        """
        records: list[dict] = []

        class _Recorder:
            def debug(self, _message, **fields):
                records.append(fields)

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        monkeypatch.setattr(foundry, "logger", _Recorder())

        secret = "url-embedded-password"
        foundry.normalized_api_base(
            f"https://operator:{secret}@contoso.services.ai.azure.com/openai/v1/chat/completions"
        )

        assert records, "normalization should have been logged"
        rendered = repr(records)
        assert secret not in rendered
        assert "operator" not in rendered
        assert records[0]["normalized"] == f"{RESOURCE}/openai/v1"

    def test_no_query_is_reported_as_none_dropped(self, monkeypatch) -> None:
        records: list[dict] = []

        class _Recorder:
            def debug(self, _message, **fields):
                records.append(fields)

            def __getattr__(self, _name):
                return lambda *args, **kwargs: None

        monkeypatch.setattr(foundry, "logger", _Recorder())
        foundry.normalized_api_base(f"{RESOURCE}/openai/v1/")

        assert records == [{"normalized": f"{RESOURCE}/openai/v1", "dropped_query": False}]


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

    @pytest.mark.parametrize(
        "api_base",
        [
            "https://operator:secret@contoso.services.ai.azure.com/openai/v1",
            "https://operator@contoso.services.ai.azure.com/openai/v1",
        ],
    )
    def test_credentials_in_the_url_are_refused(self, api_base) -> None:
        """The endpoint is handed to LiteLLM, to httpx and to config.yaml.

        httpx turns userinfo into a Basic auth header sent alongside the real
        API key, and config.yaml stores the endpoint as plain non-secret
        configuration. Foundry authenticates with the key field, so there is
        no correct form of this.
        """
        with pytest.raises(ValueError, match="credentials in the URL"):
            foundry.litellm_credentials({"api_base": api_base, "api_key": "k"})

    def test_local_only_fields_never_reach_the_request_body(self) -> None:
        """LiteLLM passes kwargs it does not recognise straight through."""
        credentials = foundry.litellm_credentials(
            {
                "api_base": f"{RESOURCE}/openai/v1",
                "api_key": "k",
                "chat_deployments": "a, b",
                "embedding_deployments": "c",
                "vlm_deployments": "a",
            }
        )
        for field in ("chat_deployments", "embedding_deployments", "vlm_deployments"):
            assert field not in credentials

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

    def test_the_three_deployment_lists_are_independent(self) -> None:
        """A flat list could not say which picker a name belongs in."""
        stored = {
            "chat_deployments": "chat-a, chat-b",
            "embedding_deployments": "embed-a",
            "vlm_deployments": "chat-a",
        }
        assert foundry.chat_deployments(stored) == ("chat-a", "chat-b")
        assert foundry.embedding_deployments(stored) == ("embed-a",)
        assert foundry.vlm_deployments(stored) == ("chat-a",)


class TestCredentialForm:
    def test_every_secret_is_typed_so_it_is_encrypted_at_rest(self) -> None:
        """Encryption keys off `field_type`, not off the field's name.

        A secret declared `text` is written to config.yaml in cleartext.
        """
        from services.model_catalog import secret_field_keys

        assert "api_key" in secret_field_keys("azure_ai")

    def test_deployment_lists_are_configuration_not_credentials(self) -> None:
        """`secret_field_keys` classifies by field type, not meaning.

        A `textarea` would be encrypted at rest, leaving ciphertext in
        config.yaml where plain configuration belongs. The form system has no
        non-secret multiline type, so this is `text` until it does.
        """
        from services.model_catalog import credential_fields, secret_field_keys

        fields = {f["key"]: f for f in credential_fields("azure_ai")}
        for key in ("chat_deployments", "embedding_deployments", "vlm_deployments"):
            assert key not in secret_field_keys("azure_ai"), key
            assert fields[key]["field_type"] == "text", key

    def test_the_form_replaces_litellms_deployment_pinning_placeholder(self) -> None:
        """LiteLLM's own `api_base` placeholder is a per-deployment Target URI.

        Following it produces a provider that serves exactly one deployment:
        every model selected resolves to the one baked into the URL.
        """
        from services.model_catalog import credential_fields

        api_base = next(f for f in credential_fields("azure_ai") if f["key"] == "api_base")
        assert "/openai/v1" in (api_base["placeholder"] or "")
        assert "deployments/" not in (api_base["placeholder"] or "")

    def test_the_form_asks_for_each_kind_of_deployment_separately(self) -> None:
        """A flat list cannot say which picker a name belongs in.

        Foundry deployment names are operator-chosen — `vision-primary` and
        `prod-embed` carry no machine-readable role — so the role has to be
        stated rather than parsed out of the name.
        """
        from services.model_catalog import credential_fields

        keys = {field["key"] for field in credential_fields("azure_ai")}
        assert {
            "api_base",
            "api_key",
            "api_version",
            "chat_deployments",
            "embedding_deployments",
            "vlm_deployments",
        } <= keys
        assert "deployment_names" not in keys


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


class TestErrorLabels:
    """What the user is told the call was, when it fails.

    The label is built from the *routed* id, so for Foundry on `/openai/v1` it
    carries `hosted_vllm/`. Joined naively onto the OpenRAG key that produces
    `azure_ai/hosted_vllm/<deployment>`, which names two providers and reads
    like a bug in the error it appears in.
    """

    def test_the_transport_prefix_is_stripped_for_a_v1_foundry_model(self, monkeypatch) -> None:
        from services import llm_gateway

        monkeypatch.setattr(llm_gateway, "_get_config", lambda: _config(f"{RESOURCE}/openai/v1"))
        assert (
            llm_gateway._call_label("azure_ai", "hosted_vllm/my-deployment")
            == "azure_ai/my-deployment"
        )

    def test_the_legacy_route_needs_no_stripping(self, monkeypatch) -> None:
        from services import llm_gateway

        monkeypatch.setattr(llm_gateway, "_get_config", lambda: _config(f"{RESOURCE}/models"))
        assert (
            llm_gateway._call_label("azure_ai", "azure_ai/my-deployment")
            == "azure_ai/my-deployment"
        )

    def test_a_models_name_that_contains_a_slash_is_left_whole(self, monkeypatch) -> None:
        """Only a *transport* prefix comes off, never part of the model id.

        watsonx serves `openai/gpt-oss-120b`, whose own name starts with a
        provider key. Deriving the route from the id's first segment instead
        of from the configuration would eat it.
        """
        from services import llm_gateway

        monkeypatch.setattr(llm_gateway, "_get_config", lambda: _config(f"{RESOURCE}/openai/v1"))
        assert (
            llm_gateway._call_label("watsonx_onprem", "watsonx/openai/gpt-oss-120b")
            == "watsonx_onprem/openai/gpt-oss-120b"
        )

    def test_a_broken_configuration_still_produces_a_label(self, monkeypatch) -> None:
        """This runs while building an error message; it cannot raise its own."""
        from services import llm_gateway

        def _explode():
            raise RuntimeError("config is unreadable")

        monkeypatch.setattr(llm_gateway, "_get_config", _explode)
        assert llm_gateway._call_label("azure_ai", "hosted_vllm/my-deployment")


class TestRouteResolutionFailsClosed:
    """A configuration that cannot be read must not fall back to a guess.

    `litellm_provider_key` treats an empty mapping as "nothing to go on" and
    answers with the static alias, which for Foundry is `azure_ai` — the
    native handler, and the wrong URL for a `/openai/v1` endpoint. Swallowing
    a read failure therefore turns a fixable error into the opaque upstream
    404 this module exists to prevent.
    """

    def test_a_config_without_the_untranslated_form_is_not_an_error(self) -> None:
        """Some config objects simply do not keep it; that is not a failure."""
        from types import SimpleNamespace

        from services.llm_gateway import _stored_credentials

        assert _stored_credentials("azure_ai", SimpleNamespace(providers=object())) == {}
        assert _stored_credentials("azure_ai", SimpleNamespace()) == {}

    def test_a_failure_to_read_surfaces_instead_of_routing_on_the_alias(self) -> None:
        from types import SimpleNamespace

        from services.llm_gateway import _stored_credentials

        def _explode(_provider):
            raise RuntimeError("credential store is down")

        config = SimpleNamespace(providers=SimpleNamespace(stored_credentials=_explode))
        with pytest.raises(RuntimeError, match="credential store is down"):
            _stored_credentials("azure_ai", config)


class TestRerouteGuardHygiene:
    """The guard runs on every `resolve_call`, so its memo is on a hot path."""

    def test_the_memo_is_bounded(self) -> None:
        """Its key holds the model id, which arrives in the request body.

        Unbounded, that is a cache an unauthenticated caller can grow without
        limit by varying the model name.
        """
        from services import llm_gateway

        llm_gateway.forget_route_mismatches()
        try:
            for index in range(llm_gateway._ROUTE_CHECK_MEMO_MAX * 2):
                llm_gateway._warn_on_unexpected_route(
                    "azure_ai", f"hosted_vllm/model-{index}", "hosted_vllm"
                )
            assert len(llm_gateway._CHECKED_ROUTES) <= llm_gateway._ROUTE_CHECK_MEMO_MAX
        finally:
            llm_gateway.forget_route_mismatches()

    def test_a_repeated_model_does_not_re_run_the_resolver(self, monkeypatch) -> None:
        """One resolver call per distinct id, not one per request."""
        import litellm

        from services import llm_gateway

        calls: list[str] = []

        def _counting(model, **_kwargs):
            calls.append(model)
            return model, "hosted_vllm", None, None

        monkeypatch.setattr(litellm, "get_llm_provider", _counting)
        llm_gateway.forget_route_mismatches()
        try:
            for _ in range(5):
                llm_gateway._warn_on_unexpected_route(
                    "azure_ai", "hosted_vllm/my-deployment", "hosted_vllm"
                )
            assert calls == ["hosted_vllm/my-deployment"]
        finally:
            llm_gateway.forget_route_mismatches()

    @pytest.mark.parametrize(
        "provider, litellm_model, route",
        [
            # `openai` sends the id unprefixed, so nothing was asserted.
            ("openai", "claude-sonnet-4", "openai"),
            # A model whose own *name* carries a vendor segment. The id still
            # does not begin with the route that was asked for.
            ("openai", "meta-llama/Llama-3-70B", "openai"),
        ],
    )
    def test_an_unasserted_route_is_not_second_guessed(
        self, monkeypatch, provider, litellm_model, route
    ) -> None:
        """LiteLLM resolving these elsewhere is not evidence of anything.

        The guard's claim is "we asked for `<route>/<name>`". Where the id
        does not carry the route, there is no claim, and an OpenAI-compatible
        server serving either of these would warn on every healthy request.
        """
        import litellm

        from services import llm_gateway

        def _unexpected(**_kwargs):
            pytest.fail("an unasserted route has nothing to check")

        monkeypatch.setattr(litellm, "get_llm_provider", _unexpected)
        llm_gateway.forget_route_mismatches()
        try:
            llm_gateway._warn_on_unexpected_route(provider, litellm_model, route)
        finally:
            llm_gateway.forget_route_mismatches()

    def test_a_prefixed_id_is_checked_even_when_the_route_is_the_provider_key(
        self, monkeypatch
    ) -> None:
        """The regression this guard exists for is an identity route.

        litellm 1.84.0 silently rerouted `azure_ai/gpt-4o` to `azure`, calling
        a Foundry hostname with the Azure OpenAI handler. Skipping the check
        wherever route == provider would have missed exactly that.
        """
        import litellm

        from services import llm_gateway

        warnings: list[dict] = []

        monkeypatch.setattr(
            litellm, "get_llm_provider", lambda model, **_k: (model, "azure", None, None)
        )
        monkeypatch.setattr(
            llm_gateway.logger,
            "warning",
            lambda _message, **fields: warnings.append(fields),
        )
        llm_gateway.forget_route_mismatches()
        try:
            llm_gateway._warn_on_unexpected_route("azure_ai", "azure_ai/gpt-4o", "azure_ai")
        finally:
            llm_gateway.forget_route_mismatches()

        assert warnings and warnings[0]["resolved_route"] == "azure"


class TestSaveTimeModelProbe:
    """The validator's model probe must use the same transport the gateway will.

    These two have separate route-building code. Resolving the route without
    the stored credentials picks the static alias, so the probe called
    `azure_ai/<model>` against a `/openai/v1` endpoint — which LiteLLM rewrites
    to `/openai/v1/models/chat/completions`. A correctly configured provider
    then failed to save with "Resource not found", for every model, which read
    as a credential or endpoint problem rather than a routing one.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["chat", "embedding"])
    @pytest.mark.parametrize("unsupported_endpoint", [False, True])
    async def test_route_errors_use_the_gateway_400(
        self, monkeypatch, kind, unsupported_endpoint
    ) -> None:
        from api.provider_validation import validate_provider_setup
        from services.llm_gateway import LlmGatewayError

        error = (
            foundry.UnsupportedEndpointError(foundry.UNSUPPORTED_ENDPOINT_MESSAGE)
            if unsupported_endpoint
            else ValueError("Invalid provider route")
        )

        def reject_route(*_args):
            raise error

        async def unexpected_call(**_kwargs):
            pytest.fail("An invalid route must fail before calling the provider")

        monkeypatch.setattr("services.model_catalog.litellm_provider_key", reject_route)
        monkeypatch.setattr("litellm.acompletion", unexpected_call)
        monkeypatch.setattr("litellm.aembedding", unexpected_call)

        with pytest.raises(LlmGatewayError) as caught:
            await validate_provider_setup(
                provider="azure_ai",
                credentials={"api_base": f"{RESOURCE}/openai/v1", "api_key": "k"},
                llm_model="my-deployment" if kind == "chat" else None,
                embedding_model="my-embed-deployment" if kind == "embedding" else None,
                verify_model=True,
            )

        assert caught.value.status_code == 400
        assert caught.value.message == str(error)
        assert caught.value.__cause__ is error

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "api_base, expected_route",
        [
            (f"{RESOURCE}/openai/v1", "hosted_vllm"),
            (f"{RESOURCE}/api/projects/p/openai/v1", "hosted_vllm"),
            (f"{RESOURCE}/models", "azure_ai"),
        ],
    )
    async def test_the_probe_routes_like_the_gateway(
        self, monkeypatch, api_base, expected_route
    ) -> None:
        from api import provider_validation

        captured: dict = {}

        async def _capture(model, **kwargs):
            captured["model"] = model
            raise AssertionError("stop before the network call")

        monkeypatch.setattr("litellm.acompletion", _capture)
        credentials = {"api_base": api_base, "api_key": "k"}

        with pytest.raises(AssertionError):
            await provider_validation._test_litellm_provider(
                provider="azure_ai",
                credentials=credentials,
                runtime_kwargs={},
                embedding_model=None,
                llm_model="my-deployment",
            )

        assert captured["model"] == f"{expected_route}/my-deployment"

    @pytest.mark.asyncio
    async def test_the_embedding_probe_routes_the_same_way(self, monkeypatch) -> None:
        from api import provider_validation

        captured: dict = {}

        async def _capture(model, **kwargs):
            captured["model"] = model
            raise AssertionError("stop before the network call")

        monkeypatch.setattr("litellm.aembedding", _capture)

        with pytest.raises(AssertionError):
            await provider_validation._test_litellm_provider(
                provider="azure_ai",
                credentials={"api_base": f"{RESOURCE}/openai/v1", "api_key": "k"},
                runtime_kwargs={},
                embedding_model="my-embed-deployment",
                llm_model=None,
            )

        assert captured["model"] == "hosted_vllm/my-embed-deployment"

    def test_a_provider_without_a_dynamic_route_is_unaffected(self) -> None:
        """The static alias stays the answer for everything else."""
        from services.model_catalog import litellm_provider_key

        stored = {"api_base": "https://cpd.example.com", "username": "u", "api_key": "k"}
        assert litellm_provider_key("watsonx_onprem", stored) == "watsonx"
        assert litellm_provider_key("openai", {"api_key": "k"}) == "openai"


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
