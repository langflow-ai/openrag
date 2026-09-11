"""Red Hat OpenShift AI: KServe + vLLM endpoints, routed through LiteLLM's hosted_vllm."""

import time
from typing import Any

import pytest

import config.model_providers as model_providers
from config.config_manager import (
    AnthropicConfig,
    GenericProviderConfig,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
    credential_values_for_kind,
)
from enhancements.providers import registry
from enhancements.providers.redhat import openshift_ai as rhoai
from services import model_catalog
from services.llm_gateway import resolve_call, split_model_id

PROVIDER = rhoai.PROVIDER_KEY

CHAT_BASE = "https://openrag-chat-predictor.openrag-models.svc.cluster.local:8443/v1"
EMBED_BASE = "https://openrag-embed-predictor.openrag-models.svc.cluster.local:8443/v1"
TOKEN = "sha256~not-a-real-token"

CHAT_MODEL = "granite-3.3-2b-instruct"
EMBED_MODEL = "granite-embedding-english-r2"


@pytest.fixture(autouse=True)
def _reload_provider_config():
    model_providers.reload()
    yield
    model_providers.reload()


@pytest.fixture(autouse=True)
def _forget_module_state():
    """Model cache and TLS warnings are process-global; no test may inherit them."""
    rhoai.forget_models()
    rhoai.forget_tls_warnings()
    yield
    rhoai.forget_models()
    rhoai.forget_tls_warnings()


def _stored(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "api_base": CHAT_BASE,
        "embedding_api_base": EMBED_BASE,
        "api_key": TOKEN,
    }
    values.update(overrides)
    return {name: value for name, value in values.items() if value is not None}


def _providers(**credentials: Any) -> ProvidersConfig:
    return ProvidersConfig(
        openai=OpenAIConfig(),
        anthropic=AnthropicConfig(),
        watsonx=WatsonXConfig(),
        ollama=OllamaConfig(),
        custom={PROVIDER: GenericProviderConfig(credentials=dict(credentials), configured=True)},
    )


def _enable_in_oss(tmp_path, monkeypatch) -> None:
    """Point the run mode at a config file that offers this provider.

    The shipped `model_providers.yaml` has every mode false — the endpoints and
    token are deployment-specific, so it is turned on per deployment. A test that
    needs the catalogue has to do the same thing an operator does.
    """
    config = tmp_path / "model_providers.yaml"
    config.write_text(
        "providers:\n"
        f"  - name: {PROVIDER}\n"
        "    display_name: Red Hat OpenShift AI\n"
        "    modes:\n"
        "      oss: true\n"
        f"    models:\n      - {CHAT_MODEL}\n"
        f"    embedding_models:\n      - {EMBED_MODEL}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENRAG_RUN_MODE", "oss")
    monkeypatch.setenv("OPENRAG_MODEL_PROVIDERS_CONFIG", str(config))
    model_providers.reload()


# ---------------------------------------------------------------------------
# Credential form
# ---------------------------------------------------------------------------


def test_the_form_asks_for_two_endpoints_a_token_and_a_ca() -> None:
    """vLLM serves one model per InferenceService, so one endpoint is not enough."""
    fields = {field["key"]: field for field in model_catalog.credential_fields(PROVIDER)}

    assert set(fields) == {"api_base", "embedding_api_base", "api_key", "ssl_verify"}
    assert fields["api_base"]["field_type"] == "text"
    assert fields["embedding_api_base"]["field_type"] == "text"
    assert fields["api_key"]["field_type"] == "password"
    assert fields["ssl_verify"]["field_type"] == "text"


def test_only_the_token_is_encrypted_at_rest() -> None:
    """`field_type` drives encryption. A CA path is not a secret; a token is."""
    assert model_catalog.secret_field_keys(PROVIDER) == {"api_key"}


def test_an_endpoint_and_a_token_are_both_required() -> None:
    assert model_catalog.required_field_keys(PROVIDER) == ["api_base", "api_key"]


# ---------------------------------------------------------------------------
# Endpoint selection — the reason this module exists
# ---------------------------------------------------------------------------


def test_a_chat_call_goes_to_the_chat_endpoint() -> None:
    assert rhoai.litellm_credentials(_stored(), kind="chat")["api_base"] == CHAT_BASE


def test_an_embedding_call_goes_to_the_embedding_endpoint() -> None:
    """The whole point: one credential bag, two InferenceServices."""
    assert rhoai.litellm_credentials(_stored(), kind="embedding")["api_base"] == EMBED_BASE


