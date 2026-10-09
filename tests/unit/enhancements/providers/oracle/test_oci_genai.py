"""Oracle OCI Generative AI: LiteLLM's `oci` provider plus a signer for principals."""

import asyncio
import base64
import json
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from api.settings.endpoints import update_settings
from api.settings.helpers import _has_other_configured_provider
from api.settings.models import SettingsUpdateBody
from config import model_providers
from config.config_manager import ConfigManager, OpenAIConfig, OpenRAGConfig
from enhancements.providers import registry
from enhancements.providers.oracle import oci_genai
from services import llm_gateway, model_catalog, provider_error_log
from services.llm_gateway import LlmGatewayError, embeddings, resolve_call
from session_manager import User
from utils import provider_health_cache

REGION = "eu-frankfurt-1"
COMPARTMENT = "ocid1.compartment.oc1..aaaa"
_API_KEY_FIELDS = {
    "oci_user": "ocid1.user.oc1..bbbb",
    "oci_fingerprint": "aa:bb:cc",
    "oci_tenancy": "ocid1.tenancy.oc1..cccc",
}
PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode()
    .strip()
)


class _FakeSigner:
    """Stands in for an SDK signer; real ones refresh through `_reset_signers`."""

    def _reset_signers(self):
        pass


SIGNER = _FakeSigner()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    import utils.encryption

    utils.encryption._cached_master_secret = None
    monkeypatch.setenv(
        "OPENRAG_ENCRYPTION_KEY",
        base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii"),
    )
    oci_genai._signers.clear()
    oci_genai._failures.clear()
    yield
    oci_genai._signers.clear()
    oci_genai._failures.clear()


def _stored(**overrides):
    values = {"oci_region": REGION, "oci_compartment_id": COMPARTMENT, **overrides}
    return {k: v for k, v in values.items() if v is not None}


def _api_key_stored(**overrides):
    return _stored(**{**_API_KEY_FIELDS, "oci_key": PEM, **overrides})


def _config(**credentials) -> OpenRAGConfig:
    config = OpenRAGConfig.from_dict({})
    config.edited = True
    if credentials:
        config.providers.set_credentials("oci", credentials)
    return config


def _fake_signers(monkeypatch, **factories):
    """Replace the SDK signer constructors; `oci` itself is imported for real."""
    import oci.auth.signers as sdk

    for name, factory in factories.items():
        monkeypatch.setattr(sdk, name, factory)


# -- catalogue and form -------------------------------------------------------


def test_it_ships_in_oss_and_on_prem_but_never_in_saas(monkeypatch):
    for mode, visible in (("oss", True), ("on_prem", True), ("saas", False)):
        monkeypatch.setenv("OPENRAG_RUN_MODE", mode)
        assert ("oci" in model_providers.visible_provider_keys()) is visible


def test_only_region_and_compartment_are_required_and_only_the_key_is_encrypted(tmp_path):
    assert model_catalog.required_field_keys("oci") == ["oci_region", "oci_compartment_id"]
    assert model_catalog.secret_field_keys("oci") == {"oci_key"}
    fields = {f["key"]: f for f in model_catalog.credential_fields("oci")}
    assert fields["oci_key"]["field_type"] == "textarea"

    path = tmp_path / "config.yaml"
    manager = ConfigManager(str(path))
    config = manager.get_config()
    config.providers.set_credentials("oci", _api_key_stored())
    manager.save_config_file(config)

    on_disk = yaml.safe_load(path.read_text())["providers"]["custom"]["oci"]["credentials"]
    assert on_disk["oci_key"]["algorithm"] == "AES-256-GCM"
    assert "BEGIN PRIVATE KEY" not in path.read_text()
    reloaded = ConfigManager(str(path)).get_config()
    assert reloaded.providers.stored_credentials("oci")["oci_key"] == PEM


def test_a_principal_with_only_region_and_compartment_is_configured():
    config = _config(oci_auth_method="instance_principal", **_stored())
    assert config.providers.custom["oci"].configured is True


# -- credentials handed to LiteLLM --------------------------------------------


def test_api_key_credentials_are_exactly_litellms_six_and_serializable():
    credentials = oci_genai.litellm_credentials(_api_key_stored(oci_auth_method=""))

    assert set(credentials) == {"oci_region", "oci_compartment_id", "oci_key", *_API_KEY_FIELDS}
    json.dumps(credentials)
    assert oci_genai.litellm_runtime_kwargs(_api_key_stored()) == {}


