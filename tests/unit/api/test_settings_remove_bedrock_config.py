"""Regression test for removing AWS Bedrock via `remove_provider_config`.

Bedrock has its own typed `providers.bedrock` field (region/access_key_id/
secret_access_key/configured) rather than a `.custom` entry. Before this fix,
the generic `remove_provider_config` handling in `update_settings()` only did
`del working_config.providers.custom[provider]`, which is a no-op for
Bedrock - the frontend's "remove" action (provider-settings-dialog.tsx sends
`remove_provider_config=<provider>`) left Bedrock's `configured` flag `True`
and its AWS keys still saved, even though `GET /settings` looked like it had
been removed.
"""

from types import SimpleNamespace

import pytest

import api.settings as settings_api
import api.settings.endpoints as settings_endpoints


def _make_config():
    return SimpleNamespace(
        edited=True,
        agent=SimpleNamespace(llm_provider="openai", llm_model="gpt-4o"),
        knowledge=SimpleNamespace(
            embedding_provider="bedrock",
            embedding_model="cohere.embed-multilingual-v3",
            index_name="documents",
        ),
        providers=SimpleNamespace(
            openai=SimpleNamespace(configured=True, api_key="sk-test"),
            anthropic=SimpleNamespace(configured=False),
            watsonx=SimpleNamespace(configured=False),
            ollama=SimpleNamespace(configured=False),
            bedrock=SimpleNamespace(
                region="eu-central-1",
                access_key_id="AKIAEXAMPLE",
                secret_access_key="supersecret",
                configured=True,
            ),
            custom={},
        ),
    )


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    """Neutralize everything update_settings() does after the config mutation
    that isn't the concern of this test (persistence, Langflow sync, telemetry)."""

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(settings_endpoints.config_manager, "save_config_file", lambda cfg: True)
    monkeypatch.setattr(settings_endpoints.clients, "refresh_patched_client", _noop)
    monkeypatch.setattr(settings_endpoints.TelemetryClient, "send_event", _noop)
    monkeypatch.setattr(
        settings_endpoints, "_run_async_post_save_langflow_updates", _noop, raising=True
    )

    class _FakeTask:
        def add_done_callback(self, _callback):
            pass

    def _fake_create_task(coro):
        coro.close()
        return _FakeTask()

    monkeypatch.setattr(settings_endpoints.asyncio, "create_task", _fake_create_task, raising=True)


@pytest.mark.asyncio
async def test_remove_provider_config_bedrock_clears_typed_fields(monkeypatch):
    config = _make_config()
    monkeypatch.setattr(settings_endpoints, "get_openrag_config", lambda: config, raising=True)

    saved_configs = []
    monkeypatch.setattr(
        settings_endpoints.config_manager,
        "save_config_file",
        lambda updated_config: saved_configs.append(updated_config) or True,
    )

    response = await settings_api.update_settings(
        settings_api.SettingsUpdateBody(remove_provider_config="bedrock"),
        session_manager=object(),
        user=None,
    )

    # Not the 400 "configure another provider first" rejection: openai is
    # configured, so removal must be allowed to proceed.
    assert not hasattr(response, "status_code") or response.status_code not in (400, 500)

    saved = saved_configs[0]
    assert saved.providers.bedrock.configured is False
    assert saved.providers.bedrock.region == ""
    assert saved.providers.bedrock.access_key_id == ""
    assert saved.providers.bedrock.secret_access_key == ""
    # Bedrock was the active embedding provider; it must fall back rather
    # than leave embedding_provider pointing at a just-removed provider.
    assert saved.knowledge.embedding_provider == "openai"


@pytest.mark.asyncio
async def test_remove_provider_config_bedrock_rejected_when_sole_provider(monkeypatch):
    """Mirrors remove_openai_config/remove_watsonx_config: removal must be
    refused when Bedrock is the only configured provider."""
    config = _make_config()
    config.providers.openai.configured = False
    monkeypatch.setattr(settings_endpoints, "get_openrag_config", lambda: config, raising=True)

    response = await settings_api.update_settings(
        settings_api.SettingsUpdateBody(remove_provider_config="bedrock"),
        session_manager=object(),
        user=None,
    )

    assert response.status_code == 400
    # Nothing was mutated on the live config.
    assert config.providers.bedrock.configured is True
