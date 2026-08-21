from types import SimpleNamespace

import pytest

from api.settings import langflow_sync
from config.settings import AppClients


class _Response:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


@pytest.mark.asyncio
async def test_create_langflow_global_variable_uses_requested_type():
    client = AppClients()
    calls = []

    async def langflow_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        return _Response(status_code=201)

    client.langflow_request = langflow_request

    await client._create_langflow_global_variable(
        "SELECTED_EMBEDDING_MODEL",
        "text-embedding-3-small",
        variable_type="Generic",
    )

    assert calls == [
        (
            "POST",
            "/api/v1/variables/",
            {
                "json": {
                    "name": "SELECTED_EMBEDDING_MODEL",
                    "value": "text-embedding-3-small",
                    "default_fields": [],
                    "type": "Generic",
                }
            },
        )
    ]


@pytest.mark.asyncio
async def test_update_langflow_global_variable_recreates_when_type_changes():
    client = AppClients()
    calls = []

    async def langflow_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(
                json_data=[
                    {
                        "id": "var-1",
                        "name": "OPENSEARCH_INDEX_NAME",
                        "value": "documents",
                        "type": "Credential",
                        "default_fields": ["OpenRAG", "Index"],
                    }
                ]
            )
        if method == "DELETE":
            return _Response(status_code=204)
        return _Response(status_code=201)

    client.langflow_request = langflow_request

    await client._update_langflow_global_variable(
        "OPENSEARCH_INDEX_NAME", "documents-v2", variable_type="Generic"
    )

    assert calls == [
        ("GET", "/api/v1/variables/", {}),
        ("DELETE", "/api/v1/variables/var-1", {}),
        (
            "POST",
            "/api/v1/variables/",
            {
                "json": {
                    "name": "OPENSEARCH_INDEX_NAME",
                    "value": "documents-v2",
                    "default_fields": ["OpenRAG", "Index"],
                    "type": "Generic",
                }
            },
        ),
    ]


@pytest.mark.asyncio
async def test_update_langflow_global_variable_patches_when_type_matches():
    client = AppClients()
    calls = []

    async def langflow_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(
                json_data=[
                    {
                        "id": "var-1",
                        "name": "OPENAI_API_KEY",
                        "value": "old",
                        "type": "Credential",
                        "default_fields": ["OpenAI", "OpenAI API Key"],
                    }
                ]
            )
        return _Response(status_code=200)

    client.langflow_request = langflow_request

    await client._update_langflow_global_variable(
        "OPENAI_API_KEY", "new-secret", variable_type="Credential"
    )

    assert calls == [
        ("GET", "/api/v1/variables/", {}),
        (
            "PATCH",
            "/api/v1/variables/var-1",
            {
                "json": {
                    "id": "var-1",
                    "name": "OPENAI_API_KEY",
                    "value": "new-secret",
                    "default_fields": ["OpenAI", "OpenAI API Key"],
                    "type": "Credential",
                }
            },
        ),
    ]


@pytest.mark.asyncio
async def test_update_langflow_global_variables_marks_non_secret_provider_fields_generic(
    monkeypatch,
):
    calls = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    config = SimpleNamespace(
        providers=SimpleNamespace(
            watsonx=SimpleNamespace(
                api_key="watson-key",
                project_id="watson-project",
                endpoint="https://watson.example",
            ),
            openai=SimpleNamespace(api_key="openai-key"),
            anthropic=SimpleNamespace(api_key="anthropic-key"),
            ollama=SimpleNamespace(endpoint="http://ollama.local"),
        ),
        knowledge=SimpleNamespace(
            embedding_model="embedding-model",
            embedding_provider=None,
        ),
        agent=SimpleNamespace(
            llm_model=None,
            llm_provider=None,
        ),
    )

    async def resolve_ollama_url(endpoint, force_refresh=False):
        return endpoint

    flows_service = SimpleNamespace(resolve_ollama_url=resolve_ollama_url)

    await langflow_sync._update_langflow_global_variables(config, flows_service=flows_service)

    names = {name for name, *_ in calls}
    assert ("OPENRAG_LLM_TOKEN", "None", True, "Credential") in calls
    assert "ANTHROPIC_API_KEY" not in names
    assert "WATSONX_APIKEY" not in names
    assert ("SELECTED_EMBEDDING_MODEL", "embedding-model", True, "Generic") in calls
    assert ("SELECTED_EMBEDDING_MODEL_PROVIDER", "OpenAI", True, "Generic") in calls
    assert ("SELECTED_LANGUAGE_MODEL_PROVIDER", "OpenAI", True, "Generic") in calls
    assert any(name == "OPENRAG_LLM_BASE_URL" for name, *_ in calls)


@pytest.mark.asyncio
async def test_ensure_required_langflow_global_variables_creates_generics_and_credential_placeholders(
    monkeypatch,
):
    calls = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    config = SimpleNamespace(
        providers=SimpleNamespace(
            watsonx=SimpleNamespace(project_id="project", endpoint="https://watson.example"),
            ollama=SimpleNamespace(endpoint="http://ollama.local"),
        ),
        knowledge=SimpleNamespace(
            embedding_model="text-embedding-3-large",
            index_name="documents-v2",
        ),
    )

    await langflow_sync.ensure_required_langflow_global_variables(config)

    names = {name for name, *_ in calls}
    assert langflow_sync.LANGFLOW_GENERIC_GLOBAL_VARIABLES <= names
    assert langflow_sync.LANGFLOW_RUNTIME_CREDENTIAL_PLACEHOLDERS <= names
    generic_calls = [c for c in calls if c[3] == "Generic"]
    credential_calls = [c for c in calls if c[3] == "Credential"]
    assert generic_calls
    assert all(variable_type == "Generic" for *_, variable_type in generic_calls)
    assert ("OPENSEARCH_INDEX_NAME", "documents-v2", True, "Generic") in calls
    assert ("SELECTED_EMBEDDING_MODEL", "text-embedding-3-large", True, "Generic") in calls
    assert ("OPENRAG_LLM_TOKEN", "None", True, "Credential") in credential_calls


@pytest.mark.asyncio
async def test_update_langflow_global_variable_overwrites_redacted_credential():
    """Langflow GET hides Credential values as null; still PATCH a placeholder."""
    client = AppClients()
    calls = []

    async def langflow_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(
                json_data=[
                    {
                        "id": "var-token",
                        "name": "OPENRAG_LLM_TOKEN",
                        "value": None,
                        "type": "Credential",
                        "default_fields": [],
                    }
                ]
            )
        return _Response(status_code=200)

    client.langflow_request = langflow_request

    await client._update_langflow_global_variable(
        "OPENRAG_LLM_TOKEN", "None", variable_type="Credential"
    )

    assert calls == [
        ("GET", "/api/v1/variables/", {}),
        (
            "PATCH",
            "/api/v1/variables/var-token",
            {
                "json": {
                    "id": "var-token",
                    "name": "OPENRAG_LLM_TOKEN",
                    "value": "None",
                    "default_fields": [],
                    "type": "Credential",
                }
            },
        ),
    ]
