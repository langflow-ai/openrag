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
                    "default_fields": [],
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
                    "default_fields": [],
                    "type": "Credential",
                }
            },
        ),
    ]


@pytest.mark.asyncio
async def test_ensure_required_langflow_global_variables_removes_apply_to_fields(monkeypatch):
    langflow_calls = []

    async def mock_langflow_request(method, endpoint, **kwargs):
        langflow_calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(
                json_data=[
                    {
                        "id": "var-1",
                        "name": "OPENAI_API_KEY",
                        "value": "secret",
                        "type": "Credential",
                        "default_fields": ["OpenAI", "api_key"],
                    },
                    {
                        "id": "var-2",
                        "name": "DOCLING_SERVE_URL",
                        "value": langflow_sync.settings.get_langflow_docling_url(),
                        "type": "Generic",
                        "default_fields": [],
                    },
                ]
            )
        return _Response(status_code=200)

    monkeypatch.setattr(
        langflow_sync.clients,
        "langflow_request",
        mock_langflow_request,
        raising=True,
    )

    create_calls = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        create_calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    config = SimpleNamespace(
        providers=SimpleNamespace(),
        knowledge=SimpleNamespace(),
    )

    await langflow_sync.ensure_required_langflow_global_variables(config)

    # Verify PATCH call was made to remove default_fields from var-1
    patch_calls = [c for c in langflow_calls if c[0] == "PATCH"]
    assert len(patch_calls) == 1
    assert patch_calls[0] == (
        "PATCH",
        "/api/v1/variables/var-1",
        {
            "json": {
                "id": "var-1",
                "name": "OPENAI_API_KEY",
                "default_fields": [],
                "type": "Credential",
            }
        },
    )


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

    assert ("WATSONX_APIKEY", "watson-key", True, "Credential") in calls
    assert ("OPENAI_API_KEY", "openai-key", True, "Credential") in calls
    assert ("ANTHROPIC_API_KEY", "anthropic-key", True, "Credential") in calls
    assert ("WATSONX_PROJECT_ID", "watson-project", True, "Generic") in calls
    assert ("WATSONX_URL", "https://watson.example", True, "Generic") in calls
    assert ("OLLAMA_BASE_URL", "http://ollama.local", True, "Generic") in calls
    assert ("SELECTED_EMBEDDING_MODEL", "embedding-model", True, "Generic") in calls


@pytest.mark.asyncio
async def test_ensure_required_langflow_global_variables_creates_all_generics(monkeypatch):
    calls = []

    async def mock_langflow_request(method, endpoint, **kwargs):
        if method == "GET":
            return _Response(status_code=200, json_data=[])
        return _Response(status_code=200)

    monkeypatch.setattr(
        langflow_sync.clients,
        "langflow_request",
        mock_langflow_request,
        raising=True,
    )

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
    assert all(variable_type == "Generic" for *_, variable_type in calls)
    assert ("OPENSEARCH_INDEX_NAME", "documents-v2", True, "Generic") in calls
    assert ("SELECTED_EMBEDDING_MODEL", "text-embedding-3-large", True, "Generic") in calls


@pytest.mark.asyncio
async def test_update_langflow_global_variables_continues_when_one_fails(monkeypatch):
    calls = []
    attempted_names = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        attempted_names.append(name)
        if name == "WATSONX_APIKEY":
            raise RuntimeError("Simulated network failure on WATSONX_APIKEY")
        calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    config = SimpleNamespace(
        providers=SimpleNamespace(
            watsonx=SimpleNamespace(api_key="watson-key", project_id="watson-project"),
            openai=SimpleNamespace(api_key="openai-key"),
        ),
        knowledge=SimpleNamespace(embedding_model="embedding-model", embedding_provider=None),
        agent=SimpleNamespace(llm_model=None, llm_provider=None),
    )

    # Calling sync should raise RuntimeError at the end because WATSONX_APIKEY failed,
    # but it should have attempted all other variables first.
    with pytest.raises(RuntimeError) as exc_info:
        await langflow_sync._update_langflow_global_variables(config)

    assert "WATSONX_APIKEY" in str(exc_info.value)
    assert "WATSONX_APIKEY" in attempted_names
    names = {name for name, *_ in calls}
    assert "WATSONX_APIKEY" not in names
    assert "WATSONX_PROJECT_ID" in names
    assert "OPENAI_API_KEY" in names
    assert "SELECTED_EMBEDDING_MODEL" in names