def test_chat_is_the_default_kind() -> None:
    """An older caller that does not know about kinds must still reach a model."""
    assert rhoai.litellm_credentials(_stored())["api_base"] == CHAT_BASE


def test_one_endpoint_serves_both_when_no_embedding_url_is_given() -> None:
    """The second field is optional, so a single-endpoint gateway still works."""
    stored = _stored(embedding_api_base=None)

    assert rhoai.litellm_credentials(stored, kind="chat")["api_base"] == CHAT_BASE
    assert rhoai.litellm_credentials(stored, kind="embedding")["api_base"] == CHAT_BASE


@pytest.mark.parametrize("kind", ["chat", "embedding"])
def test_the_embedding_url_never_reaches_litellm(kind) -> None:
    """LiteLLM forwards kwargs it does not recognise, so a stray field lands in the body."""
    assert "embedding_api_base" not in rhoai.litellm_credentials(_stored(), kind=kind)


def test_no_endpoint_means_no_credentials_at_all() -> None:
    """Not tidiness: LiteLLM falls back to HOSTED_VLLM_API_BASE from the process
    environment when `api_base` is absent, so returning a bare token could send a
    cluster ServiceAccount token to whatever unrelated host is configured there.
    """
    assert rhoai.litellm_credentials({"api_key": TOKEN}) == {}


def test_the_token_is_carried_through_as_the_api_key() -> None:
    """RHOAI's kube-rbac-proxy wants `Authorization: Bearer <token>`, which is
    exactly what LiteLLM does with `api_key`."""
    assert rhoai.litellm_credentials(_stored())["api_key"] == TOKEN


def test_the_tls_setting_is_kept_off_the_wire() -> None:
    """LiteLLM reads `ssl_verify` for TLS and, on the hosted_vllm chat path, also
    copies it into the request body. `additional_drop_params` is how the bag
    tells LiteLLM to strip it again."""
    credentials = rhoai.litellm_credentials(_stored(ssl_verify="false"))

    assert credentials["ssl_verify"] is False
    assert "ssl_verify" in credentials["additional_drop_params"]


