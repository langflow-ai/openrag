"""Unit tests for OCI provider config wiring in ``config.config_manager``."""

import base64
from pathlib import Path

import pytest
import yaml

from config.config_manager import (
    AnthropicConfig,
    ConfigManager,
    OCIConfig,
    OllamaConfig,
    OpenAIConfig,
    ProvidersConfig,
    WatsonXConfig,
)


class TestOCIConfigDefaults:
    def test_defaults_are_all_empty(self):
        cfg = OCIConfig()
        assert cfg.user == ""
        assert cfg.fingerprint == ""
        assert cfg.tenancy == ""
        assert cfg.compartment_id == ""
        assert cfg.key_file == ""
        assert cfg.key == ""
        assert cfg.region == ""
        assert cfg.configured is False

    def test_oci_config_auth_method_defaults_to_api_key(self):
        config = OCIConfig()
        assert config.auth_method == "api_key"

    def test_oci_config_auth_method_accepts_instance_principal(self):
        config = OCIConfig(auth_method="instance_principal")
        assert config.auth_method == "instance_principal"


class TestProvidersConfigOci:
    def _make_providers(self, **oci_kwargs) -> ProvidersConfig:
        return ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
            oci=OCIConfig(**oci_kwargs) if oci_kwargs else OCIConfig(),
        )

    def test_oci_defaults_when_omitted(self):
        """Existing call sites that don't pass oci= must keep working."""
        providers = ProvidersConfig(
            openai=OpenAIConfig(),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        )
        assert isinstance(providers.oci, OCIConfig)
        assert providers.oci.configured is False

    def test_get_provider_config_returns_oci(self):
        providers = self._make_providers(user="u")
        assert providers.get_provider_config("oci") is providers.oci

    def test_get_provider_config_is_case_insensitive(self):
        providers = self._make_providers(user="u")
        assert providers.get_provider_config("OCI") is providers.oci

    def test_any_configured_true_when_only_oci_configured(self):
        providers = self._make_providers(configured=True)
        assert providers.any_configured() is True

    def test_any_configured_false_when_nothing_configured(self):
        providers = self._make_providers()
        assert providers.any_configured() is False

    def test_unknown_provider_falls_back_to_generic_config(self):
        """Unrecognized provider names resolve through the generic custom-
        provider path (GenericProviderConfig), not a raise - this is what
        lets any arbitrary LiteLLM provider be configured via
        provider_credentials without a dedicated dataclass."""
        providers = self._make_providers()
        config = providers.get_provider_config("not-a-real-provider")
        assert config.configured is False


class TestConfigManagerOciEnvOverrides:
    def _cm(self, tmp_path) -> ConfigManager:
        return ConfigManager(config_file=str(Path(tmp_path) / "config.yaml"))

    def test_env_vars_populate_oci_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OCI_USER", "ocid1.user.oc1..xxx")
        monkeypatch.setenv("OCI_FINGERPRINT", "xx:xx:xx:xx")
        monkeypatch.setenv("OCI_TENANCY", "ocid1.tenancy.oc1..xxx")
        monkeypatch.setenv("OCI_COMPARTMENT_ID", "ocid1.compartment.oc1..xxx")
        monkeypatch.setenv("OCI_KEY_FILE", "/tmp/oci_key.pem")
        monkeypatch.setenv("OCI_REGION", "us-ashburn-1")
        monkeypatch.delenv("OCI_KEY", raising=False)

        cm = self._cm(tmp_path)
        config = cm.load_config()

        assert config.providers.oci.user == "ocid1.user.oc1..xxx"
        assert config.providers.oci.fingerprint == "xx:xx:xx:xx"
        assert config.providers.oci.tenancy == "ocid1.tenancy.oc1..xxx"
        assert config.providers.oci.compartment_id == "ocid1.compartment.oc1..xxx"
        assert config.providers.oci.key_file == "/tmp/oci_key.pem"
        assert config.providers.oci.region == "us-ashburn-1"
        assert config.providers.oci.key == ""

    def test_inline_key_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OCI_KEY", "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----")

        cm = self._cm(tmp_path)
        config = cm.load_config()

        assert config.providers.oci.key.startswith("-----BEGIN PRIVATE KEY-----")

    def test_no_env_vars_leaves_oci_blank(self, tmp_path, monkeypatch):
        for var in (
            "OCI_USER",
            "OCI_FINGERPRINT",
            "OCI_TENANCY",
            "OCI_COMPARTMENT_ID",
            "OCI_KEY_FILE",
            "OCI_KEY",
            "OCI_REGION",
        ):
            monkeypatch.delenv(var, raising=False)

        cm = self._cm(tmp_path)
        config = cm.load_config()

        assert config.providers.oci == OCIConfig()

    def test_oci_auth_method_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OCI_AUTH_METHOD", "workload_identity")
        cm = self._cm(tmp_path)
        config = cm.load_config()
        assert config.providers.oci.auth_method == "workload_identity"

    def test_round_trips_through_save_and_reload(self, tmp_path, monkeypatch):
        for var in (
            "OCI_USER",
            "OCI_FINGERPRINT",
            "OCI_TENANCY",
            "OCI_COMPARTMENT_ID",
            "OCI_KEY_FILE",
            "OCI_KEY",
            "OCI_REGION",
        ):
            monkeypatch.delenv(var, raising=False)

        cm = self._cm(tmp_path)
        config = cm.load_config()
        config.providers.oci.user = "ocid1.user.oc1..saved"
        config.providers.oci.fingerprint = "aa:bb:cc"
        config.providers.oci.tenancy = "ocid1.tenancy.oc1..saved"
        config.providers.oci.compartment_id = "ocid1.compartment.oc1..saved"
        config.providers.oci.key_file = "/tmp/saved_key.pem"
        config.providers.oci.region = "eu-frankfurt-1"
        config.providers.oci.configured = True

        assert cm.save_config_file(config) is True

        cm2 = self._cm(tmp_path)
        reloaded = cm2.load_config()

        assert reloaded.providers.oci.user == "ocid1.user.oc1..saved"
        assert reloaded.providers.oci.fingerprint == "aa:bb:cc"
        assert reloaded.providers.oci.tenancy == "ocid1.tenancy.oc1..saved"
        assert reloaded.providers.oci.compartment_id == "ocid1.compartment.oc1..saved"
        assert reloaded.providers.oci.key_file == "/tmp/saved_key.pem"
        assert reloaded.providers.oci.region == "eu-frankfurt-1"
        assert reloaded.providers.oci.configured is True


