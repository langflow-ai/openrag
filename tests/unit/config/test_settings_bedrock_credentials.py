"""Unit tests for the Bedrock env-var block in
`config.settings.AppClients.patched_async_client`.

Only the region is exported: LiteLLM needs AWS_REGION_NAME to route/sign
every Bedrock request regardless of auth mode, and no other component reads
that variable. The access key and secret must NOT be exported as
AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY - those are the credential fallback
the AWS S3 connector reads (connectors/aws_s3/auth.py), so configuring
Bedrock would silently reauthenticate every S3 connector relying on it.
They are passed per call instead; see
tests/unit/services/test_models_service_bedrock_credentials.py.
"""

from types import SimpleNamespace

import pytest

from config.settings import AppClients


def _config(*, region="", access_key_id="", secret_access_key="") -> SimpleNamespace:
    return SimpleNamespace(
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key=""),
            anthropic=SimpleNamespace(api_key=""),
            watsonx=SimpleNamespace(api_key="", endpoint="", project_id=""),
            ollama=SimpleNamespace(endpoint=""),
            bedrock=SimpleNamespace(
                region=region,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
            ),
        ),
        knowledge=SimpleNamespace(
            embedding_model="cohere.embed-multilingual-v3",
            embedding_provider="bedrock",
        ),
    )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"):
        monkeypatch.delenv(var, raising=False)
    # patched_async_client falls back to a raw (non-monkeypatch-tracked)
    # `os.environ["OPENAI_API_KEY"] = "no-key-required"` assignment when this
    # is unset - which would leak into the real environment for the rest of
    # the test session and break unrelated tests (e.g. test_encryption.py's
    # auto-upgrade test, which reads OPENAI_API_KEY back via config
    # env-overrides). Pre-seed it through monkeypatch so that fallback branch
    # never fires and cleanup is guaranteed.
    monkeypatch.setenv("OPENAI_API_KEY", "test-dummy-key")


class TestBedrockCredentialEnvVars:
    def test_iam_role_mode_sets_region_only(self, monkeypatch):
        """Zero explicit creds: region is set (litellm needs it to sign/route
        every request), but no access key env vars are set - so an IAM role
        (e.g. IRSA) is free to supply credentials instead."""
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(region="eu-central-1"),
        )

        client = AppClients()
        _ = client.patched_async_client

        assert __import__("os").environ.get("AWS_REGION_NAME") == "eu-central-1"
        assert "AWS_ACCESS_KEY_ID" not in __import__("os").environ
        assert "AWS_SECRET_ACCESS_KEY" not in __import__("os").environ

    def test_explicit_credentials_never_leak_into_the_shared_aws_env_vars(self, monkeypatch):
        """Regression: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are the AWS S3
        connector's credential fallback. Bedrock must not overwrite them."""
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(
                region="us-east-1",
                access_key_id="AKIAEXAMPLE",
                secret_access_key="supersecret",
            ),
        )

        client = AppClients()
        _ = client.patched_async_client

        import os

        assert os.environ.get("AWS_REGION_NAME") == "us-east-1"
        assert "AWS_ACCESS_KEY_ID" not in os.environ
        assert "AWS_SECRET_ACCESS_KEY" not in os.environ

    def test_preexisting_s3_connector_credentials_survive(self, monkeypatch):
        """The S3 connector's env credentials must be left untouched."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "S3-KEY")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3-secret")
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(
                region="us-east-1",
                access_key_id="AKIAEXAMPLE",
                secret_access_key="supersecret",
            ),
        )

        client = AppClients()
        _ = client.patched_async_client

        import os

        assert os.environ["AWS_ACCESS_KEY_ID"] == "S3-KEY"
        assert os.environ["AWS_SECRET_ACCESS_KEY"] == "s3-secret"

    def test_no_bedrock_config_sets_no_aws_env_vars(self, monkeypatch):
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(),
        )

        client = AppClients()
        _ = client.patched_async_client

        import os

        assert "AWS_REGION_NAME" not in os.environ
        assert "AWS_ACCESS_KEY_ID" not in os.environ
        assert "AWS_SECRET_ACCESS_KEY" not in os.environ

    @pytest.mark.asyncio
    async def test_region_removed_then_refreshed_clears_stale_env_var(self, monkeypatch):
        """CodeRabbit finding, confirmed real: AWS_REGION_NAME is process-wide
        and refresh_patched_client() only closes the old client - it never
        touched the env var. Configure a region, refresh after removing it,
        and confirm the stale value doesn't linger for the next client."""
        current = {"region": "eu-central-1"}
        monkeypatch.setattr(
            "config.settings.get_openrag_config",
            lambda: _config(region=current["region"]),
        )

        client = AppClients()
        _ = client.patched_async_client

        import os

        assert os.environ.get("AWS_REGION_NAME") == "eu-central-1"

        current["region"] = ""
        await client.refresh_patched_client()
        _ = client.patched_async_client

        assert "AWS_REGION_NAME" not in os.environ


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