@pytest.mark.asyncio
async def test_litellm_does_not_leak_the_tls_setting_into_the_request_body() -> None:
    """The real thing, against a local OpenAI-compatible stub: found with a
    capturing proxy in front of a live cluster, where the body arrived as
    `{"model": ..., "messages": ..., "ssl_verify": false}`. vLLM ignored it; a
    stricter server would not."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import litellm

    bodies: list[dict[str, Any]] = []

    class _Stub(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            bodies.append(body)
            if self.path.endswith("/embeddings"):
                reply = {
                    "object": "list",
                    "model": body["model"],
                    "data": [{"index": 0, "object": "embedding", "embedding": [0.0] * 4}],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                }
            else:
                reply = {
                    "id": "chatcmpl-stub",
                    "object": "chat.completion",
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "ok"},
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            raw = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        stored = _stored(api_base=base, embedding_api_base=base, ssl_verify="false")
        await litellm.acompletion(
            model=f"hosted_vllm/{CHAT_MODEL}",
            messages=[{"role": "user", "content": "hi"}],
            drop_params=True,
            **rhoai.litellm_credentials(stored, kind="chat"),
        )
        await litellm.aembedding(
            model=f"hosted_vllm/{EMBED_MODEL}",
            input=["hi"],
            **rhoai.litellm_credentials(stored, kind="embedding"),
        )
    finally:
        server.shutdown()

    assert len(bodies) == 2
    for body in bodies:
        assert "ssl_verify" not in body
        assert "additional_drop_params" not in body
        assert "embedding_api_base" not in body


# ---------------------------------------------------------------------------
# Endpoint URL normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given, expected",
    [
        # `oc get svc` prints an address with no path; pasting it is the common case.
        ("https://chat.svc:8443", "https://chat.svc:8443/v1"),
        ("https://chat.svc:8443/", "https://chat.svc:8443/v1"),
        ("https://chat.svc:8443/v1", "https://chat.svc:8443/v1"),
        ("https://chat.svc:8443/v1/", "https://chat.svc:8443/v1"),
        # An endpoint behind a path-routing proxy keeps its prefix.
        ("https://gw.example.com/openrag/v1", "https://gw.example.com/openrag/v1"),
        ("", ""),
        (None, ""),
    ],
)
def test_the_openai_path_is_added_but_never_doubled(given, expected) -> None:
    assert rhoai.normalized_api_base(given) == expected


def test_a_pasted_service_address_still_reaches_the_models_route() -> None:
    assert rhoai.models_url("https://chat.svc:8443") == "https://chat.svc:8443/v1/models"


# ---------------------------------------------------------------------------
# TLS
# ---------------------------------------------------------------------------


def test_no_ca_configured_verifies_normally() -> None:
    assert rhoai.resolve_ssl_verify("") is True
    assert rhoai.resolve_ssl_verify(None) is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off", " FALSE "])
def test_verification_can_be_turned_off_for_a_port_forward(value) -> None:
    assert rhoai.resolve_ssl_verify(value) is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on"])
def test_an_explicit_true_verifies_normally(value) -> None:
    assert rhoai.resolve_ssl_verify(value) is True


def test_a_ca_bundle_path_is_passed_through(tmp_path) -> None:
    ca = tmp_path / "service-ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")

    assert rhoai.resolve_ssl_verify(str(ca)) == str(ca)


def _recorded_warnings(monkeypatch) -> list[str]:
    """Warnings the module emits. Read off the module logger rather than caplog:
    logging goes through structlog here, which does not route to caplog's handler.
    """
    messages: list[str] = []

    class _Recorder:
        def warning(self, message, **fields):
            messages.append(message)

        def __getattr__(self, _name):
            return lambda *args, **kwargs: None

    monkeypatch.setattr(rhoai, "logger", _Recorder())
    return messages


def test_a_missing_ca_path_is_warned_about_and_still_used(monkeypatch) -> None:
    """Falling back to the system trust store would verify against roots the
    operator never asked for, and succeed — hiding the misconfiguration. Better
    to fail on the missing file.
    """
    warnings = _recorded_warnings(monkeypatch)
    missing = "/no/such/service-ca.crt"

    assert rhoai.resolve_ssl_verify(missing) == missing
    assert any("CA bundle path does not exist" in message for message in warnings)


def test_the_disabled_tls_warning_is_not_repeated_per_request(monkeypatch) -> None:
    """`litellm_credentials` runs on every chat message and every embedded chunk."""
    warnings = _recorded_warnings(monkeypatch)

    for _ in range(5):
        rhoai.resolve_ssl_verify("false")

    disabled = [m for m in warnings if "TLS verification is disabled" in m]
    assert len(disabled) == 1


def test_the_tls_setting_rides_in_the_credential_bag(tmp_path) -> None:
    """Per-provider, unlike SSL_CERT_FILE, which would replace certifi's roots
    process-wide and break every public provider in the same deployment."""
    ca = tmp_path / "service-ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----", encoding="utf-8")

    credentials = rhoai.litellm_credentials(_stored(ssl_verify=str(ca)))

    assert credentials["ssl_verify"] == str(ca)
    assert rhoai.litellm_credentials(_stored(ssl_verify="false"))["ssl_verify"] is False


def test_a_translated_false_is_not_mistaken_for_a_blank() -> None:
    """The health check and model discovery are handed the LiteLLM form by some
    callers, where `ssl_verify` is already a bool. `False` is falsy, and a
    truth-test on the value used to drop it — turning "do not verify" back
    into "verify" for the one setting where that inverts the operator's intent."""
    assert rhoai._values({"ssl_verify": False})["ssl_verify"] == "false"
    assert rhoai._values({"ssl_verify": True})["ssl_verify"] == "true"
    # Not a credential; must not be stringified into one.
    assert "additional_drop_params" not in rhoai._values({"additional_drop_params": ["x"]})


def test_verification_stays_off_when_the_health_check_gets_the_litellm_form() -> None:
    """The regression: `RHOAI_TLS_VERIFY=false` for a port-forward, and the
    pre-save check verifying anyway while real traffic did not."""
    translated = rhoai.litellm_credentials(_stored(ssl_verify="false"), kind="chat")

    assert translated["ssl_verify"] is False
    assert rhoai.ssl_verify_for(translated) is False


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_it_routes_as_hosted_vllm() -> None:
    """`rhoai/<model>` is not a prefix LiteLLM can resolve. `hosted_vllm` is
    chosen over `openai_like` because only it threads a per-call `ssl_verify` —
    see the module docstring.
    """
    assert model_catalog.litellm_provider_key(PROVIDER) == "hosted_vllm"
    assert rhoai.LITELLM_PROVIDER == "hosted_vllm"


def test_an_alias_is_a_provider_the_gateway_can_resolve() -> None:
    assert model_catalog.is_known_provider(PROVIDER)


