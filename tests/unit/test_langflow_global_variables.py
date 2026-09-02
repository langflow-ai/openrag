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

    names = {name for name, *_ in calls}
    assert ("OPENRAG_LLM_TOKEN", "None", True, "Credential") in calls
    assert "ANTHROPIC_API_KEY" not in names
    assert "WATSONX_APIKEY" not in names
    assert ("SELECTED_EMBEDDING_MODEL", "embedding-model", True, "Generic") in calls
    assert ("SELECTED_EMBEDDING_PROVIDER", "openai", True, "Generic") in calls
    assert ("SELECTED_EMBEDDING_MODEL_PROVIDER", "OpenAI", True, "Generic") in calls
    assert ("SELECTED_LANGUAGE_MODEL_PROVIDER", "OpenAI", True, "Generic") in calls
    assert any(name == "OPENRAG_LLM_BASE_URL" for name, *_ in calls)


@pytest.mark.asyncio
async def test_ensure_required_langflow_global_variables_creates_generics_and_credential_placeholders(
    monkeypatch,
):
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
async def test_update_langflow_global_variables_continues_when_one_fails(monkeypatch):
    """One failing upsert must not abort the rest; errors are aggregated (PR #2267)."""
    calls = []
    attempted_names = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        attempted_names.append(name)
        if name == "OPENRAG_LLM_BASE_URL":
            raise RuntimeError("Simulated network failure on OPENRAG_LLM_BASE_URL")
        calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients,
        "_create_langflow_global_variable",
        create_variable,
        raising=True,
    )

    config = SimpleNamespace(
        knowledge=SimpleNamespace(embedding_model="embedding-model"),
        agent=SimpleNamespace(llm_model="llm-model"),
    )

    with pytest.raises(RuntimeError) as exc_info:
        await langflow_sync._update_langflow_global_variables(config)

    assert "OPENRAG_LLM_BASE_URL" in str(exc_info.value)
    assert "OPENRAG_LLM_BASE_URL" in attempted_names

    names = {name for name, *_ in calls}
    assert "OPENRAG_LLM_BASE_URL" not in names
    assert "SELECTED_EMBEDDING_MODEL" in names
    assert "SELECTED_LANGUAGE_MODEL" in names
    assert langflow_sync.LANGFLOW_RUNTIME_CREDENTIAL_PLACEHOLDERS <= names


@pytest.mark.asyncio
async def test_model_change_pushes_selected_model_globals(monkeypatch):
    """A model-only settings change must reach Langflow.

    The flows use one OpenAI-compatible component per kind, so
    `change_langflow_model_value` finds no per-provider node to patch and the
    SELECTED_*_MODEL global variables are the only channel left. Those globals
    used to be written solely when provider credentials changed, which left the
    retrieval flow embedding with — and labelling chunks as — the previous
    model until some unrelated credential edit happened to resync it.
    """
    upserts: list[tuple[str, str]] = []

    async def fake_upsert(name, value, **kwargs):
        upserts.append((name, value))

    monkeypatch.setattr(langflow_sync, "_upsert_langflow_global_variable", fake_upsert)

    class _FlowsService:
        def __init__(self):
            self.calls = []

        async def change_langflow_model_value(self, provider, **kwargs):
            self.calls.append((provider, kwargs))
            return {"updated": []}

    config = SimpleNamespace(
        agent=SimpleNamespace(llm_model="gpt-4o-mini", llm_provider="openai"),
        knowledge=SimpleNamespace(
            embedding_model="ibm/slate-125m-english-rtrvr-v2",
            embedding_provider="watsonx",
        ),
    )

    await langflow_sync._update_langflow_model_values(
        config,
        _FlowsService(),
        embedding_model="ibm/slate-125m-english-rtrvr-v2",
        embedding_provider="watsonx",
    )

    assert ("SELECTED_EMBEDDING_MODEL", "ibm/slate-125m-english-rtrvr-v2") in upserts
    assert ("SELECTED_EMBEDDING_PROVIDER", "watsonx") in upserts
    assert not any(name == "SELECTED_LANGUAGE_MODEL" for name, _ in upserts)