@pytest.mark.asyncio
async def test_ensure_required_langflow_global_variables_get_500_sends_no_post_requests(
    monkeypatch,
):
    langflow_calls = []

    async def mock_langflow_request(method, endpoint, **kwargs):
        langflow_calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(status_code=500, text="Internal Server Error")
        return _Response(status_code=200)

    monkeypatch.setattr(
        langflow_sync.clients,
        "langflow_request",
        mock_langflow_request,
        raising=True,
    )

    create_calls = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        create_calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    config = SimpleNamespace(
        providers=SimpleNamespace(),
        knowledge=SimpleNamespace(),
    )

    await langflow_sync.ensure_required_langflow_global_variables(config)

    assert len(create_calls) == 0
    assert len(langflow_calls) == 1
    assert langflow_calls[0][0] == "GET"


@pytest.mark.asyncio
async def test_ensure_required_langflow_global_variables_handles_failed_delete_post_patch(
    monkeypatch,
):
    langflow_calls = []

    async def mock_langflow_request(method, endpoint, **kwargs):
        langflow_calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(
                json_data=[
                    {
                        "id": "var-del-fail",
                        "name": "OPENSEARCH_INDEX_NAME",
                        "value": "documents",
                        "type": "Credential",
                    },
                    {
                        "id": "var-post-fail",
                        "name": "WATSONX_URL",
                        "value": "https://watson.example",
                        "type": "Credential",
                    },
                    {
                        "id": "var-patch-fail",
                        "name": "OPENAI_API_KEY",
                        "value": "secret",
                        "type": "Credential",
                        "default_fields": ["OpenAI", "api_key"],
                    },
                ]
            )
        if method == "DELETE" and "var-del-fail" in endpoint:
            return _Response(status_code=500)
        if method == "DELETE" and "var-post-fail" in endpoint:
            return _Response(status_code=204)
        if method == "POST" and endpoint == "/api/v1/variables/":
            return _Response(status_code=500)
        if method == "PATCH" and "var-patch-fail" in endpoint:
            return _Response(status_code=500)
        return _Response(status_code=200)

    monkeypatch.setattr(
        langflow_sync.clients,
        "langflow_request",
        mock_langflow_request,
        raising=True,
    )

    config = SimpleNamespace(
        providers=SimpleNamespace(),
        knowledge=SimpleNamespace(),
    )

    # Should complete without raising exception even though individual DELETE, POST, PATCH failed
    await langflow_sync.ensure_required_langflow_global_variables(config)

    methods = [c[0] for c in langflow_calls]
    assert "DELETE" in methods
    assert "POST" in methods
    assert "PATCH" in methods


@pytest.mark.asyncio
async def test_ensure_required_globals_skips_creating_empty_valued_variables(monkeypatch):
    """Unconfigured optional providers must not be POSTed to Langflow.

    Langflow answers 400 "Variable value cannot be empty", which the create
    helper reports as a generic "Failed to create Langflow global variable"
    warning on every boot.
    """

    async def mock_langflow_request(method, endpoint, **kwargs):
        if method == "GET":
            return _Response(json_data=[])
        return _Response(status_code=200)

    monkeypatch.setattr(
        langflow_sync.clients, "langflow_request", mock_langflow_request, raising=True
    )

    create_calls = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        create_calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    # No ollama / watsonx configured -> OLLAMA_BASE_URL, WATSONX_PROJECT_ID and
    # WATSONX_URL all resolve to "".
    config = SimpleNamespace(providers=SimpleNamespace(), knowledge=SimpleNamespace())

    await langflow_sync.ensure_required_langflow_global_variables(config)

    created = {name for name, *_ in create_calls}
    assert "OLLAMA_BASE_URL" not in created
    assert "WATSONX_PROJECT_ID" not in created
    assert "WATSONX_URL" not in created
    # Variables that do have a value are still created.
    assert "OPENSEARCH_INDEX_NAME" in created
    assert all(value for _, value, *_ in create_calls)