@pytest.mark.parametrize("method", ["instance_principal", "workload_identity"])
def test_a_principal_never_sends_stale_api_key_fields_or_its_method(monkeypatch, method):
    signer = SIGNER
    _fake_signers(
        monkeypatch,
        InstancePrincipalsSecurityTokenSigner=lambda **_: signer,
        get_oke_workload_identity_resource_principal_signer=lambda **_: signer,
    )
    config = _config(**_api_key_stored())
    config.providers.set_credentials("oci", {"oci_auth_method": method})

    credentials = config.providers.credential_values("oci")
    assert credentials == {"oci_region": REGION, "oci_compartment_id": COMPARTMENT}
    json.dumps(credentials)

    stored = config.providers.stored_credentials("oci")
    kwargs = registry.runtime_kwargs_for(registry.get("oci"), stored)
    assert kwargs == {"oci_signer": signer}
    # The signer is a runtime kwarg only: never stored or part of the credentials.
    assert "oci_signer" not in stored
    assert "oci_signer" not in credentials


def test_resolve_call_carries_region_and_compartment_per_call():
    config = _config(**_api_key_stored())
    model, provider, credentials = resolve_call(
        "oci:cohere.embed-english-v3.0", kind="embedding", config=config
    )
    assert (model, provider) == ("oci/cohere.embed-english-v3.0", "oci")
    assert credentials["oci_region"] == REGION
    assert "oci_auth_method" not in credentials


# -- validation ---------------------------------------------------------------


def test_an_unknown_auth_method_is_a_clear_value_error():
    with pytest.raises(ValueError, match="Unknown OCI auth method 'kerberos'.*api_key"):
        oci_genai.litellm_credentials(_stored(oci_auth_method="kerberos"))


@pytest.mark.asyncio
async def test_health_check_rejects_an_unknown_method_and_missing_fields():
    with pytest.raises(ValueError, match="Unknown OCI auth method"):
        await oci_genai.lightweight_health_check(_stored(oci_auth_method="nope"))
    with pytest.raises(ValueError, match="oci_fingerprint.*oci_key.*oci_tenancy.*oci_user"):
        await oci_genai.lightweight_health_check(_stored())


@pytest.mark.asyncio
async def test_health_check_validates_the_pem_locally():
    await oci_genai.lightweight_health_check(_api_key_stored())
    # A single-line paste with literal "\n" is accepted, as LiteLLM accepts it.
    await oci_genai.lightweight_health_check(_api_key_stored(oci_key=PEM.replace("\n", "\\n")))
    with pytest.raises(ValueError, match="not a valid unencrypted RSA PEM") as caught:
        await oci_genai.lightweight_health_check(_api_key_stored(oci_key="not-a-key-xyz"))
    assert "not-a-key-xyz" not in str(caught.value)


@pytest.mark.asyncio
async def test_health_check_rejects_a_non_rsa_key_litellm_cannot_sign_with():
    from cryptography.hazmat.primitives.asymmetric import ec

    ec_pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    with pytest.raises(ValueError, match="RSA PEM"):
        await oci_genai.lightweight_health_check(_api_key_stored(oci_key=ec_pem))


def test_the_auth_method_is_case_insensitive():
    assert oci_genai.litellm_credentials(_stored(oci_auth_method="Instance_Principal")) == _stored()


@pytest.mark.asyncio
async def test_health_check_builds_the_signer_for_a_principal(monkeypatch):
    built = []
    _fake_signers(
        monkeypatch, InstancePrincipalsSecurityTokenSigner=lambda **_: built.append(1) or "s"
    )

    await oci_genai.lightweight_health_check(_stored(oci_auth_method="instance_principal"))

    assert built == [1]


# -- signer lifecycle ---------------------------------------------------------


def test_signer_success_is_cached_and_a_failure_only_for_a_short_while(monkeypatch):
    calls = []

    def flaky(**_):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("IMDS unreachable")
        return SIGNER

    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=flaky)
    stored = _stored(oci_auth_method="instance_principal")

    with pytest.raises(ValueError, match="instance_principal signer.*dynamic-group"):
        oci_genai.litellm_runtime_kwargs(stored)
    # Remembered: repeated requests do not each pay the SDK's network attempts.
    with pytest.raises(ValueError, match="instance_principal signer"):
        oci_genai.litellm_runtime_kwargs(stored)
    assert len(calls) == 1

    monkeypatch.setattr(oci_genai, "_FAILURE_TTL_SECONDS", 0)
    assert oci_genai.litellm_runtime_kwargs(stored) == {"oci_signer": SIGNER}
    assert oci_genai.litellm_runtime_kwargs(stored) == {"oci_signer": SIGNER}
    assert len(calls) == 2


