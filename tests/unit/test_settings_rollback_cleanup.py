from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import api.settings as settings_api
from config.config_manager import (
    AgentConfig,
    AnthropicConfig,
    KnowledgeConfig,
    OllamaConfig,
    OnboardingState,
    OpenAIConfig,
    OpenRAGConfig,
    ProvidersConfig,
    WatsonXConfig,
)
from session_manager import User


def _build_config() -> OpenRAGConfig:
    return OpenRAGConfig(
        providers=ProvidersConfig(
            openai=OpenAIConfig(configured=True),
            anthropic=AnthropicConfig(),
            watsonx=WatsonXConfig(),
            ollama=OllamaConfig(),
        ),
        knowledge=KnowledgeConfig(
            backend="astra",
            embedding_model="text-embedding-3-small",
            embedding_provider="openai",
        ),
        agent=AgentConfig(
            llm_model="gpt-4o-mini",
            llm_provider="openai",
        ),
        onboarding=OnboardingState(
            current_step=2,
            openrag_docs_filter_id="filter-openrag",
            user_doc_filter_id="filter-user",
            openrag_docs_ingested_version="0.3.1",
            openrag_docs_remote_signature="sig-1",
        ),
        edited=True,
    )


@pytest.mark.asyncio
async def test_rollback_onboarding_uses_backend_cleanup_for_task_files(
    monkeypatch,
    tmp_path: Path,
):
    current_config = _build_config()
    backend = Mock()
    backend.delete_by_filename = AsyncMock(return_value=3)
    task_service = Mock()
    task_service.get_all_tasks.return_value = [
        {
            "task_id": "task-1",
            "status": "processing",
            "files": {
                "/tmp/report.txt": {"filename": "report.txt"},
            },
        }
    ]
    task_service.cancel_task = AsyncMock(return_value=True)
    task_service.task_store = {
        "u1": {"task-1": {"dummy": True}},
        "anonymous": {"task-1": {"dummy": True}},
    }
    task_service._task_locks = {"task-1": object()}

    knowledge_filter_service = Mock()
    knowledge_filter_service.delete_knowledge_filter = AsyncMock(
        return_value={"success": True}
    )

    monkeypatch.setattr(settings_api, "get_openrag_config", lambda: current_config)
    monkeypatch.setattr(
        "services.knowledge_backend.get_knowledge_backend_service",
        lambda _session_manager: backend,
    )
    monkeypatch.setattr(
        settings_api.TelemetryClient,
        "send_event",
        AsyncMock(),
    )
    monkeypatch.setattr(
        settings_api.config_manager,
        "config_file",
        tmp_path / "config.yaml",
        raising=False,
    )

    response = await settings_api.rollback_onboarding(
        request=Mock(),
        body=None,
        session_manager=Mock(),
        task_service=task_service,
        knowledge_filter_service=knowledge_filter_service,
        user=User(
            user_id="u1",
            email="u1@example.com",
            name="User One",
            jwt_token="Bearer test-token",
        ),
    )

    assert response.message == "Onboarding configuration rolled back successfully"
    assert response.cancelled_tasks == 1
    assert response.deleted_files == 1
    backend.delete_by_filename.assert_awaited_once()
    delete_args = backend.delete_by_filename.await_args.args
    assert delete_args[0] == "report.txt"
    assert delete_args[1].user_id == "u1"
    assert delete_args[1].user_email == "u1@example.com"
    assert delete_args[1].jwt_token == "Bearer test-token"
    task_service.cancel_task.assert_awaited_once_with("u1", "task-1")
    assert "task-1" not in task_service.task_store["u1"]
    assert "task-1" not in task_service.task_store["anonymous"]
    knowledge_filter_service.delete_knowledge_filter.assert_any_await(
        "filter-openrag",
        "u1",
        "Bearer test-token",
    )
    knowledge_filter_service.delete_knowledge_filter.assert_any_await(
        "filter-user",
        "u1",
        "Bearer test-token",
    )
    assert settings_api.config_manager.config_file.exists()
