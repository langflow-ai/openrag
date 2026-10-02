"""Unit tests for the AWS Bedrock provider config wiring in ConfigManager.

Covers: the BedrockConfig dataclass, ProvidersConfig wiring (default value so
pre-existing callers that don't know about bedrock keep working),
get_provider_config() dispatch, and env-var override loading (including the
"leave access keys blank, IAM role auth still works" requirement).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.config_manager import (  # noqa: E402
    AnthropicConfig,
    BedrockConfig,
    ConfigManager,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
)


class TestBedrockConfigDataclass:
    def test_defaults(self):
        cfg = BedrockConfig()
        assert cfg.region == ""
        assert cfg.access_key_id == ""
        assert cfg.secret_access_key == ""
        assert cfg.configured is False

    def test_explicit_values(self):
        cfg = BedrockConfig(
            region="eu-central-1",
            access_key_id="AKIA...",
            secret_access_key="secret",
            configured=True,
        )
        assert cfg.region == "eu-central-1"
        assert cfg.access_key_id == "AKIA..."
        assert cfg.secret_access_key == "secret"
        assert cfg.configured is True


class TestProvidersConfigBedrockWiring:
    def _make_providers(self, **bedrock_kwargs) -> ProvidersConfig:
        return ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
            **({"bedrock": BedrockConfig(**bedrock_kwargs)} if bedrock_kwargs else {}),
        )

    def test_bedrock_field_has_default_so_existing_callers_keep_working(self):
        """ProvidersConfig must remain constructible without passing `bedrock=`
        so pre-existing call sites across the codebase (and tests) that only
        know about openai/anthropic/watsonx/ollama don't break."""
        providers = ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        )
        assert isinstance(providers.bedrock, BedrockConfig)
        assert providers.bedrock.configured is False

    def test_get_provider_config_returns_bedrock(self):
        providers = self._make_providers(region="us-east-1")
        assert providers.get_provider_config("bedrock").region == "us-east-1"

    def test_get_provider_config_is_case_insensitive(self):
        providers = self._make_providers(region="us-east-1")
        assert providers.get_provider_config("Bedrock").region == "us-east-1"

    def test_any_configured_true_when_only_bedrock_configured(self):
        providers = self._make_providers(region="us-east-1", configured=True)
        assert providers.any_configured() is True

    def test_any_configured_false_when_nothing_configured(self):
        providers = self._make_providers()
        assert providers.any_configured() is False