def test_its_model_ids_carry_the_openrag_provider_tag() -> None:
    assert split_model_id(f"{PROVIDER}:{CHAT_MODEL}") == (PROVIDER, CHAT_MODEL)
    assert model_catalog.public_model_id(PROVIDER, CHAT_MODEL) == f"{PROVIDER}:{CHAT_MODEL}"


def test_a_chat_call_resolves_to_the_chat_endpoint() -> None:
    config = _config(_providers(**_stored()))

    litellm_model, provider, credentials = resolve_call(
        f"{PROVIDER}:{CHAT_MODEL}", kind="chat", config=config
    )

    assert litellm_model == f"hosted_vllm/{CHAT_MODEL}"
    assert provider == PROVIDER
    assert credentials["api_base"] == CHAT_BASE


def test_an_embedding_call_resolves_to_the_embedding_endpoint() -> None:
    """End to end through the gateway: the kind has to survive `resolve_call`,
    `provider_credentials` and `credential_values` to get here."""
    config = _config(_providers(**_stored()))

    litellm_model, provider, credentials = resolve_call(
        f"{PROVIDER}:{EMBED_MODEL}", kind="embedding", config=config
    )

    assert litellm_model == f"hosted_vllm/{EMBED_MODEL}"
    assert provider == PROVIDER
    assert credentials["api_base"] == EMBED_BASE


def _config(providers: ProvidersConfig):
    from types import SimpleNamespace

    return SimpleNamespace(
        providers=providers,
        agent=SimpleNamespace(llm_provider=PROVIDER, llm_model=CHAT_MODEL),
        knowledge=SimpleNamespace(
            embedding_provider=PROVIDER,
            embedding_model=EMBED_MODEL,
            legacy_embedding_provider_map={},
        ),
    )


def test_credential_values_narrows_to_the_requested_endpoint() -> None:
    providers = _providers(**_stored())

    assert providers.credential_values(PROVIDER, kind="chat")["api_base"] == CHAT_BASE
    assert providers.credential_values(PROVIDER, kind="embedding")["api_base"] == EMBED_BASE


def test_stored_credentials_keeps_both_endpoints() -> None:
    """Model discovery has to see both, which the narrowed form cannot give it."""
    stored = _providers(**_stored()).stored_credentials(PROVIDER)

    assert stored["api_base"] == CHAT_BASE
    assert stored["embedding_api_base"] == EMBED_BASE


def test_a_config_object_that_predates_kinds_is_still_callable() -> None:
    """The gateway and the health endpoint accept any object exposing
    `credential_values`; passing a keyword it does not declare is a TypeError
    that would surface as an unhealthy provider."""

    class _OldConfig:
        def credential_values(self, provider):
            return {"api_key": "legacy"}

    assert credential_values_for_kind(_OldConfig(), "openai", "embedding") == {"api_key": "legacy"}


def test_a_kindless_enhancement_is_still_callable() -> None:
    """watsonx.ai on-prem reaches one API and takes the one-argument form."""
    onprem = registry.get("watsonx_onprem")
    credentials = registry.credentials_for(
        onprem,
        {"api_base": "https://cpd.example.com", "username": "u", "api_key": "k"},
        "embedding",
    )

    assert credentials["api_base"] == "https://cpd.example.com"


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


def _models_body(*ids: str) -> dict[str, Any]:
    return {"object": "list", "data": [{"id": model, "object": "model"} for model in ids]}


def _client_returning(responses: dict[str, Any], seen: dict[str, Any] | None = None):
    """An httpx.AsyncClient stand-in that answers per URL."""

    class _Client:
        def __init__(self, **kwargs):
            if seen is not None:
                seen["verify"] = kwargs.get("verify")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, **kwargs):
            if seen is not None:
                seen.setdefault("urls", []).append(url)
                seen["headers"] = kwargs.get("headers")
            answer = responses[url]
            if isinstance(answer, Exception):
                raise answer
            return answer

    return _Client


