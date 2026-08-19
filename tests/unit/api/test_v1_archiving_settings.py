from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.settings as settings_api
import api.settings.endpoints as settings_endpoints
from api.v1.settings import get_settings_endpoint
from session_manager import User


def _config():
    """Build a minimal configuration with local archiving enabled."""
    return SimpleNamespace(
        agent=SimpleNamespace(
            llm_provider=None,
            llm_model=None,
            system_prompt=None,
        ),
        knowledge=SimpleNamespace(
            embedding_provider=None,
            embedding_model=None,
            chunk_size=None,
            chunk_overlap=None,
            table_structure=None,
            ocr=None,
            picture_descriptions=None,
        ),
        archiving=SimpleNamespace(enabled=True),
    )


@pytest.mark.asyncio
async def test_v1_settings_marks_local_archiving_unavailable_in_multi_user_mode(
    monkeypatch,
):
    """Report local archiving as unavailable in multi-user mode."""
    monkeypatch.setattr("api.v1.settings.get_openrag_config", _config)
    monkeypatch.setattr("api.v1.settings.is_no_auth_mode", lambda: False)
    user = User(
        user_id="user-1",
        email="user@example.com",
        name="User",
        jwt_token="Bearer token",
    )

    settings = await get_settings_endpoint(user=user)

    assert settings.archiving.available is False
    assert settings.archiving.enabled is False


@pytest.mark.asyncio
async def test_v1_settings_exposes_archiving_in_no_auth_mode(monkeypatch):
    """Expose the configured local archiving state in no-auth mode."""
    monkeypatch.setattr("api.v1.settings.get_openrag_config", _config)
    monkeypatch.setattr("api.v1.settings.is_no_auth_mode", lambda: True)
    user = User(
        user_id="default",
        email="user@example.com",
        name="User",
        jwt_token="Bearer token",
    )

    settings = await get_settings_endpoint(user=user)

    assert settings.archiving.available is True
    assert settings.archiving.enabled is True


@pytest.mark.asyncio
async def test_settings_rejects_enabling_local_archiving_in_multi_user_mode(
    monkeypatch,
):
    """Reject attempts to enable local archiving in multi-user mode."""
    config = SimpleNamespace(
        edited=True,
        archiving=SimpleNamespace(enabled=False),
    )
    monkeypatch.setattr(settings_endpoints, "get_openrag_config", lambda: config)
    monkeypatch.setattr("config.settings.is_no_auth_mode", lambda: False)

    with pytest.raises(HTTPException) as exc_info:
        await settings_api.update_settings(
            settings_api.SettingsUpdateBody(archive_sources_enabled=True),
            session_manager=object(),
            user=None,
        )

    assert exc_info.value.status_code == 422
    assert config.archiving.enabled is False
