"""Unit tests for the OCI branches of the models-listing endpoints:
``api.models.get_oci_models`` (internal ``/models/oci`` route handler) and
``api.v1.models._fetch_models`` (public ``/v1/models/{provider}`` dispatch).

Both are static-list, credential-free lookups (see
``ModelsService.get_oci_models``), unlike the WatsonX/OpenAI/Anthropic/
Ollama handlers they sit next to.
"""

import json
from types import SimpleNamespace

import pytest

from api.models import get_oci_models
from api.v1.models import _fetch_models
from services.model_catalog import is_known_provider
from services.models_service import ModelsService


def _body(response) -> dict:
    return json.loads(bytes(response.body))


class TestGetOciModelsHandler:
    @pytest.mark.asyncio
    async def test_returns_static_model_list(self):
        response = await get_oci_models(body=None, models_service=ModelsService(), user=None)

        assert response.status_code == 200
        payload = _body(response)
        assert payload["language_models"] == []
        values = {m["value"] for m in payload["embedding_models"]}
        assert "cohere.embed-multilingual-v3.0" in values

    @pytest.mark.asyncio
    async def test_no_credentials_required(self):
        """Unlike get_ibm_models, this must succeed with an empty body."""
        response = await get_oci_models(models_service=ModelsService(), user=None)
        assert response.status_code == 200


class TestFetchModelsOciDispatch:
    def test_oci_is_a_valid_provider(self):
        assert is_known_provider("oci")

    @pytest.mark.asyncio
    async def test_dispatches_to_get_oci_models_without_requiring_credentials(self):
        # No providers.oci credentials configured at all -- must still succeed,
        # unlike watsonx/openai which 400 without configured credentials.
        config = SimpleNamespace(providers=SimpleNamespace())
        models, error_response = await _fetch_models("oci", config, ModelsService())

        assert error_response is None
        assert models is not None
        values = {m["value"] for m in models["embedding_models"]}
        assert "cohere.embed-multilingual-v3.0" in values