@pytest.mark.asyncio
async def test_each_endpoint_is_asked_what_it_serves(monkeypatch) -> None:
    """Chat and embedding are told apart by which endpoint answered, so no
    capability sniffing is needed and the split cannot be wrong."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
                f"{EMBED_BASE}/models": _Response(200, _models_body(EMBED_MODEL)),
            },
            seen,
        ),
    )

    models = await rhoai.fetch_models(_stored())

    assert models.chat == (CHAT_MODEL,)
    assert models.embedding == (EMBED_MODEL,)
    assert seen["urls"] == [f"{CHAT_BASE}/models", f"{EMBED_BASE}/models"]
    assert seen["headers"]["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.asyncio
async def test_one_endpoint_is_asked_once_and_fills_both_pickers(monkeypatch) -> None:
    """`GET /v1/models` does not say what a model is for. Emptying a picker on a
    guess is worse than offering an id that fails loudly if misused."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning({f"{CHAT_BASE}/models": _Response(200, _models_body("solo"))}, seen),
    )

    models = await rhoai.fetch_models(_stored(embedding_api_base=None))

    assert models.chat == ("solo",)
    assert models.embedding == ("solo",)
    assert seen["urls"] == [f"{CHAT_BASE}/models"]


@pytest.mark.asyncio
async def test_the_configured_tls_setting_is_used_for_discovery_too(monkeypatch) -> None:
    """Discovery talks to the endpoint directly, not through LiteLLM, so without
    this it could fail on a certificate the gateway accepts, or the reverse."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
                f"{EMBED_BASE}/models": _Response(200, _models_body(EMBED_MODEL)),
            },
            seen,
        ),
    )

    await rhoai.fetch_models(_stored(ssl_verify="false"))

    assert seen["verify"] is False


@pytest.mark.asyncio
async def test_one_dead_endpoint_does_not_empty_the_other_picker(monkeypatch) -> None:
    """A rolling embedding deployment must not take the chat picker with it."""
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
                f"{EMBED_BASE}/models": _Response(503, None, "Service Unavailable"),
            }
        ),
    )
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)

    models = await rhoai.fetch_models(_stored())

    assert models.chat == (CHAT_MODEL,)
    assert models.embedding is None  # that half keeps its configured fallback


@pytest.mark.asyncio
async def test_a_dead_endpoint_does_not_empty_its_own_picker_either(monkeypatch) -> None:
    """The failed half is None, not an empty list, so the catalogue keeps the
    configured rows for it rather than showing nothing for five minutes."""
    responses = {
        f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
        f"{EMBED_BASE}/models": _Response(503, None, "Service Unavailable"),
    }
    monkeypatch.setattr("httpx.AsyncClient", _client_returning(responses))
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)

    await rhoai.fetch_models(_stored())

    assert rhoai.cached_models() == rhoai.ClusterModels(chat=(CHAT_MODEL,), embedding=None)


@pytest.mark.asyncio
async def test_a_failed_listing_keeps_the_previous_answer_for_that_half(monkeypatch) -> None:
    """An endpoint mid-rollout answered fine a minute ago; that answer is
    better than the configured guess, so it stays until it ages out."""
    seen: dict[str, Any] = {}
    responses = {
        f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
        f"{EMBED_BASE}/models": _Response(200, _models_body(EMBED_MODEL)),
    }
    monkeypatch.setattr("httpx.AsyncClient", _client_returning(responses, seen))
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)
    await rhoai.fetch_models(_stored())

    # The embedding answer ages out; the endpoint is then down.
    rhoai._models_cache["embedding"] = rhoai._models_cache["embedding"]._replace(
        at=time.monotonic() - rhoai.MODELS_TTL_SECONDS - 1
    )
    responses[f"{EMBED_BASE}/models"] = _Response(503, None, "Service Unavailable")
    models = await rhoai.fetch_models(_stored())

    assert models == rhoai.ClusterModels(chat=(CHAT_MODEL,), embedding=None)
    # Only the stale half was asked again; the fresh chat answer was reused.
    assert seen["urls"] == [f"{CHAT_BASE}/models", f"{EMBED_BASE}/models", f"{EMBED_BASE}/models"]


@pytest.mark.asyncio
async def test_a_failed_half_is_asked_again_next_time(monkeypatch) -> None:
    """A failure must not be parked behind a fresh timestamp: the next refresh
    tries that endpoint again, and a recovered answer fills the picker."""
    seen: dict[str, Any] = {}
    responses = {
        f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
        f"{EMBED_BASE}/models": _Response(503, None, "Service Unavailable"),
    }
    monkeypatch.setattr("httpx.AsyncClient", _client_returning(responses, seen))
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)
    await rhoai.fetch_models(_stored())

    responses[f"{EMBED_BASE}/models"] = _Response(200, _models_body(EMBED_MODEL))
    models = await rhoai.fetch_models(_stored())

    assert models == rhoai.ClusterModels(chat=(CHAT_MODEL,), embedding=(EMBED_MODEL,))
    assert seen["urls"] == [f"{CHAT_BASE}/models", f"{EMBED_BASE}/models", f"{EMBED_BASE}/models"]


async def _no_retry(method, url, *, client, **kwargs):
    """Skip the backoff so a failure test does not sleep."""
    return await client.request(method, url, **kwargs)


@pytest.mark.asyncio
async def test_an_unreachable_cluster_keeps_the_configured_fallback(monkeypatch) -> None:
    """Returning None leaves whatever the catalogue had; raising would fail the
    whole catalogue request because one endpoint is down."""
    import httpx

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": httpx.ConnectError("no route to host"),
                f"{EMBED_BASE}/models": httpx.ConnectError("no route to host"),
            }
        ),
    )
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)

    assert await rhoai.fetch_models(_stored()) is None


@pytest.mark.asyncio
async def test_a_listing_that_cannot_be_read_keeps_the_fallback(monkeypatch) -> None:
    """A proxy answering with an HTML error page must not put garbage in a picker."""
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, None, "<html>gateway timeout</html>"),
                f"{EMBED_BASE}/models": _Response(200, {"unexpected": "shape"}),
            }
        ),
    )

    assert await rhoai.fetch_models(_stored()) is None


@pytest.mark.asyncio
async def test_incomplete_credentials_are_not_taken_to_the_network(monkeypatch) -> None:
    def _explode(**kwargs):
        raise AssertionError("no HTTP call should be made")

    monkeypatch.setattr("httpx.AsyncClient", _explode)

    assert await rhoai.fetch_models({"api_key": TOKEN}) is None
    assert await rhoai.fetch_models({"api_base": CHAT_BASE}) is None


@pytest.mark.parametrize(
    "body, expected",
    [
        (_models_body("a", "b"), ("a", "b")),
        # Order preserved, duplicates dropped.
        (_models_body("a", "b", "a"), ("a", "b")),
        ({"object": "list", "data": []}, ()),
        ({"object": "list", "data": [{"no": "id"}, {"id": "  "}, "junk"]}, ()),
        ({"error": {"message": "nope"}}, ()),
        ("not a mapping", ()),
        (None, ()),
    ],
)
def test_only_well_formed_model_entries_are_kept(body, expected) -> None:
    assert rhoai.model_ids(body) == expected


@pytest.mark.asyncio
async def test_a_fresh_listing_is_reused_rather_than_refetched(monkeypatch) -> None:
    """The set of served models changes when an administrator deploys one, not
    once per catalogue request."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
                f"{EMBED_BASE}/models": _Response(200, _models_body(EMBED_MODEL)),
            },
            seen,
        ),
    )

    await rhoai.fetch_models(_stored())
    await rhoai.fetch_models(_stored())

    assert len(seen["urls"]) == 2  # one round, not two
    assert rhoai.cached_models().chat == (CHAT_MODEL,)


