"""Unit tests for the AWS Bedrock lightweight health/validation check.

Bedrock auth is AWS SigV4 signing performed by LiteLLM at call time, so
there's no cheap unsigned HTTP probe to make the way watsonx's IBM IAM
token exchange works. `_test_bedrock_lightweight_health` instead validates
config *shape* directly against the config singleton - these tests assert
that check's pass/fail conditions and that no live network call is made.
"""

from types import SimpleNamespace

import pytest

from api.provider_validation import _test_bedrock_lightweight_health
from api.provider_validation import test_embedding as run_embedding_test
from api.provider_validation import test_lightweight_health as run_lightweight_health_test


def _patch_bedrock_config(monkeypatch, **bedrock_kwargs):
    bedrock_config = SimpleNamespace(
        region="", access_key_id="", secret_access_key="", configured=False
    )
    for key, value in bedrock_kwargs.items():
        setattr(bedrock_config, key, value)
    monkeypatch.setattr(
        "config.config_manager.config_manager",
        SimpleNamespace(
            get_config=lambda: SimpleNamespace(providers=SimpleNamespace(bedrock=bedrock_config))
        ),
    )


class TestBedrockLightweightHealthCredentialShape:
    @pytest.mark.asyncio
    async def test_passes_with_region_only_iam_role(self, monkeypatch):
        _patch_bedrock_config(monkeypatch, region="eu-central-1")
        await _test_bedrock_lightweight_health()  # must not raise

    @pytest.mark.asyncio
    async def test_passes_with_region_and_matched_key_pair(self, monkeypatch):
        _patch_bedrock_config(
            monkeypatch,
            region="us-east-1",
            access_key_id="AKIAEXAMPLE",
            secret_access_key="supersecret",
        )
        await _test_bedrock_lightweight_health()  # must not raise

    @pytest.mark.asyncio
    async def test_fails_without_region(self, monkeypatch):
        _patch_bedrock_config(monkeypatch, region="")
        with pytest.raises(Exception, match="region"):
            await _test_bedrock_lightweight_health()

    @pytest.mark.asyncio
    async def test_fails_with_access_key_but_no_secret(self, monkeypatch):
        _patch_bedrock_config(
            monkeypatch, region="us-east-1", access_key_id="AKIAEXAMPLE", secret_access_key=""
        )
        with pytest.raises(Exception, match="together"):
            await _test_bedrock_lightweight_health()

    @pytest.mark.asyncio
    async def test_fails_with_secret_but_no_access_key(self, monkeypatch):
        _patch_bedrock_config(
            monkeypatch, region="us-east-1", access_key_id="", secret_access_key="supersecret"
        )
        with pytest.raises(Exception, match="together"):
            await _test_bedrock_lightweight_health()

    @pytest.mark.asyncio
    async def test_never_makes_a_live_network_call(self, monkeypatch):
        _patch_bedrock_config(monkeypatch, region="eu-central-1")

        class ExplodingClient:
            def __init__(self, *a, **k):
                raise AssertionError("Bedrock lightweight health check must not touch the network")

        monkeypatch.setattr("httpx.AsyncClient", ExplodingClient)
        await _test_bedrock_lightweight_health()  # must not raise / not touch httpx


class TestDispatchersRouteToBedrock:
    @pytest.mark.asyncio
    async def test_lightweight_health_dispatch_hits_bedrock_branch(self, monkeypatch):
        _patch_bedrock_config(monkeypatch, region="eu-central-1")
        await run_lightweight_health_test(provider="bedrock")  # must not raise

    @pytest.mark.asyncio
    async def test_lightweight_health_dispatch_bedrock_failure_propagates(self, monkeypatch):
        _patch_bedrock_config(monkeypatch, region="")
        with pytest.raises(Exception, match="region"):
            await run_lightweight_health_test(provider="bedrock")

    @pytest.mark.asyncio
    async def test_embedding_dispatch_hits_bedrock_branch(self, monkeypatch):
        _patch_bedrock_config(monkeypatch, region="eu-central-1")
        await run_embedding_test(
            provider="bedrock", embedding_model="cohere.embed-multilingual-v3"
        )  # must not raise


class TestBedrockLightweightHealthUsesPendingCredentials:
    """Regression test for validating a pending (not-yet-saved) config.

    `update_settings()` validates BEFORE persisting, threading the request's
    resolved/pending credential values through `validate_provider_setup` ->
    `test_lightweight_health` -> here via the `credentials` dict. Before this
    fix, `_test_bedrock_lightweight_health` ignored that parameter entirely
    and re-read the OLD saved config instead - so a single first-time-setup
    request that both submits Bedrock's region/keys AND selects Bedrock as
    the embedding provider failed with "requires a region", even though the
    request itself supplied one.
    """

    @pytest.mark.asyncio
    async def test_passes_with_pending_region_even_when_saved_config_is_unconfigured(
        self, monkeypatch
    ):
        # The currently-saved config has no Bedrock fields yet (first-time
        # setup) - if the function fell back to reading it, this would fail.
        _patch_bedrock_config(monkeypatch, region="", access_key_id="", secret_access_key="")

        pending_credentials = {"aws_region_name": "eu-central-1"}
        await _test_bedrock_lightweight_health(pending_credentials)  # must not raise

    @pytest.mark.asyncio
    async def test_fails_without_region_in_pending_credentials(self, monkeypatch):
        _patch_bedrock_config(monkeypatch, region="us-east-1")  # saved config IS configured

        with pytest.raises(Exception, match="region"):
            await _test_bedrock_lightweight_health({})

    @pytest.mark.asyncio
    async def test_fails_with_mismatched_pending_key_pair(self, monkeypatch):
        _patch_bedrock_config(monkeypatch, region="")

        pending_credentials = {
            "aws_region_name": "eu-central-1",
            "aws_access_key_id": "AKIAEXAMPLE",
        }
        with pytest.raises(Exception, match="together"):
            await _test_bedrock_lightweight_health(pending_credentials)

    @pytest.mark.asyncio
    async def test_dispatch_passes_credentials_through(self, monkeypatch):
        """`test_lightweight_health`'s bedrock branch must forward its
        `credentials` argument rather than dropping it."""
        _patch_bedrock_config(monkeypatch, region="")  # saved config has no region

        await run_lightweight_health_test(
            provider="bedrock",
            credentials={"aws_region_name": "eu-central-1"},
        )  # must not raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
