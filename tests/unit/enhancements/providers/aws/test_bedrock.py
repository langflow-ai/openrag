"""Amazon Bedrock: a LiteLLM provider plus a small form and health-check enhancement."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from botocore.exceptions import ClientError, NoCredentialsError

from api.settings.endpoints import update_settings
from api.settings.helpers import _has_other_configured_provider
from api.settings.models import SettingsUpdateBody
from config import model_providers
from config.config_manager import ConfigManager, OpenAIConfig, OpenRAGConfig
from enhancements.providers.aws import bedrock
from services import model_catalog
from services.llm_gateway import resolve_call
from session_manager import User
from utils import provider_health_cache

SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
REGION = "eu-central-1"


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    import utils.encryption

    utils.encryption._cached_master_secret = None
    monkeypatch.setenv(
        "OPENRAG_ENCRYPTION_KEY",
        base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii"),
    )


def _config(**credentials) -> OpenRAGConfig:
    config = OpenRAGConfig.from_dict({})
    config.edited = True
    if credentials:
        config.providers.set_credentials("bedrock", credentials)
    return config


def test_it_ships_in_oss_and_on_prem_but_never_in_saas(monkeypatch):
    for mode, visible in (("oss", True), ("on_prem", True), ("saas", False)):
        monkeypatch.setenv("OPENRAG_RUN_MODE", mode)
        assert ("bedrock" in model_providers.visible_provider_keys()) is visible


def test_the_form_requires_a_region_and_encrypts_the_secrets(tmp_path):
    fields = {f["key"]: f for f in model_catalog.credential_fields("bedrock")}
    assert fields["aws_region_name"]["required"] is True
    assert not any(f["required"] for key, f in fields.items() if key != "aws_region_name")
    assert model_catalog.secret_field_keys("bedrock") == {"aws_secret_access_key"}

    path = tmp_path / "config.yaml"
    manager = ConfigManager(str(path))
    config = manager.get_config()
    config.providers.set_credentials(
        "bedrock",
        {
            "aws_region_name": REGION,
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": SECRET,
        },
    )
    manager.save_config_file(config)

    on_disk = yaml.safe_load(path.read_text())["providers"]["custom"]["bedrock"]["credentials"]
    assert on_disk["aws_region_name"] == REGION
    assert on_disk["aws_secret_access_key"]["algorithm"] == "AES-256-GCM"
    assert SECRET not in path.read_text()
    reloaded = ConfigManager(str(path)).get_config()
    assert reloaded.providers.stored_credentials("bedrock")["aws_secret_access_key"] == SECRET


def test_a_region_alone_counts_as_configured_for_iam_role_deployments():
    assert _config(aws_region_name=REGION).providers.custom["bedrock"].configured is True


def test_keys_without_a_region_are_not_configured():
    config = _config(aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key=SECRET)
    assert config.providers.custom["bedrock"].configured is False


def test_the_region_travels_with_the_call_not_the_environment(monkeypatch):
    monkeypatch.delenv("AWS_REGION_NAME", raising=False)
    config = _config(aws_region_name=REGION)

    model, provider, credentials = resolve_call(
        "bedrock:cohere.embed-v4:0", kind="embedding", config=config
    )

    assert (model, provider) == ("bedrock/cohere.embed-v4:0", "bedrock")
    assert credentials == {"aws_region_name": REGION}


def test_blank_values_never_reach_litellm():
    stored = {
        "aws_region_name": f" {REGION} ",
        "aws_access_key_id": "",
        "aws_secret_access_key": " ",
    }
    assert bedrock.litellm_credentials(stored) == {"aws_region_name": REGION}


def _sts(monkeypatch, *, error=None):
    client = MagicMock()
    if error is not None:
        client.get_caller_identity.side_effect = error
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("boto3.session.Session.client", lambda self, *a, **k: factory(*a, **k))
    return factory, client


@pytest.mark.asyncio
async def test_health_check_calls_sts_with_the_region_and_keys(monkeypatch):
    factory, client = _sts(monkeypatch)

    await bedrock.lightweight_health_check(
        {
            "aws_region_name": REGION,
            "aws_access_key_id": "AKIAEXAMPLE",
            "aws_secret_access_key": SECRET,
        }
    )

    assert factory.call_args.args == ("sts",)
    assert factory.call_args.kwargs["region_name"] == REGION
    assert factory.call_args.kwargs["aws_secret_access_key"] == SECRET
    client.get_caller_identity.assert_called_once_with()


@pytest.mark.asyncio
async def test_health_check_with_a_region_only_uses_the_default_chain(monkeypatch):
    factory, _ = _sts(monkeypatch)

    await bedrock.lightweight_health_check({"aws_region_name": REGION})

    assert "aws_access_key_id" not in factory.call_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            ClientError(
                {"Error": {"Code": "InvalidClientTokenId", "Message": f"bad {SECRET}"}},
                "GetCallerIdentity",
            ),
            "InvalidClientTokenId",
        ),
        (NoCredentialsError(), "No AWS credentials were found"),
        (RuntimeError(f"boom {SECRET}"), "RuntimeError"),
    ],
)
async def test_health_check_failures_are_clean_value_errors(monkeypatch, error, expected):
    _sts(monkeypatch, error=error)

    with pytest.raises(ValueError) as caught:
        await bedrock.lightweight_health_check(
            {"aws_region_name": REGION, "aws_secret_access_key": SECRET}
        )

    assert expected in str(caught.value)
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_an_sts_connect_timeout_does_not_block_the_save(monkeypatch):
    from botocore.exceptions import ConnectTimeoutError

    _sts(monkeypatch, error=ConnectTimeoutError(endpoint_url="https://sts.example"))
    await bedrock.lightweight_health_check({"aws_region_name": REGION})


@pytest.mark.asyncio
async def test_a_mistyped_region_fails_the_check(monkeypatch):
    from botocore.exceptions import EndpointConnectionError

    _sts(monkeypatch, error=EndpointConnectionError(endpoint_url="https://sts.us-esat-1.example"))

    with pytest.raises(ValueError, match="Check the region name"):
        await bedrock.lightweight_health_check({"aws_region_name": "us-esat-1"})


@pytest.mark.asyncio
async def test_a_key_id_without_its_secret_says_so(monkeypatch):
    from botocore.exceptions import PartialCredentialsError

    _sts(monkeypatch, error=PartialCredentialsError(provider="explicit", cred_var="secret"))

    with pytest.raises(ValueError, match="both the access key ID and the secret"):
        await bedrock.lightweight_health_check(
            {"aws_region_name": REGION, "aws_access_key_id": "AKIAEXAMPLE"}
        )


@pytest.mark.asyncio
async def test_health_check_needs_a_region():
    with pytest.raises(ValueError, match="region"):
        await bedrock.lightweight_health_check({"aws_secret_access_key": SECRET})


async def _save(config, body, **patches):
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
async def test_a_credential_save_checks_the_pending_credentials(monkeypatch):
    factory, _ = _sts(monkeypatch)
    config = _config(
        aws_region_name=REGION, aws_access_key_id="OLDKEY", aws_secret_access_key="OLD"
    )
    body = SettingsUpdateBody(
        provider_credentials={
            "bedrock": {"aws_secret_access_key": SECRET, "aws_access_key_id": "NEWKEY"}
        }
    )

    response, save = await _save(config, body)

    assert getattr(response, "status_code", 200) == 200
    kwargs = factory.call_args.kwargs
    assert (kwargs["aws_access_key_id"], kwargs["aws_secret_access_key"]) == ("NEWKEY", SECRET)
    assert kwargs["region_name"] == REGION
    save.assert_called_once()


@pytest.mark.asyncio
async def test_a_rejected_credential_save_is_a_400_without_the_secret(monkeypatch):
    _sts(
        monkeypatch,
        error=ClientError(
            {"Error": {"Code": "SignatureDoesNotMatch", "Message": f"key {SECRET}"}},
            "GetCallerIdentity",
        ),
    )
    config = _config(aws_region_name=REGION)
    body = SettingsUpdateBody(
        provider_credentials={
            "bedrock": {"aws_secret_access_key": SECRET, "aws_access_key_id": "K"}
        }
    )

    response, save = await _save(config, body)

    assert response.status_code == 400
    assert b"SignatureDoesNotMatch" in response.body
    assert SECRET.encode() not in response.body
    save.assert_not_called()


def _aws_keys(config):
    return {k for k in config.providers.credential_values("bedrock") if k.startswith("aws_")}


@pytest.fixture
def real_boto_sts(monkeypatch, tmp_path):
    """Real boto3 client creation (so credential-pair validation runs); only the call is faked."""
    calls: list[str] = []

    def api_call(self, operation_name, api_params):
        calls.append(operation_name)
        return {"Account": "1"}

    monkeypatch.setattr("botocore.client.BaseClient._make_api_call", api_call)
    # Keep the host's AWS profile and instance metadata out of credential resolution.
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    return calls


def _keyed_config():
    return _config(
        aws_region_name=REGION, aws_access_key_id="AKIAOLD", aws_secret_access_key=SECRET
    )


async def _update(config, provider_credentials=None, removals=None):
    body = SettingsUpdateBody(
        provider_credentials={"bedrock": provider_credentials or {}},
        provider_credential_removals={"bedrock": removals} if removals else None,
    )
    response, save = await _save(config, body)
    saved = save.call_args.args[0] if save.called else None
    return getattr(response, "status_code", 200), getattr(response, "body", b""), saved


@pytest.mark.asyncio
async def test_clearing_the_access_key_id_goes_back_to_the_iam_role(real_boto_sts):
    config = _keyed_config()

    status, body, saved = await _update(config, removals=["aws_access_key_id"])

    assert status == 200, body
    assert real_boto_sts == ["GetCallerIdentity"]
    assert _aws_keys(saved) == {"aws_region_name"}


@pytest.mark.asyncio
async def test_a_region_only_save_keeps_the_keys(real_boto_sts):
    config = _keyed_config()

    status, body, saved = await _update(config, {"aws_region_name": "us-east-1"})

    assert status == 200, body
    assert saved.providers.stored_credentials("bedrock")["aws_secret_access_key"] == SECRET


@pytest.mark.asyncio
async def test_resubmitting_the_same_key_id_keeps_its_secret(real_boto_sts):
    config = _keyed_config()

    status, body, saved = await _update(config, {"aws_access_key_id": "AKIAOLD"})

    assert status == 200, body
    assert saved.providers.stored_credentials("bedrock")["aws_secret_access_key"] == SECRET


@pytest.mark.asyncio
async def test_submitting_only_the_secret_keeps_the_key_id(real_boto_sts):
    config = _keyed_config()

    status, body, saved = await _update(config, {"aws_secret_access_key": "fresh"})

    assert status == 200, body
    stored = saved.providers.stored_credentials("bedrock")
    assert (stored["aws_access_key_id"], stored["aws_secret_access_key"]) == ("AKIAOLD", "fresh")


@pytest.mark.asyncio
async def test_a_new_key_id_is_not_validated_against_the_old_secret(real_boto_sts):
    config = _keyed_config()

    status, body, saved = await _update(config, {"aws_access_key_id": "AKIANEW"})

    assert status == 400
    assert b"both the access key ID and the secret" in body
    assert real_boto_sts == []
    assert saved is None


def test_a_new_access_key_id_replaces_the_old_secret_and_the_same_one_keeps_it():
    config = _config(
        aws_region_name=REGION, aws_access_key_id="AKIAOLD", aws_secret_access_key=SECRET
    )

    config.providers.set_credentials("bedrock", {"aws_access_key_id": "AKIAOLD"})
    assert config.providers.stored_credentials("bedrock")["aws_secret_access_key"] == SECRET

    config.providers.set_credentials("bedrock", {"aws_access_key_id": "AKIANEW"})
    assert "aws_secret_access_key" not in config.providers.stored_credentials("bedrock")

    config.providers.set_credentials(
        "bedrock", {"aws_access_key_id": "AKIAOTHER", "aws_secret_access_key": "fresh"}
    )
    assert config.providers.stored_credentials("bedrock")["aws_secret_access_key"] == "fresh"


@pytest.mark.asyncio
async def test_removing_bedrock_deletes_it_and_falls_back():
    config = _config(aws_region_name=REGION)
    config.providers.openai = OpenAIConfig(api_key="sk-test", configured=True)
    config.knowledge.embedding_provider = "bedrock"
    config.knowledge.embedding_model = "cohere.embed-english-v3"

    response, save = await _save(config, SettingsUpdateBody(remove_provider_config="Bedrock"))

    assert getattr(response, "status_code", 200) == 200
    saved = save.call_args.args[0]
    assert "bedrock" not in saved.providers.custom
    assert saved.knowledge.embedding_provider == "openai"


def test_bedrock_alone_counts_as_another_configured_provider():
    config = _config(aws_region_name=REGION)
    assert _has_other_configured_provider(config, "openai") is True
    assert _has_other_configured_provider(config, "bedrock") is False


def test_rotating_the_secret_key_busts_the_health_cache():
    base = {
        "provider": "bedrock",
        "embedding_provider": "bedrock",
        "test_completion": False,
        "llm_model": "",
        "embedding_model": "",
        "endpoint": None,
        "project_id": None,
        "api_key": None,
    }
    one = provider_health_cache.cache_key(
        **base, credentials={"aws_region_name": REGION, "aws_secret_access_key": "one"}
    )
    two = provider_health_cache.cache_key(
        **base, credentials={"aws_region_name": REGION, "aws_secret_access_key": "two"}
    )
    assert one != two
    assert "one" not in one