@pytest.mark.asyncio
async def test_changing_an_endpoint_invalidates_the_cache(monkeypatch) -> None:
    """A cached list belongs to the endpoints and token it was fetched with."""
    other = "https://other-chat.svc:8443/v1"
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
                f"{EMBED_BASE}/models": _Response(200, _models_body(EMBED_MODEL)),
                f"{other}/models": _Response(200, _models_body("other-model")),
            },
            seen,
        ),
    )

    await rhoai.fetch_models(_stored())
    models = await rhoai.fetch_models(_stored(api_base=other))

    assert models.chat == ("other-model",)


@pytest.mark.asyncio
async def test_forget_models_drops_the_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
                f"{EMBED_BASE}/models": _Response(200, _models_body(EMBED_MODEL)),
            }
        ),
    )

    await rhoai.fetch_models(_stored())
    assert rhoai.cached_models() is not None

    rhoai.forget_models()
    assert rhoai.cached_models() is None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_healthy_deployment_passes_with_no_model_selected(monkeypatch) -> None:
    """`GET /v1/models` needs no model and bills no tokens, which is what makes
    it a check the provider can pass during onboarding."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
                f"{EMBED_BASE}/models": _Response(200, _models_body(EMBED_MODEL)),
            },
            seen,
        ),
    )

    await rhoai.lightweight_health_check(_stored())

    assert seen["urls"] == [f"{CHAT_BASE}/models", f"{EMBED_BASE}/models"]


@pytest.mark.asyncio
async def test_the_litellm_form_still_checks_with_the_configured_tls_setting(monkeypatch) -> None:
    """Handed the narrowed bag, the check covers the one endpoint in it — but
    with the TLS setting the operator chose, not verification switched back on."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning({f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL))}, seen),
    )
    translated = rhoai.litellm_credentials(_stored(ssl_verify="false"), kind="chat")

    await rhoai.lightweight_health_check(translated)

    assert seen["verify"] is False
    assert seen["urls"] == [f"{CHAT_BASE}/models"]