def test_the_sdk_is_given_a_bounded_retry_strategy(monkeypatch):
    seen: dict = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return SIGNER

    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=capture)
    oci_genai.litellm_runtime_kwargs(_stored(oci_auth_method="instance_principal"))

    assert seen["retry_strategy"] is seen["federation_client_retry_strategy"]
    checkers = {type(c).__name__: c for c in seen["retry_strategy"].checkers.checkers}
    assert checkers["LimitBasedRetryChecker"].max_attempts == 2
    assert checkers["TotalTimeExceededRetryChecker"].time_limit_seconds <= 10


def test_concurrent_callers_fail_fast_while_the_signer_is_being_built(monkeypatch):
    building, release = threading.Event(), threading.Event()
    calls = []

    def slow(**_):
        calls.append(1)
        building.set()
        release.wait(5)
        return SIGNER

    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=slow)
    stored = _stored(oci_auth_method="instance_principal")
    first = threading.Thread(target=oci_genai.litellm_runtime_kwargs, args=(stored,))
    first.start()
    assert building.wait(5)

    started = time.monotonic()
    for _ in range(5):
        with pytest.raises(ValueError, match="still being set up"):
            oci_genai.litellm_runtime_kwargs(stored)
    assert time.monotonic() - started < 1

    release.set()
    first.join()
    assert oci_genai.litellm_runtime_kwargs(stored) == {"oci_signer": SIGNER}
    assert len(calls) == 1


def _federation_signer():
    """A real SDK instance principal signer over a federation client we can 'expire'."""
    from oci.auth.signers.security_token_signer import X509FederationClientBasedSecurityTokenSigner

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    federation = MagicMock()
    federation.get_security_token.return_value = "TOKEN-1"
    federation.session_key_supplier.get_key_pair.return_value = {"private": key}
    return federation, X509FederationClientBasedSecurityTokenSigner(federation)


def _signed_token(signer):
    from litellm.llms.oci.common_utils import sign_with_oci_signer

    headers, _ = sign_with_oci_signer(
        {}, {"oci_signer": signer}, {"x": 1}, "https://inference.generativeai.example/embedText"
    )
    return headers["authorization"].split('keyId="')[1].split('"')[0]


def test_a_cached_principal_signer_is_refreshed_before_each_use(monkeypatch):
    federation, signer = _federation_signer()
    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=lambda **_: signer)
    stored = _stored(oci_auth_method="instance_principal")

    handed_over = oci_genai.litellm_runtime_kwargs(stored)["oci_signer"]
    assert _signed_token(handed_over).endswith("TOKEN-1")

    federation.get_security_token.return_value = "TOKEN-2"  # the token expired and was renewed
    handed_over = oci_genai.litellm_runtime_kwargs(stored)["oci_signer"]

    assert handed_over is signer
    assert _signed_token(handed_over).endswith("TOKEN-2")


def test_a_workload_identity_signer_is_asked_for_a_valid_token(monkeypatch):
    signer = MagicMock()
    _fake_signers(
        monkeypatch, get_oke_workload_identity_resource_principal_signer=lambda **_: signer
    )

    oci_genai.litellm_runtime_kwargs(_stored(oci_auth_method="workload_identity"))

    signer.get_security_token.assert_called_once_with()


def test_a_failed_token_refresh_is_a_curated_error_without_the_detail(monkeypatch):
    federation, signer = _federation_signer()
    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=lambda **_: signer)
    stored = _stored(oci_auth_method="instance_principal")
    oci_genai.litellm_runtime_kwargs(stored)
    federation.get_security_token.side_effect = RuntimeError("secret-detail 10.0.0.1")

    with pytest.raises(ValueError, match="refresh the OCI instance_principal") as caught:
        oci_genai.litellm_runtime_kwargs(stored)

    assert "secret-detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_a_slow_signer_does_not_stall_the_event_loop(monkeypatch):
    def slow_failure(**_):
        time.sleep(0.5)
        raise RuntimeError("IMDS unreachable")

    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=slow_failure)
    config = _config(oci_auth_method="instance_principal", **_stored())
    gaps: list[float] = []

    async def ticker():
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.02)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0.05)
    with pytest.raises(LlmGatewayError):
        await embeddings({"model": "oci:cohere.embed-english-v3.0", "input": ["q"]}, config=config)
    # Let the ticker resume once, so a blocked loop shows up as a long gap.
    await asyncio.sleep(0.05)
    task.cancel()

    assert max(gaps) < 0.25


