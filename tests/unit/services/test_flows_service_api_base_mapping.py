"""Coverage for the new "openai" -> OPENAI_API_BASE entry in
FlowsService._update_component_fields's field_mappings["api_base"] table
(openrag issue #2060). This lets the Langflow-flow ingest path's Embedding
Model component pick up the custom OpenAI base-URL override via the
OPENAI_API_BASE Langflow global variable, the same way the pre-existing
Ollama entry wires up OLLAMA_BASE_URL.

The template dict intentionally omits a "model" key so
_update_component_fields skips the (Langflow-API-calling) model-update
branch entirely and goes straight to the field_mappings loop we care about -
keeping this a true unit test with no Langflow HTTP calls involved.
"""

import pytest

from services.flows_service import FlowsService


def _api_base_template():
    return {"api_base": {"value": "", "load_from_db": False}}


@pytest.mark.asyncio
class TestApiBaseFieldMapping:
    async def test_openai_provider_maps_to_openai_api_base_global_var(self):
        service = FlowsService()
        component_node = {"data": {"node": {"template": _api_base_template()}}}

        updated = await service._update_component_fields(
            component_node, provider="openai", model_value="text-embedding-3-small"
        )

        template = component_node["data"]["node"]["template"]
        assert updated is True
        assert template["api_base"]["value"] == "OPENAI_API_BASE"
        assert template["api_base"]["load_from_db"] is True

    async def test_ollama_provider_still_maps_to_ollama_base_url(self):
        """Regression guard: adding the openai entry must not disturb the
        pre-existing ollama mapping in the same field_mappings["api_base"] dict."""
        service = FlowsService()
        component_node = {"data": {"node": {"template": _api_base_template()}}}

        await service._update_component_fields(
            component_node, provider="ollama", model_value="llama3"
        )

        template = component_node["data"]["node"]["template"]
        assert template["api_base"]["value"] == "OLLAMA_BASE_URL"
        assert template["api_base"]["load_from_db"] is True

    async def test_provider_without_api_base_mapping_clears_the_field(self):
        """Providers with no api_base entry (e.g. watsonx/anthropic) fall
        through to the "else" branch and clear the field."""
        service = FlowsService()
        component_node = {"data": {"node": {"template": _api_base_template()}}}

        await service._update_component_fields(
            component_node, provider="watsonx", model_value="some-model"
        )

        template = component_node["data"]["node"]["template"]
        assert template["api_base"]["value"] == ""
        assert template["api_base"]["load_from_db"] is False