class TestOCIInlineKeyEncryptionAtRest:
    """Regression coverage: the inline PEM key (``oci.key``) must be encrypted
    on disk the same way ``api_key`` is for the other providers.
    OCIConfig previously bypassed ``_decrypt_provider`` entirely on load, and
    ``save_config_file``'s encryption loop only targeted ``api_key``, so a
    user-submitted inline PEM key was persisted to config.yaml in plaintext.
    ``key_file`` is a filesystem path, not a secret, and must stay untouched.
    """

    @pytest.fixture(autouse=True)
    def _encryption_key(self, monkeypatch):
        import utils.encryption

        utils.encryption._cached_master_secret = None
        monkeypatch.setenv(
            "OPENRAG_ENCRYPTION_KEY",
            base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii"),
        )
        yield
        utils.encryption._cached_master_secret = None

    def _cm(self, tmp_path) -> ConfigManager:
        return ConfigManager(config_file=str(Path(tmp_path) / "config.yaml"))

    def test_inline_key_encrypted_on_disk_and_decrypts_on_reload(self, tmp_path, monkeypatch):
        for var in (
            "OCI_USER",
            "OCI_FINGERPRINT",
            "OCI_TENANCY",
            "OCI_COMPARTMENT_ID",
            "OCI_KEY_FILE",
            "OCI_KEY",
            "OCI_REGION",
        ):
            monkeypatch.delenv(var, raising=False)

        pem = "-----BEGIN PRIVATE KEY-----\nMIIBogplaintext\n-----END PRIVATE KEY-----"

        cm = self._cm(tmp_path)
        config = cm.load_config()
        config.providers.oci.user = "ocid1.user.oc1..xxx"
        config.providers.oci.fingerprint = "aa:bb:cc"
        config.providers.oci.tenancy = "ocid1.tenancy.oc1..xxx"
        config.providers.oci.compartment_id = "ocid1.compartment.oc1..xxx"
        config.providers.oci.key = pem
        config.providers.oci.key_file = ""
        config.providers.oci.region = "us-ashburn-1"
        config.providers.oci.configured = True

        assert cm.save_config_file(config) is True

        # The raw YAML on disk must NOT contain the plaintext PEM - it must be
        # an AES-256-GCM envelope, exactly like api_key for other providers.
        with open(cm.config_file) as f:
            raw = yaml.safe_load(f)
        raw_key = raw["providers"]["oci"]["key"]
        assert isinstance(raw_key, dict), "oci.key must be encrypted (dict envelope) at rest"
        assert raw_key["algorithm"] == "AES-256-GCM"
        assert pem not in yaml.dump(raw)

        # Reloading decrypts it back to the original plaintext PEM.
        cm2 = self._cm(tmp_path)
        reloaded = cm2.load_config()
        assert reloaded.providers.oci.key == pem

    def test_key_file_path_left_unencrypted(self, tmp_path, monkeypatch):
        """key_file is a filesystem path, not a secret - must not be touched."""
        for var in ("OCI_KEY", "OCI_KEY_FILE"):
            monkeypatch.delenv(var, raising=False)

        cm = self._cm(tmp_path)
        config = cm.load_config()
        config.providers.oci.key = ""
        config.providers.oci.key_file = "/etc/oci/api_key.pem"
        config.providers.oci.configured = True

        assert cm.save_config_file(config) is True

        with open(cm.config_file) as f:
            raw = yaml.safe_load(f)
        assert raw["providers"]["oci"]["key_file"] == "/etc/oci/api_key.pem"

        cm2 = self._cm(tmp_path)
        reloaded = cm2.load_config()
        assert reloaded.providers.oci.key_file == "/etc/oci/api_key.pem"
