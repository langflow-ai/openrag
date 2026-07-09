"""Unit tests for the OCI credential write path in
``api.settings.endpoints.update_settings``.

Regression coverage for the gap where ``SettingsUpdateBody``/``OnboardingBody``
accepted the 7 ``oci_*`` fields and ``remove_oci_config``, but
``update_settings`` had no branch that persisted them into
``config.providers.oci`` (only the GET /settings read path built the
response's ``OCIProviderConfig``). Mirrors the WatsonX write-path pattern
(multiple credential fields landing on ``current_config.providers.<name>``)
and the existing ``remove_ollama_config``/``remove_watsonx_config`` removal
tests in ``tests/unit/test_settings_async_post_save.py``.

Imports the ``api.settings.endpoints`` submodule directly (not the
``api.settings`` package) because the package's ``__init__.py`` does not
re-export ``_background_tasks``/``config_manager``/``clients``/etc. -- see
the two pre-existing failures in ``test_settings_async_post_save.py`` that
hit ``AttributeError: module 'api.settings' has no attribute
'_background_tasks'`` for exactly this reason.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.settings.endpoints as settings_endpoints
from api.settings.models import SettingsUpdateBody
from config.embedding_constants import OPENAI_DEFAULT_EMBEDDING_MODEL


class _FakeTask:
    def __init__(self):
        self.done_callback = None

    def add_done_callback(self, cb):
        self.done_callback = cb


def _make_config(*, oci_configured: bool, embedding_provider: str = "openai"):
    providers = SimpleNamespace(
        openai=SimpleNamespace(api_key="openai-key", configured=True),
        anthropic=SimpleNamespace(api_key="", configured=False),
        watsonx=SimpleNamespace(api_key="", endpoint="", project_id="", configured=False),
        ollama=SimpleNamespace(endpoint="", configured=False),
        oci=SimpleNamespace(
            user="ocid1.user.oc1..xxx" if oci_configured else "",
            fingerprint="xx:xx:xx:xx" if oci_configured else "",
            tenancy="ocid1.tenancy.oc1..xxx" if oci_configured else "",
            compartment_id="ocid1.compartment.oc1..xxx" if oci_configured else "",
            key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
            if oci_configured
            else "",
            key_file="",
            region="us-ashburn-1" if oci_configured else "",
            configured=oci_configured,
        ),
    )
    return SimpleNamespace(
        edited=True,
        agent=SimpleNamespace(llm_provider="openai", llm_model="gpt-5.4-mini"),
        knowledge=SimpleNamespace(
            embedding_provider=embedding_provider,
            embedding_model="text-embedding-3-small",
        ),
        providers=providers,
    )


def _patch_common(monkeypatch, config):
    """Apply the same monkeypatches used by the existing provider-removal
    tests in test_settings_async_post_save.py, so update_settings() can run
    without touching Langflow, OpenSearch, or the filesystem."""
    fake_task = _FakeTask()
    post_save_mock = AsyncMock()

    async def _noop_refresh():
        return None

    def _fake_create_task(coro):
        # Only scheduling behavior matters here; discard the coroutine.
        coro.close()
        return fake_task

    monkeypatch.setattr(settings_endpoints, "get_openrag_config", lambda: config, raising=True)
    monkeypatch.setattr(
        settings_endpoints.config_manager,
        "save_config_file",
        lambda updated_config: True,
        raising=True,
    )
    monkeypatch.setattr(
        settings_endpoints.clients, "refresh_patched_client", _noop_refresh, raising=True
    )
    monkeypatch.setattr(settings_endpoints.TelemetryClient, "send_event", AsyncMock(), raising=True)
    monkeypatch.setattr(
        settings_endpoints, "_run_async_post_save_langflow_updates", post_save_mock, raising=True
    )
    monkeypatch.setattr(settings_endpoints.asyncio, "create_task", _fake_create_task, raising=True)
    return fake_task, post_save_mock


@pytest.mark.asyncio
async def test_update_settings_persists_oci_credential_fields(monkeypatch):
    settings_endpoints._background_tasks.clear()
    config = _make_config(oci_configured=False)
    _patch_common(monkeypatch, config)

    response = await settings_endpoints.update_settings(
        SettingsUpdateBody(
            oci_user="ocid1.user.oc1..xxx",
            oci_fingerprint="xx:xx:xx:xx",
            oci_tenancy="ocid1.tenancy.oc1..xxx",
            oci_compartment_id="ocid1.compartment.oc1..xxx",
            oci_key="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            oci_key_file="/tmp/oci_key.pem",
            oci_region="us-ashburn-1",
        ),
        session_manager=object(),
        user=None,
    )

    assert isinstance(response, settings_endpoints.SettingsUpdateResponse)
    assert config.providers.oci.user == "ocid1.user.oc1..xxx"
    assert config.providers.oci.fingerprint == "xx:xx:xx:xx"
    assert config.providers.oci.tenancy == "ocid1.tenancy.oc1..xxx"
    assert config.providers.oci.compartment_id == "ocid1.compartment.oc1..xxx"
    assert config.providers.oci.key == "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    assert config.providers.oci.key_file == "/tmp/oci_key.pem"
    assert config.providers.oci.region == "us-ashburn-1"
    assert config.providers.oci.configured is True


@pytest.mark.asyncio
async def test_update_settings_remove_oci_config_clears_fields(monkeypatch):
    settings_endpoints._background_tasks.clear()
    config = _make_config(oci_configured=True, embedding_provider="oci")
    _patch_common(monkeypatch, config)

    response = await settings_endpoints.update_settings(
        SettingsUpdateBody(remove_oci_config=True),
        session_manager=object(),
        user=None,
    )

    assert isinstance(response, settings_endpoints.SettingsUpdateResponse)
    assert config.providers.oci.user == ""
    assert config.providers.oci.fingerprint == ""
    assert config.providers.oci.tenancy == ""
    assert config.providers.oci.compartment_id == ""
    assert config.providers.oci.key == ""
    assert config.providers.oci.key_file == ""
    assert config.providers.oci.region == ""
    assert config.providers.oci.configured is False
    # OCI was the active embedding provider -> falls back to the only other
    # configured provider (openai), mirroring the watsonx removal fallback.
    assert config.knowledge.embedding_provider == "openai"
    assert config.knowledge.embedding_model == OPENAI_DEFAULT_EMBEDDING_MODEL


@pytest.mark.asyncio
async def test_update_settings_remove_oci_config_blocked_without_other_provider(monkeypatch):
    """Mirrors the "configure another model provider first" guard already
    enforced for ollama/openai/anthropic/watsonx removal."""
    settings_endpoints._background_tasks.clear()
    config = _make_config(oci_configured=True, embedding_provider="oci")
    config.providers.openai.configured = False
    _patch_common(monkeypatch, config)

    response = await settings_endpoints.update_settings(
        SettingsUpdateBody(remove_oci_config=True),
        session_manager=object(),
        user=None,
    )

    assert response.status_code == 400
    # Distinguish this from the pre-fix generic "no valid fields" 400 (which
    # a body with only remove_oci_config=True would also have hit when there
    # was no branch recognizing that field at all).
    assert b"Cannot remove OCI Generative AI configuration" in bytes(response.body)
    # Nothing was cleared since the removal was rejected.
    assert config.providers.oci.configured is True