@pytest.mark.asyncio
async def test_a_signer_failure_is_a_clean_503_through_the_gateway(monkeypatch):
    def broken():
        raise RuntimeError("secret-detail 10.0.0.1")

    _fake_signers(
        monkeypatch,
        get_oke_workload_identity_resource_principal_signer=lambda **_: broken(),
    )
    config = _config(oci_auth_method="workload_identity", **_stored())
    provider_error_log.clear()

    with pytest.raises(LlmGatewayError) as caught:
        await embeddings({"model": "oci:cohere.embed-english-v3.0", "input": ["q"]}, config=config)

    assert caught.value.status_code == 503
    assert "workload identity" in caught.value.message.lower()
    assert "secret-detail" not in caught.value.message
    assert provider_error_log.latest_failure("oci", "embedding") == caught.value.message


@pytest.mark.asyncio
async def test_the_gateway_forwards_input_type_and_signer_to_litellm(monkeypatch):
    captured = {}

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return {"data": [{"embedding": [0.1], "index": 0}]}

    monkeypatch.setattr("litellm.aembedding", fake_aembedding)
    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=lambda **_: SIGNER)
    config = _config(oci_auth_method="instance_principal", **_stored())

    await embeddings(
        {"model": "oci:cohere.embed-english-v3.0", "input": ["q"]}, config=config, interactive=True
    )

    assert captured["oci_signer"] == SIGNER
    assert captured["input_type"] == "search_query"
    assert captured["oci_region"] == REGION
    assert "oci_auth_method" not in captured
    assert llm_gateway.max_embedding_input_tokens("oci:cohere.embed-english-v3.0") == 512


@pytest.mark.asyncio
async def test_the_chat_path_carries_the_signer_too(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=lambda **_: SIGNER)
    config = _config(oci_auth_method="instance_principal", **_stored())

    await llm_gateway.chat_completions(
        {"model": "oci:cohere.command-r-08-2024", "messages": [{"role": "user", "content": "hi"}]},
        config=config,
    )

    assert captured["oci_signer"] == SIGNER
    assert captured["oci_region"] == REGION
    assert "oci_auth_method" not in captured


# -- settings save, removal, health cache -------------------------------------


async def _save(config, body):
    rbac = MagicMock()
    rbac.has_permission = AsyncMock(return_value=True)
    with (
        patch("api.settings.endpoints.get_openrag_config", return_value=config),
        patch("api.settings.endpoints.config_manager.save_config_file", return_value=True) as save,
        patch("api.settings.endpoints.clients.refresh_patched_client", new_callable=AsyncMock),
        patch(
            "api.settings.endpoints._run_async_post_save_langflow_updates", new_callable=AsyncMock
        ),
    ):
        response = await update_settings(
            body=body,
            session_manager=AsyncMock(),
            user=MagicMock(spec=User),
            models_service=MagicMock(),
            rbac=rbac,
        )
    return response, save


@pytest.mark.asyncio
async def test_a_save_with_an_unknown_auth_method_is_a_400_and_nothing_is_saved():
    config = _config(**_stored())
    body = SettingsUpdateBody(provider_credentials={"oci": {"oci_auth_method": "kerberos"}})

    response, save = await _save(config, body)

    assert response.status_code == 400
    assert b"Unknown OCI auth method" in response.body
    save.assert_not_called()


@pytest.mark.asyncio
async def test_a_bad_pem_is_rejected_even_when_the_stored_key_is_valid():
    config = _config(**_api_key_stored())
    body = SettingsUpdateBody(provider_credentials={"oci": {"oci_key": "leaky-not-a-key"}})

    response, save = await _save(config, body)

    assert response.status_code == 400
    assert b"leaky-not-a-key" not in response.body
    save.assert_not_called()


