from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.settings as settings_api
import api.settings.endpoints as settings_endpoints


def _make_config(index_name="documents"):
    return SimpleNamespace(
        edited=True,
        agent=SimpleNamespace(llm_provider="openai", llm_model="gpt-4o"),
        knowledge=SimpleNamespace(
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
            index_name=index_name,
        ),
        providers=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_update_settings_rejects_index_name_outside_security_role_patterns(monkeypatch):
    config = _make_config()
    monkeypatch.setattr(settings_endpoints, "get_openrag_config", lambda: config, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await settings_api.update_settings(
            settings_api.SettingsUpdateBody(index_name="test"),
            session_manager=object(),
            user=None,
        )

    assert exc_info.value.status_code == 422
    # The rejected index name is not permitted, so it must never be written to config.
    assert config.knowledge.index_name == "documents"


@pytest.mark.asyncio
async def test_update_settings_accepts_index_name_matching_security_role_patterns(monkeypatch):
    config = _make_config()
    monkeypatch.setattr(settings_endpoints, "get_openrag_config", lambda: config, raising=True)
    monkeypatch.setattr(
        settings_endpoints.config_manager,
        "save_config_file",
        lambda updated_config: True,
        raising=True,
    )

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(
        settings_endpoints.clients, "_create_langflow_global_variable", _noop, raising=True
    )
    monkeypatch.setattr(settings_endpoints.TelemetryClient, "send_event", _noop, raising=True)
    monkeypatch.setattr(
        settings_endpoints, "_run_async_post_save_langflow_updates", _noop, raising=True
    )
    monkeypatch.setattr(
        settings_endpoints.asyncio, "create_task", lambda coro: coro.close(), raising=True
    )

    await settings_api.update_settings(
        settings_api.SettingsUpdateBody(index_name="documents-v2"),
        session_manager=object(),
        user=None,
    )

    assert config.knowledge.index_name == "documents-v2"