@pytest.mark.asyncio
async def test_validation_hands_the_check_the_stored_form(monkeypatch) -> None:
    """`validate_provider_setup` gets the LiteLLM form for the probe and the
    stored form for the enhancement check; the check must get the latter, or
    the embedding endpoint is never looked at before the first ingest."""
    from api import provider_validation

    received: list[dict[str, Any]] = []

    async def _capture(credentials):
        received.append(dict(credentials))

    monkeypatch.setattr(rhoai, "lightweight_health_check", _capture)
    stored = _stored()
    translated = rhoai.litellm_credentials(stored, kind="chat")

    await provider_validation.validate_provider_setup(
        provider=PROVIDER, credentials=translated, stored_credentials=stored
    )
    await provider_validation.validate_provider_setup(provider=PROVIDER, credentials=translated)

    assert received[0]["embedding_api_base"] == EMBED_BASE
    assert "embedding_api_base" not in received[1]  # no stored form given: falls back


@pytest.mark.asyncio
async def test_a_wrong_embedding_url_is_found_before_the_first_ingest(monkeypatch) -> None:
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body(CHAT_MODEL)),
                f"{EMBED_BASE}/models": _Response(404, {"error": {"message": "Not Found"}}),
            }
        ),
    )
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)

    with pytest.raises(Exception, match="no /v1/models"):
        await rhoai.lightweight_health_check(_stored())


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
async def test_a_rejected_token_names_the_rolebinding(monkeypatch, status) -> None:
    """RHOAI runs a SubjectAccessReview, so the usual cause is a missing grant
    rather than a bad token — and the message has to say so or the operator
    hunts for the wrong thing."""
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {f"{CHAT_BASE}/models": _Response(status, {"error": {"message": "forbidden"}})}
        ),
    )
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)

    with pytest.raises(Exception, match="inferenceservices"):
        await rhoai.lightweight_health_check(_stored())


@pytest.mark.asyncio
async def test_an_unreachable_endpoint_says_which_one(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning({f"{CHAT_BASE}/models": httpx.ConnectError("no route to host")}),
    )
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)

    with pytest.raises(Exception, match="chat endpoint"):
        await rhoai.lightweight_health_check(_stored())


@pytest.mark.asyncio
async def test_a_slow_endpoint_is_reported_as_a_timeout(monkeypatch) -> None:
    import httpx

    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning({f"{CHAT_BASE}/models": httpx.ConnectTimeout("too slow")}),
    )
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)

    with pytest.raises(Exception, match="did not respond in time"):
        await rhoai.lightweight_health_check(_stored())


@pytest.mark.asyncio
async def test_the_whole_check_is_bounded_however_slow_the_endpoints_are(monkeypatch) -> None:
    """Per-request timeouts, retries and backoff across two endpoints add up to
    about a minute; a human is waiting on the settings save, so the check as a
    whole has a deadline of its own."""
    import asyncio

    class _Hanging:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, **kwargs):
            await asyncio.sleep(60)

    monkeypatch.setattr("httpx.AsyncClient", _Hanging)
    monkeypatch.setattr(rhoai, "HEALTH_TOTAL_BUDGET_SECONDS", 0.05)

    with pytest.raises(Exception, match="did not respond in time"):
        await asyncio.wait_for(rhoai.lightweight_health_check(_stored()), timeout=5)


@pytest.mark.asyncio
async def test_the_health_check_retries_less_than_discovery(monkeypatch) -> None:
    """Discovery can afford to wait out a rollout; the pre-save check cannot."""
    calls: list[int] = []

    async def _count(method, url, *, client, max_retries=2, **kwargs):
        calls.append(max_retries)
        return _Response(200, _models_body(CHAT_MODEL))

    monkeypatch.setattr("httpx.AsyncClient", _client_returning({}))
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _count)

    await rhoai.lightweight_health_check(_stored(embedding_api_base=""))

    assert calls == [rhoai.HEALTH_MAX_RETRIES]
    assert rhoai.HEALTH_MAX_RETRIES < 2


