"""Unit tests for the Bedrock credential env-var block in
`config.settings.AppClients.patched_async_client`.

Mirrors the WatsonX block exactly: access_key_id/secret_access_key are only
set as env vars when explicitly configured (so IAM role/IRSA auth keeps
working with zero explicit creds), while region is always set whenever
configured, since LiteLLM needs it to route/sign every Bedrock request
regardless of auth mode.
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

    def test_explicit_credentials_are_all_set(self, monkeypatch):
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
        assert os.environ.get("AWS_ACCESS_KEY_ID") == "AKIAEXAMPLE"
        assert os.environ.get("AWS_SECRET_ACCESS_KEY") == "supersecret"

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
