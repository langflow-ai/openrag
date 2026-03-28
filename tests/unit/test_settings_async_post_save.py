from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.settings as settings_api


class _FakeTask:
    def __init__(self):
        self.done_callback = None

    def add_done_callback(self, cb):
        self.done_callback = cb


def _make_config_for_ollama_removal():
    providers = SimpleNamespace(
        openai=SimpleNamespace(api_key="openai-key", configured=True),
        anthropic=SimpleNamespace(api_key="", configured=False),
        watsonx=SimpleNamespace(
            api_key="",
            endpoint="",
            project_id="",
            configured=False,
        ),
        ollama=SimpleNamespace(endpoint="http://localhost:11434", configured=True),
    )
    return SimpleNamespace(
        edited=True,
        agent=SimpleNamespace(llm_provider="ollama", llm_model="llama3.2"),
        knowledge=SimpleNamespace(
            embedding_provider="ollama",
            embedding_model="nomic-embed-text",
        ),
        providers=providers,
    )


@pytest.mark.asyncio
async def test_update_settings_retains_background_task_reference(monkeypatch):
    settings_api._background_tasks.clear()
    config = _make_config_for_ollama_removal()
    fake_task = _FakeTask()
    post_save_mock = AsyncMock()

    async def _noop_refresh():
        return None

    def _fake_create_task(coro):
        # We only need to validate scheduling behavior in this unit test.
        coro.close()
        return fake_task

    monkeypatch.setattr(settings_api, "get_openrag_config", lambda: config, raising=True)
    monkeypatch.setattr(
        settings_api.config_manager,
        "save_config_file",
        lambda updated_config: True,
        raising=True,
    )
    monkeypatch.setattr(
        settings_api.clients,
        "refresh_patched_client",
        _noop_refresh,
        raising=True,
    )
    monkeypatch.setattr(settings_api.TelemetryClient, "send_event", AsyncMock(), raising=True)
    monkeypatch.setattr(
        settings_api,
        "_run_async_post_save_langflow_updates",
        post_save_mock,
        raising=True,
    )
    monkeypatch.setattr(settings_api.asyncio, "create_task", _fake_create_task, raising=True)

    response = await settings_api.update_settings(
        settings_api.SettingsUpdateBody(remove_ollama_config=True),
        session_manager=object(),
        user=None,
    )

    assert isinstance(response, settings_api.SettingsUpdateResponse)
    assert fake_task in settings_api._background_tasks
    assert fake_task.done_callback is not None
    fake_task.done_callback(fake_task)
    assert fake_task not in settings_api._background_tasks


@pytest.mark.asyncio
async def test_provider_removal_triggers_mcp_server_update(monkeypatch):
    settings_api._background_tasks.clear()
    config = _make_config_for_ollama_removal()
    post_save_mock = AsyncMock()
    fake_task = _FakeTask()

    async def _noop_refresh():
        return None

    def _fake_create_task(coro):
        coro.close()
        return fake_task

    monkeypatch.setattr(settings_api, "get_openrag_config", lambda: config, raising=True)
    monkeypatch.setattr(
        settings_api.config_manager,
        "save_config_file",
        lambda updated_config: True,
        raising=True,
    )
    monkeypatch.setattr(
        settings_api.clients,
        "refresh_patched_client",
        _noop_refresh,
        raising=True,
    )
    monkeypatch.setattr(settings_api.TelemetryClient, "send_event", AsyncMock(), raising=True)
    monkeypatch.setattr(
        settings_api,
        "_run_async_post_save_langflow_updates",
        post_save_mock,
        raising=True,
    )
    monkeypatch.setattr(settings_api.asyncio, "create_task", _fake_create_task, raising=True)

    await settings_api.update_settings(
        settings_api.SettingsUpdateBody(remove_ollama_config=True),
        session_manager=object(),
        user=None,
    )

    assert post_save_mock.call_count == 1
    kwargs = post_save_mock.call_args.kwargs
    assert kwargs["update_mcp_servers"] is True
    assert kwargs["update_model_values"] is True