@pytest.mark.asyncio
async def test_llm_model_change_pushes_selected_language_model(monkeypatch):
    upserts: list[tuple[str, str]] = []

    async def fake_upsert(name, value, **kwargs):
        upserts.append((name, value))

    monkeypatch.setattr(langflow_sync, "_upsert_langflow_global_variable", fake_upsert)

    class _FlowsService:
        async def change_langflow_model_value(self, provider, **kwargs):
            return {"updated": []}

    config = SimpleNamespace(
        agent=SimpleNamespace(llm_model="ibm/granite-4-h-small", llm_provider="watsonx"),
        knowledge=SimpleNamespace(embedding_model="", embedding_provider="watsonx"),
    )

    await langflow_sync._update_langflow_model_values(
        config,
        _FlowsService(),
        llm_model="ibm/granite-4-h-small",
        llm_provider="watsonx",
    )

    assert ("SELECTED_LANGUAGE_MODEL", "ibm/granite-4-h-small") in upserts


@pytest.mark.asyncio
async def test_selected_model_upsert_failure_is_not_fatal(monkeypatch):
    async def boom(name, value, **kwargs):
        raise RuntimeError("langflow down")

    monkeypatch.setattr(langflow_sync, "_upsert_langflow_global_variable", boom)

    calls = []

    class _FlowsService:
        async def change_langflow_model_value(self, provider, **kwargs):
            calls.append(provider)
            return {"updated": []}

    config = SimpleNamespace(
        agent=SimpleNamespace(llm_model="gpt-4o-mini", llm_provider="openai"),
        knowledge=SimpleNamespace(
            embedding_model="text-embedding-3-small", embedding_provider="openai"
        ),
    )

    await langflow_sync._update_langflow_model_values(
        config,
        _FlowsService(),
        embedding_model="text-embedding-3-small",
        embedding_provider="openai",
    )

    assert calls == ["openai"]


# --- guards carried over from main (#2265) -------------------------------
# Those tests exercised OLLAMA_BASE_URL / WATSONX_URL / WATSONX_PROJECT_ID.
# This branch stops publishing vendor endpoints to Langflow entirely - the
# /v1 proxy holds the credentials - so those names are no longer in
# LANGFLOW_GENERIC_GLOBAL_VARIABLES and the originals would have passed
# vacuously. They are retargeted at OPENRAG_LLM_BASE_URL, which is generic
# and can still resolve to "" when the proxy URL is not derivable.


def _patch_llm_base_url(monkeypatch, value: str) -> None:
    monkeypatch.setattr(
        langflow_sync.settings, "get_langflow_llm_base_url", lambda: value, raising=True
    )


def _stub_langflow(monkeypatch, existing=None, calls=None):
    async def mock_langflow_request(method, endpoint, **kwargs):
        if calls is not None:
            calls.append((method, endpoint, kwargs))
        if method == "GET":
            return _Response(json_data=existing or [])
        if method == "DELETE":
            return _Response(status_code=204)
        return _Response(status_code=201)

    monkeypatch.setattr(
        langflow_sync.clients, "langflow_request", mock_langflow_request, raising=True
    )


@pytest.mark.asyncio
async def test_ensure_required_globals_skips_creating_empty_valued_variables(monkeypatch):
    """Langflow answers 400 "Variable value cannot be empty" for a blank value.

    Creating one anyway logs a "Failed to create Langflow global variable"
    warning on every boot.
    """
    _stub_langflow(monkeypatch)
    _patch_llm_base_url(monkeypatch, "")

    create_calls = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        create_calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients, "_create_langflow_global_variable", create_variable, raising=True
    )

    config = SimpleNamespace(providers=SimpleNamespace(), knowledge=SimpleNamespace())
    await langflow_sync.ensure_required_langflow_global_variables(config)

    created = {name for name, *_ in create_calls}
    assert "OPENRAG_LLM_BASE_URL" not in created
    # Variables that do have a value are still created.
    assert "OPENSEARCH_INDEX_NAME" in created
    assert all(value for _, value, *_ in create_calls)