class TestConfigManagerBedrockEnvOverrides:
    """`_load_env_overrides` should read BEDROCK_* env vars into config_data,
    mirroring the exact pattern used for WATSONX_*."""

    def _manager(self, tmp_path) -> ConfigManager:
        return ConfigManager(config_file=str(tmp_path / "config.yaml"))

    def test_region_env_var_applied(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BEDROCK_REGION", "eu-central-1")
        monkeypatch.delenv("BEDROCK_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("BEDROCK_SECRET_ACCESS_KEY", raising=False)

        cm = self._manager(tmp_path)
        config = cm.load_config()

        assert config.providers.bedrock.region == "eu-central-1"
        assert config.providers.bedrock.access_key_id == ""
        assert config.providers.bedrock.secret_access_key == ""

    def test_access_keys_env_vars_applied(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
        monkeypatch.setenv("BEDROCK_ACCESS_KEY_ID", "AKIAEXAMPLE")
        monkeypatch.setenv("BEDROCK_SECRET_ACCESS_KEY", "supersecret")

        cm = self._manager(tmp_path)
        config = cm.load_config()

        assert config.providers.bedrock.region == "us-east-1"
        assert config.providers.bedrock.access_key_id == "AKIAEXAMPLE"
        assert config.providers.bedrock.secret_access_key == "supersecret"

    def test_iam_role_use_case_leaves_keys_blank_without_error(self, tmp_path, monkeypatch):
        """Zero explicit credentials (IAM role / IRSA) must load cleanly -
        only region is required."""
        monkeypatch.setenv("BEDROCK_REGION", "us-west-2")
        monkeypatch.delenv("BEDROCK_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("BEDROCK_SECRET_ACCESS_KEY", raising=False)

        cm = self._manager(tmp_path)
        config = cm.load_config()

        assert config.providers.bedrock.region == "us-west-2"
        assert config.providers.bedrock.access_key_id == ""
        assert config.providers.bedrock.secret_access_key == ""
        # Mirrors the existing pattern (e.g. watsonx): env-var-supplied
        # credentials do not automatically flip `configured` - that flag is
        # only ever set by the settings/onboarding REST handlers.
        assert config.providers.bedrock.configured is False

    def test_no_env_vars_leaves_bedrock_at_defaults(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BEDROCK_REGION", raising=False)
        monkeypatch.delenv("BEDROCK_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("BEDROCK_SECRET_ACCESS_KEY", raising=False)

        cm = self._manager(tmp_path)
        config = cm.load_config()

        assert config.providers.bedrock == BedrockConfig()

    def test_edited_config_skips_bedrock_env_overrides(self, tmp_path, monkeypatch):
        """Same priority rule as every other provider: a manually-edited
        config.yaml wins over env vars entirely."""
        import yaml

        monkeypatch.setenv("BEDROCK_REGION", "eu-central-1")
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            yaml.dump(
                {
                    "providers": {"bedrock": {"region": "ap-south-1"}},
                    "edited": True,
                }
            )
        )

        cm = ConfigManager(config_file=str(cfg_path))
        config = cm.load_config()

        assert config.providers.bedrock.region == "ap-south-1"


class TestConfigManagerBedrockFileRoundTrip:
    @pytest.fixture(autouse=True)
    def _encryption_key(self, monkeypatch):
        """Provide a master secret so encrypt_secret()/decrypt_secret() are
        active (they no-op to plaintext without one), mirroring the fixture
        used in tests/unit/test_encryption.py."""
        import base64

        import utils.encryption

        utils.encryption._cached_master_secret = None
        monkeypatch.setenv(
            "OPENRAG_ENCRYPTION_KEY",
            base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii"),
        )
        yield
        utils.encryption._cached_master_secret = None

    def test_save_and_reload_round_trips_bedrock_fields(self, tmp_path, monkeypatch):
        for var in ("BEDROCK_REGION", "BEDROCK_ACCESS_KEY_ID", "BEDROCK_SECRET_ACCESS_KEY"):
            monkeypatch.delenv(var, raising=False)

        cfg_path = tmp_path / "config.yaml"
        cm = ConfigManager(config_file=str(cfg_path))
        config = cm.load_config()
        config.providers.bedrock.region = "ca-central-1"
        config.providers.bedrock.access_key_id = "AKIA123"
        config.providers.bedrock.secret_access_key = "shh"
        config.providers.bedrock.configured = True

        assert cm.save_config_file(config) is True

        # secret_access_key is a genuine AWS credential (unlike access_key_id,
        # which AWS treats as an identifier, not a secret) and must be
        # encrypted at rest, mirroring how api_key is handled for every other
        # provider. Assert the plaintext value never touches disk.
        raw_on_disk = cfg_path.read_text()
        assert "shh" not in raw_on_disk

        import yaml

        with open(cfg_path) as f:
            saved_data = yaml.safe_load(f)
        bedrock_data = saved_data["providers"]["bedrock"]
        assert isinstance(bedrock_data["secret_access_key"], dict)
        assert bedrock_data["secret_access_key"]["algorithm"] == "AES-256-GCM"
        # access_key_id is not a secret and stays plaintext, same as before.
        assert bedrock_data["access_key_id"] == "AKIA123"

        cm2 = ConfigManager(config_file=str(cfg_path))
        reloaded = cm2.load_config()

        assert reloaded.providers.bedrock.region == "ca-central-1"
        assert reloaded.providers.bedrock.access_key_id == "AKIA123"
        assert reloaded.providers.bedrock.secret_access_key == "shh"
        assert reloaded.providers.bedrock.configured is True


class TestBedrockGenericCredentialsBridge:
    """Bedrock is now offered via config/model_providers.yaml, so it renders
    through GenericOnboarding - the generic-provider form driven by litellm's
    own bundled credential-field spec, which names Bedrock's fields
    aws_region_name/aws_access_key_id/aws_secret_access_key. Those submit
    through the generic provider_credentials payload
    (ProvidersConfig.set_credentials), which must bridge them into the typed
    BedrockConfig fields the rest of Bedrock support (model registry gate,
    lightweight health check, embedding call kwargs) already reads directly.
    """

    def test_set_credentials_populates_typed_bedrock_fields(self):
        providers = ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        )

        providers.set_credentials(
            "bedrock",
            {
                "aws_region_name": "eu-central-1",
                "aws_access_key_id": "AKIA123",
                "aws_secret_access_key": "shh",
            },
        )

        assert providers.bedrock.region == "eu-central-1"
        assert providers.bedrock.access_key_id == "AKIA123"
        assert providers.bedrock.secret_access_key == "shh"
        assert providers.bedrock.configured is True

    def test_set_credentials_iam_role_mode_needs_only_region(self):
        """No access key/secret - the IAM role / IRSA auth mode."""
        providers = ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        )

        providers.set_credentials("bedrock", {"aws_region_name": "us-east-1"})

        assert providers.bedrock.region == "us-east-1"
        assert providers.bedrock.access_key_id == ""
        assert providers.bedrock.configured is True

    def test_credential_values_round_trips_through_generic_submission(self):
        """What set_credentials writes, credential_values must read back in
        the exact litellm kwarg shape - the two are the write and read
        halves of the same bridge."""
        providers = ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        )

        providers.set_credentials(
            "bedrock",
            {
                "aws_region_name": "eu-central-1",
                "aws_access_key_id": "AKIA123",
                "aws_secret_access_key": "shh",
            },
        )

        assert providers.credential_values("bedrock") == {
            "aws_region_name": "eu-central-1",
            "aws_access_key_id": "AKIA123",
            "aws_secret_access_key": "shh",
        }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
