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
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

import api.settings.endpoints as settings_endpoints
import utils.oci_auth as oci_auth
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
            # Matches OCIConfig's default auth_method regardless of whether
            # credentials are configured -- see config.config_manager.OCIConfig.
            auth_method="api_key",
            configured=oci_configured,
        ),
    )
    # update_settings()'s embedding-provider validation branch resolves the
    # effective provider config via current_config.providers.get_provider_config(...)
    # (see config.config_manager.ProvidersConfig.get_provider_config). The real
    # config object has this method; this fake needs it too for that branch to run.
    providers.get_provider_config = lambda provider: getattr(providers, provider)
    # update_settings()'s validation branch also resolves generic LiteLLM
    # credential kwargs via current_config.providers.credential_values(...)
    # (see config.config_manager.ProvidersConfig.credential_values). OCI
    # doesn't use this path (it has its own oci_* fields), so an empty dict
    # is enough for this fake.
    providers.credential_values = lambda _provider: {}
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
    without touching Langflow, OpenSearch, or the filesystem.

    ``update_settings`` stages every mutation on a ``copy.deepcopy`` of the
    live config (``working_config``) and only calls ``save_config_file`` once
    all validation has passed -- the live ``config`` object itself is never
    mutated in place. Callers must therefore assert against the config
    captured in ``saved_configs`` (the argument passed to
    ``save_config_file``), not against ``config`` -- mirroring the pattern in
    ``tests/unit/test_settings_index_name_validation.py``.
    """
    fake_task = _FakeTask()
    post_save_mock = AsyncMock()
    saved_configs = []

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
        lambda updated_config: saved_configs.append(updated_config) or True,
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
    return fake_task, post_save_mock, saved_configs


@pytest.mark.asyncio
async def test_update_settings_persists_oci_credential_fields(monkeypatch):
    settings_endpoints._background_tasks.clear()
    config = _make_config(oci_configured=False)
    _fake_task, _post_save_mock, saved_configs = _patch_common(monkeypatch, config)

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
    # The staged copy passed to save_config_file carries the new values...
    saved = saved_configs[0]
    assert saved.providers.oci.user == "ocid1.user.oc1..xxx"
    assert saved.providers.oci.fingerprint == "xx:xx:xx:xx"
    assert saved.providers.oci.tenancy == "ocid1.tenancy.oc1..xxx"
    assert saved.providers.oci.compartment_id == "ocid1.compartment.oc1..xxx"
    assert saved.providers.oci.key == "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
    assert saved.providers.oci.key_file == "/tmp/oci_key.pem"
    assert saved.providers.oci.region == "us-ashburn-1"
    assert saved.providers.oci.configured is True
    # ...but the original config object (the live cache before this call
    # completes) must never be mutated in place.
    assert config.providers.oci.user == ""
    assert config.providers.oci.configured is False


@pytest.mark.asyncio
async def test_update_settings_remove_oci_config_clears_fields(monkeypatch):
    settings_endpoints._background_tasks.clear()
    config = _make_config(oci_configured=True, embedding_provider="oci")
    _fake_task, _post_save_mock, saved_configs = _patch_common(monkeypatch, config)
    # _default_embedding_model() no longer hardcodes a per-provider model name;
    # it echoes back whatever the deployment declared via EMBEDDING_PROVIDER /
    # EMBEDDING_MODEL (see config.embedding_constants). Declare one so the
    # fallback resolves to a concrete model.
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", OPENAI_DEFAULT_EMBEDDING_MODEL)

    response = await settings_endpoints.update_settings(
        SettingsUpdateBody(remove_oci_config=True),
        session_manager=object(),
        user=None,
    )

    assert isinstance(response, settings_endpoints.SettingsUpdateResponse)
    # The staged copy passed to save_config_file carries the cleared values...
    saved = saved_configs[0]
    assert saved.providers.oci.user == ""
    assert saved.providers.oci.fingerprint == ""
    assert saved.providers.oci.tenancy == ""
    assert saved.providers.oci.compartment_id == ""
    assert saved.providers.oci.key == ""
    assert saved.providers.oci.key_file == ""
    assert saved.providers.oci.region == ""
    assert saved.providers.oci.configured is False
    # OCI was the active embedding provider -> falls back to the only other
    # configured provider (openai), mirroring the watsonx removal fallback.
    assert saved.knowledge.embedding_provider == "openai"
    assert saved.knowledge.embedding_model == OPENAI_DEFAULT_EMBEDDING_MODEL
    # ...but the original config object (the live cache before this call
    # completes) must never be mutated in place.
    assert config.providers.oci.user == "ocid1.user.oc1..xxx"
    assert config.providers.oci.configured is True
    assert config.knowledge.embedding_provider == "oci"


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


@pytest.mark.asyncio
async def test_update_settings_oci_auth_method_override_reaches_validation(monkeypatch):
    """Regression test for the ordering bug flagged during Task 4 and closed
    in Task 5: ``update_settings()`` builds its local ``oci_auth_method``
    variable (used for provider validation) from the pre-existing config
    *before* ``working_config`` -- the deep copy staged for persistence --
    even exists. Unlike its 7 sibling oci_* locals, ``oci_auth_method`` had
    no pre-validation override step for a request-body value, so a PATCH
    that changed auth_method (while also touching the embedding provider)
    would validate against the OLD auth_method while persisting the NEW one.

    Drives update_settings() with a body that sets both
    ``embedding_provider="oci"`` (required to enter the embedding validation
    branch at all) and ``oci_auth_method="instance_principal"``, against a
    config whose stored auth_method is still the "api_key" default, and
    asserts that the signer-construction check invoked deep inside
    validation actually receives "instance_principal" -- not the stale
    "api_key" config value. ``build_oci_signer`` is mocked so no real OCI
    SDK / instance-metadata call happens.
    """
    settings_endpoints._background_tasks.clear()
    config = _make_config(oci_configured=True, embedding_provider="oci")
    assert config.providers.oci.auth_method == "api_key"  # the stale value this test guards against
    _fake_task, _post_save_mock, saved_configs = _patch_common(monkeypatch, config)

    build_signer_mock = Mock(return_value=object())
    monkeypatch.setattr(oci_auth, "build_oci_signer", build_signer_mock, raising=True)

    response = await settings_endpoints.update_settings(
        SettingsUpdateBody(embedding_provider="oci", oci_auth_method="instance_principal"),
        session_manager=object(),
        user=None,
    )

    assert isinstance(response, settings_endpoints.SettingsUpdateResponse)
    # Proves the local-override fix: validation received the NEW auth_method,
    # not the config's stale "api_key" value.
    build_signer_mock.assert_called_once_with("instance_principal")
    # Proves the working_config write also lands: the new auth_method is
    # what actually gets persisted, not just what validation saw.
    assert saved_configs[0].providers.oci.auth_method == "instance_principal"


class _DenyingRBAC:
    """RBAC service that grants nothing, and records what was asked for."""

    def __init__(self):
        self.checked = []

    async def has_permission(self, uid, permission):
        self.checked.append(permission)
        return False

    async def audit_denied(self, uid, permission):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("oci_auth_method", "instance_principal"),
        # Reference cases: the sibling oci_* fields were already listed in
        # provider_fields and have always been gated.
        ("oci_region", "us-ashburn-1"),
        ("oci_compartment_id", "ocid1.compartment.oc1..xxx"),
    ],
)
async def test_update_settings_requires_providers_write_for_oci_fields(monkeypatch, field, value):
    """``update_settings``'s outer dependency only requires ``config:write``;
    the ``providers:write`` check is applied inside, gated on ``should_validate``
    -- which is computed from the ``provider_fields`` list.

    ``oci_auth_method`` was missing from that list while still being written
    through to ``providers.oci.auth_method``, so a request setting ONLY that
    field skipped the ``providers:write`` check (and provider validation)
    entirely: a caller scoped to ``config:write`` alone could flip the OCI
    auth method unchecked.
    """
    settings_endpoints._background_tasks.clear()
    config = _make_config(oci_configured=True, embedding_provider="oci")
    _patch_common(monkeypatch, config)
    monkeypatch.setattr(settings_endpoints, "is_rbac_enforced", lambda: True, raising=True)
    rbac = _DenyingRBAC()

    with pytest.raises(HTTPException) as excinfo:
        await settings_endpoints.update_settings(
            SettingsUpdateBody(**{field: value}),
            session_manager=object(),
            user=SimpleNamespace(db_user_id="user-1", user_id="user-1"),
            rbac=rbac,
        )

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail["required"] == "providers:write"
    assert rbac.checked == ["providers:write"]