@pytest.mark.asyncio
async def test_missing_credentials_say_what_is_missing(monkeypatch) -> None:
    """Distinct messages, because the fix is different: one is a URL, the other
    is an `oc create token`."""

    def _explode(**kwargs):
        raise AssertionError("no HTTP call should be made")

    monkeypatch.setattr("httpx.AsyncClient", _explode)

    with pytest.raises(Exception, match="No chat endpoint"):
        await rhoai.lightweight_health_check({"api_key": TOKEN})

    with pytest.raises(Exception, match="No ServiceAccount token"):
        await rhoai.lightweight_health_check({"api_base": CHAT_BASE})


# ---------------------------------------------------------------------------
# Visibility and the catalogue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("run_mode", ["oss", "on_prem", "saas"])
def test_it_is_hidden_everywhere_as_shipped(monkeypatch, run_mode) -> None:
    """Its endpoints and token are deployment-specific, so it is turned on with
    OPENRAG_MODEL_PROVIDERS_CONFIG rather than offered to everyone."""
    monkeypatch.delenv("OPENRAG_MODEL_PROVIDERS_CONFIG", raising=False)
    monkeypatch.setenv("OPENRAG_RUN_MODE", run_mode)
    model_providers.reload()

    assert PROVIDER not in model_providers.visible_provider_keys()


def test_a_deployment_can_offer_it_with_a_config_override(tmp_path, monkeypatch) -> None:
    _enable_in_oss(tmp_path, monkeypatch)

    assert PROVIDER in model_providers.visible_provider_keys()


def test_the_configured_models_are_the_fallback_picker(tmp_path, monkeypatch) -> None:
    """LiteLLM's bundled table has no hosted_vllm models at all, so without the
    config rows the pickers would be empty until the cluster answers."""
    _enable_in_oss(tmp_path, monkeypatch)

    entry = {e["key"]: e for e in model_catalog.catalog()["providers"]}[PROVIDER]

    assert [m["model"] for m in entry["models"]] == [CHAT_MODEL]
    assert [m["model"] for m in entry["embedding_models"]] == [EMBED_MODEL]
    assert entry["name"] == "Red Hat OpenShift AI"


@pytest.mark.asyncio
async def test_what_the_cluster_serves_wins_over_the_configured_fallback(
    tmp_path, monkeypatch
) -> None:
    """A model the InferenceServices do not serve must not sit in the picker
    waiting to be chosen."""
    _enable_in_oss(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body("deployed-chat")),
                f"{EMBED_BASE}/models": _Response(200, _models_body("deployed-embed")),
            }
        ),
    )
    await rhoai.fetch_models(_stored())

    entry = {e["key"]: e for e in model_catalog.catalog()["providers"]}[PROVIDER]

    assert [m["model"] for m in entry["models"]] == ["deployed-chat"]
    assert [m["model"] for m in entry["embedding_models"]] == ["deployed-embed"]


@pytest.mark.asyncio
async def test_the_picker_for_a_dead_endpoint_keeps_the_configured_fallback(
    tmp_path, monkeypatch
) -> None:
    """One endpoint down empties neither picker: the live answer wins where
    there is one, and the configured rows stand in for the half without."""
    _enable_in_oss(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "httpx.AsyncClient",
        _client_returning(
            {
                f"{CHAT_BASE}/models": _Response(200, _models_body("deployed-chat")),
                f"{EMBED_BASE}/models": _Response(503, None, "Service Unavailable"),
            }
        ),
    )
    monkeypatch.setattr(rhoai, "_http_request_with_retry", _no_retry)
    await rhoai.fetch_models(_stored())

    entry = {e["key"]: e for e in model_catalog.catalog()["providers"]}[PROVIDER]

    assert [m["model"] for m in entry["models"]] == ["deployed-chat"]
    assert [m["model"] for m in entry["embedding_models"]] == [EMBED_MODEL]


@pytest.mark.asyncio
async def test_the_catalogue_refresh_passes_both_endpoints(tmp_path, monkeypatch) -> None:
    """`refresh_live_models` reads the stored form, not the narrowed LiteLLM one:
    the kind-specific bag carries only one endpoint, and discovery needs both."""
    _enable_in_oss(tmp_path, monkeypatch)
    captured: dict[str, Any] = {}

    async def _capture(credentials):
        captured.update(credentials)
        return None

    monkeypatch.setattr(rhoai, "fetch_models", _capture)
    monkeypatch.setattr(
        "config.settings.get_openrag_config", lambda: _config(_providers(**_stored()))
    )

    await model_catalog.refresh_live_models()

    assert captured["api_base"] == CHAT_BASE
    assert captured["embedding_api_base"] == EMBED_BASE
