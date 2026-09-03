"""Unit tests for the AWS Bedrock model-listing endpoints.

Covers `api.models.get_bedrock_models` (internal `/models/bedrock` route
handler) and the `bedrock` dispatch branch in `api.v1.models._fetch_models`
(public `/v1/models/{provider}` route).
"""

import json
from types import SimpleNamespace

import pytest

from api.models import BedrockBody, get_bedrock_models
from api.v1.models import VALID_PROVIDERS, _fetch_models
from services.models_service import ModelsService


class TestApiModelsGetBedrockModels:
    @pytest.mark.asyncio
    async def test_returns_static_list_without_body(self):
        response = await get_bedrock_models(body=None, models_service=ModelsService())

        assert response.status_code == 200
        payload = json.loads(response.body)
        assert payload["language_models"] == []
        values = {m["value"] for m in payload["embedding_models"]}
        assert "cohere.embed-multilingual-v3" in values

    @pytest.mark.asyncio
    async def test_body_is_optional_and_unused_for_the_static_list(self):
        """Region isn't needed to list the static models - only to actually
        route a call, which happens later via config, not this endpoint."""
        response = await get_bedrock_models(
            body=BedrockBody(region="eu-central-1"), models_service=ModelsService()
        )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_service_error_returns_500(self):
        class ExplodingModelsService:
            async def get_bedrock_models(self):
                raise RuntimeError("boom")

        response = await get_bedrock_models(
            body=None, models_service=ExplodingModelsService()
        )

        assert response.status_code == 500


class TestV1ModelsBedrockDispatch:
    def test_bedrock_is_a_valid_provider(self):
        assert "bedrock" in VALID_PROVIDERS

    @pytest.mark.asyncio
    async def test_fetch_models_dispatches_to_bedrock_without_requiring_credentials(self):
        """Unlike watsonx, the bedrock branch must not 400 for missing
        api_key/endpoint/project_id - the model list is static."""
        config = SimpleNamespace(
            providers=SimpleNamespace(
                bedrock=SimpleNamespace(region="", access_key_id="", secret_access_key=""),
            )
        )

        models, error_response = await _fetch_models("bedrock", config, ModelsService())

        assert error_response is None
        values = {m["value"] for m in models["embedding_models"]}
        assert "cohere.embed-multilingual-v3" in values


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