@pytest.mark.asyncio
async def test_ensure_required_globals_creates_the_variable_once_it_has_a_value(monkeypatch):
    _stub_langflow(monkeypatch)
    _patch_llm_base_url(monkeypatch, "http://openrag-backend:8000/v1")

    create_calls = []

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        create_calls.append((name, value, modify, variable_type))

    monkeypatch.setattr(
        langflow_sync.clients, "_create_langflow_global_variable", create_variable, raising=True
    )

    config = SimpleNamespace(providers=SimpleNamespace(), knowledge=SimpleNamespace())
    await langflow_sync.ensure_required_langflow_global_variables(config)

    assert (
        "OPENRAG_LLM_BASE_URL",
        "http://openrag-backend:8000/v1",
        True,
        "Generic",
    ) in create_calls


@pytest.mark.asyncio
async def test_ensure_required_globals_does_not_blank_an_existing_value(monkeypatch):
    """An empty target must never overwrite what Langflow already holds."""
    calls = []
    _stub_langflow(
        monkeypatch,
        existing=[
            {
                "id": "var-1",
                "name": "OPENRAG_LLM_BASE_URL",
                "value": "http://openrag-backend:8000/v1",
                "type": "Generic",
                "default_fields": [],
            }
        ],
        calls=calls,
    )
    _patch_llm_base_url(monkeypatch, "")

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        pass

    monkeypatch.setattr(
        langflow_sync.clients, "_create_langflow_global_variable", create_variable, raising=True
    )

    config = SimpleNamespace(providers=SimpleNamespace(), knowledge=SimpleNamespace())
    await langflow_sync.ensure_required_langflow_global_variables(config)

    patched = [c for c in calls if c[0] == "PATCH" and "var-1" in c[1]]
    assert patched == []


@pytest.mark.asyncio
async def test_ensure_required_globals_defers_type_migration_when_value_is_empty(monkeypatch):
    """The DELETE lands before the recreate, so a refused POST would drop it."""
    calls = []
    _stub_langflow(
        monkeypatch,
        existing=[
            {
                "id": "var-1",
                "name": "OPENRAG_LLM_BASE_URL",
                "value": "",
                "type": "Credential",
                "default_fields": [],
            }
        ],
        calls=calls,
    )
    _patch_llm_base_url(monkeypatch, "")

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        pass

    monkeypatch.setattr(
        langflow_sync.clients, "_create_langflow_global_variable", create_variable, raising=True
    )

    config = SimpleNamespace(providers=SimpleNamespace(), knowledge=SimpleNamespace())
    await langflow_sync.ensure_required_langflow_global_variables(config)

    touched = [c for c in calls if "var-1" in c[1]]
    assert touched == []


@pytest.mark.asyncio
async def test_ensure_required_globals_migration_keeps_the_value_when_target_empty(monkeypatch):
    """A Credential->Generic migration must not recreate the variable with ""."""
    calls = []
    _stub_langflow(
        monkeypatch,
        existing=[
            {
                "id": "var-1",
                "name": "OPENRAG_LLM_BASE_URL",
                "value": "http://openrag-backend:8000/v1",
                "type": "Credential",
                "default_fields": [],
            }
        ],
        calls=calls,
    )
    _patch_llm_base_url(monkeypatch, "")

    async def create_variable(name, value, modify=False, variable_type="Credential"):
        pass

    monkeypatch.setattr(
        langflow_sync.clients, "_create_langflow_global_variable", create_variable, raising=True
    )

    config = SimpleNamespace(providers=SimpleNamespace(), knowledge=SimpleNamespace())
    await langflow_sync.ensure_required_langflow_global_variables(config)

    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 1
    # Recreated as Generic, carrying the value Langflow already held.
    assert posts[0][2]["json"]["value"] == "http://openrag-backend:8000/v1"
    assert posts[0][2]["json"]["type"] == "Generic"