@pytest.mark.asyncio
async def test_a_good_pem_fixes_a_bad_stored_one():
    config = _config(**_api_key_stored(oci_key="stale-not-a-key"))
    body = SettingsUpdateBody(provider_credentials={"oci": {"oci_key": PEM}})

    response, save = await _save(config, body)

    assert getattr(response, "status_code", 200) == 200
    assert save.call_args.args[0].providers.stored_credentials("oci")["oci_key"] == PEM


@pytest.mark.asyncio
async def test_a_principal_save_builds_the_signer_and_is_stored(monkeypatch):
    built = []
    _fake_signers(
        monkeypatch, InstancePrincipalsSecurityTokenSigner=lambda **_: built.append(1) or "s"
    )
    config = _config(**_stored())
    body = SettingsUpdateBody(
        provider_credentials={"oci": {"oci_auth_method": "instance_principal"}}
    )

    response, save = await _save(config, body)

    assert getattr(response, "status_code", 200) == 200
    assert built == [1]
    assert save.call_args.args[0].providers.stored_credentials("oci")["oci_auth_method"] == (
        "instance_principal"
    )


@pytest.mark.asyncio
async def test_the_model_probe_on_save_uses_the_pending_credentials(monkeypatch):
    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=lambda **_: SIGNER)
    probe = AsyncMock()
    monkeypatch.setattr("api.provider_validation._test_litellm_provider", probe)
    config = _config(**_api_key_stored())
    body = SettingsUpdateBody(
        embedding_provider="oci",
        embedding_model="cohere.embed-english-v3.0",
        provider_credentials={"oci": {"oci_auth_method": "instance_principal"}},
    )

    response, _ = await _save(config, body)

    assert getattr(response, "status_code", 200) == 200
    kwargs = probe.call_args.kwargs
    # Validated as the principal it is about to become, not the stored API key.
    assert kwargs["runtime_kwargs"] == {"oci_signer": SIGNER}
    assert "oci_key" not in kwargs["credentials"]


@pytest.mark.asyncio
async def test_removing_oci_deletes_it_and_falls_back():
    config = _config(**_api_key_stored())
    config.providers.openai = OpenAIConfig(api_key="sk-test", configured=True)
    config.knowledge.embedding_provider = "oci"
    config.knowledge.embedding_model = "cohere.embed-english-v3.0"

    response, save = await _save(config, SettingsUpdateBody(remove_provider_config="oci"))

    assert getattr(response, "status_code", 200) == 200
    saved = save.call_args.args[0]
    assert "oci" not in saved.providers.custom
    assert saved.knowledge.embedding_provider == "openai"


def test_oci_alone_counts_as_another_configured_provider():
    config = _config(**_api_key_stored())
    assert _has_other_configured_provider(config, "openai") is True
    assert _has_other_configured_provider(config, "oci") is False


def test_rotating_the_key_busts_the_health_cache():
    config = _config(**_api_key_stored())

    def key():
        return provider_health_cache.cache_key(
            "oci",
            "oci",
            False,
            "",
            "",
            None,
            None,
            None,
            credentials=config.providers.credential_values("oci"),
        )

    before = key()
    config.providers.set_credentials("oci", {"oci_key": "rotated-key-material"})

    assert key() != before
    assert "rotated-key-material" not in key()


@pytest.mark.asyncio
async def test_ingest_error_probes_see_the_principal_not_missing_api_keys(monkeypatch):
    from api import provider_validation

    _fake_signers(monkeypatch, InstancePrincipalsSecurityTokenSigner=lambda **_: SIGNER)
    probe = AsyncMock()
    monkeypatch.setattr("api.provider_validation._test_litellm_provider", probe)
    config = _config(oci_auth_method="instance_principal", **_stored())
    config.knowledge.embedding_provider = "oci"
    config.knowledge.embedding_model = "cohere.embed-english-v3.0"
    monkeypatch.setattr("config.settings.get_openrag_config", lambda: config)

    assert await provider_validation.probe_embedding_error() is None
    assert probe.call_args.kwargs["runtime_kwargs"] == {"oci_signer": SIGNER}

    probe.reset_mock()
    config.agent.llm_provider = "oci"
    config.agent.llm_model = "cohere.command-r-08-2024"
    assert await provider_validation.probe_chat_llm_error() is None
    assert probe.call_args.kwargs["runtime_kwargs"] == {"oci_signer": SIGNER}

    probe.reset_mock()
    assert await provider_validation.probe_provider_credential_error() is None