@pytest.mark.asyncio
async def test_ensure_required_globals_creates_optional_provider_var_once_configured(monkeypatch):
    async def mock_langflow_request(method, endpoint, **kwargs):
        if method == "GET":
            return _Response(json_data=[])
        return _Response(status_code=200)

    monkeypatch.setattr(
        langflow_sync.clients, "langflow_request", mock_langflow_request, raising=True
    )

    create_calls = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        create_calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    config = SimpleNamespace(
        providers=SimpleNamespace(ollama=SimpleNamespace(endpoint="http://localhost:11434")),
        knowledge=SimpleNamespace(),
    )

    await langflow_sync.ensure_required_langflow_global_variables(config)

    assert ("OLLAMA_BASE_URL", "http://localhost:11434", True, "Generic") in create_calls


@pytest.mark.asyncio
async def test_ensure_required_globals_does_not_blank_existing_value(monkeypatch):
    """An existing variable must not be PATCHed to "" when its provider is gone.

    Langflow rejects the empty value, so the PATCH would fail and log a warning
    every boot while leaving the stored value untouched anyway.
    """
    langflow_calls = []

    async def mock_langflow_request(method, endpoint, **kwargs):
        langflow_calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(
                json_data=[
                    {
                        "id": "var-1",
                        "name": "OLLAMA_BASE_URL",
                        "value": "http://localhost:11434",
                        "type": "Generic",
                        "default_fields": [],
                    }
                ]
            )
        return _Response(status_code=200)

    monkeypatch.setattr(
        langflow_sync.clients, "langflow_request", mock_langflow_request, raising=True
    )

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        pass

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    # ollama no longer configured -> target value is ""
    config = SimpleNamespace(providers=SimpleNamespace(), knowledge=SimpleNamespace())

    await langflow_sync.ensure_required_langflow_global_variables(config)

    assert [c for c in langflow_calls if c[0] == "PATCH"] == []


@pytest.mark.asyncio
async def test_ensure_required_globals_type_migration_keeps_value_when_target_empty(monkeypatch):
    """A Credential->Generic migration must not recreate the variable with "".

    The DELETE has already landed by then, so a 400 on the recreate would drop
    the variable entirely.
    """
    langflow_calls = []

    async def mock_langflow_request(method, endpoint, **kwargs):
        langflow_calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(
                json_data=[
                    {
                        "id": "var-1",
                        "name": "WATSONX_URL",
                        "value": "https://us-south.ml.cloud.ibm.com",
                        "type": "Credential",
                        "default_fields": [],
                    }
                ]
            )
        if method == "DELETE":
            return _Response(status_code=204)
        return _Response(status_code=201)

    monkeypatch.setattr(
        langflow_sync.clients, "langflow_request", mock_langflow_request, raising=True
    )

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        pass

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    config = SimpleNamespace(providers=SimpleNamespace(), knowledge=SimpleNamespace())

    await langflow_sync.ensure_required_langflow_global_variables(config)

    posts = [c for c in langflow_calls if c[0] == "POST"]
    assert len(posts) == 1
    # Recreated as Generic, but carrying the value Langflow already held.
    assert posts[0][2]["json"]["value"] == "https://us-south.ml.cloud.ibm.com"
    assert posts[0][2]["json"]["type"] == "Generic"
