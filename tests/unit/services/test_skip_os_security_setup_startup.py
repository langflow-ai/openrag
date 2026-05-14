"""OPENRAG_SKIP_OS_SECURITY_SETUP gates the startup_orchestrator call to
setup_opensearch_security.

Two cases:
  * Flag false (default): setup_opensearch_security is invoked.
  * Flag true:            it is NOT invoked, skip log line is emitted.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _services_stub():
    """Minimal services dict — only models_service is touched before the
    OpenSearch security block, and we want its call to fail loudly so the
    test fails fast if it changes."""
    models = MagicMock()
    models.update_model_registry = AsyncMock()
    return {"models_service": models}


@pytest.mark.asyncio
async def test_setup_runs_when_flag_false(monkeypatch):
    """Default (flag false): setup_opensearch_security is called."""
    import services.startup_orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "OPENRAG_SKIP_OS_SECURITY_SETUP", False)
    monkeypatch.setattr(orchestrator, "DISABLE_INGEST_WITH_LANGFLOW", False)
    # IBM_AUTH_ENABLED is imported lazily inside startup_tasks().
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False, raising=False)

    setup_mock = AsyncMock()
    with (
        patch("utils.opensearch_utils.setup_opensearch_security", setup_mock),
        patch.object(orchestrator, "wait_for_opensearch", AsyncMock()),
        patch.object(orchestrator, "init_index", AsyncMock()),
        patch.object(orchestrator, "configure_alerting_security", AsyncMock()),
        patch.object(
            orchestrator,
            "_reingest_default_docs_on_upgrade_if_needed",
            AsyncMock(return_value=False),
        ),
        patch.object(orchestrator, "_update_mcp_server_urls", AsyncMock()),
    ):
        # Force the post-security work to exit early — config.edited=False
        # short-circuits both the recovery init_index and the flow check.
        with patch.object(
            orchestrator,
            "get_openrag_config",
            MagicMock(
                return_value=MagicMock(edited=False, knowledge=MagicMock(embedding_model=None))
            ),
        ):
            services = _services_stub()
            services["task_service"] = MagicMock()
            services["document_service"] = MagicMock()
            services["langflow_file_service"] = MagicMock()
            services["session_manager"] = MagicMock()
            services["langflow_mcp_service"] = MagicMock()
            services["flows_service"] = MagicMock(ensure_flows_exist=AsyncMock(return_value=set()))
            await orchestrator.startup_tasks(services)

    assert setup_mock.await_count == 1, (
        "setup_opensearch_security must run when OPENRAG_SKIP_OS_SECURITY_SETUP is false"
    )


@pytest.mark.asyncio
async def test_setup_skipped_when_flag_true(monkeypatch):
    """Flag true: setup_opensearch_security is NOT called."""
    import services.startup_orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "OPENRAG_SKIP_OS_SECURITY_SETUP", True)
    monkeypatch.setattr(orchestrator, "DISABLE_INGEST_WITH_LANGFLOW", False)
    monkeypatch.setattr("config.settings.IBM_AUTH_ENABLED", False, raising=False)

    setup_mock = AsyncMock()
    # Spy on the orchestrator's bound logger so we can assert the skip line
    # was emitted without depending on caplog propagation through the
    # project's custom logger wrapper.
    logger_spy = MagicMock()
    monkeypatch.setattr(orchestrator, "logger", logger_spy)

    with (
        patch("utils.opensearch_utils.setup_opensearch_security", setup_mock),
        patch.object(orchestrator, "wait_for_opensearch", AsyncMock()),
        patch.object(orchestrator, "init_index", AsyncMock()),
        patch.object(orchestrator, "configure_alerting_security", AsyncMock()),
        patch.object(
            orchestrator,
            "_reingest_default_docs_on_upgrade_if_needed",
            AsyncMock(return_value=False),
        ),
        patch.object(orchestrator, "_update_mcp_server_urls", AsyncMock()),
    ):
        with patch.object(
            orchestrator,
            "get_openrag_config",
            MagicMock(
                return_value=MagicMock(edited=False, knowledge=MagicMock(embedding_model=None))
            ),
        ):
            services = _services_stub()
            services["task_service"] = MagicMock()
            services["document_service"] = MagicMock()
            services["langflow_file_service"] = MagicMock()
            services["session_manager"] = MagicMock()
            services["langflow_mcp_service"] = MagicMock()
            services["flows_service"] = MagicMock(ensure_flows_exist=AsyncMock(return_value=set()))
            await orchestrator.startup_tasks(services)

    assert setup_mock.await_count == 0, (
        "setup_opensearch_security must NOT run when OPENRAG_SKIP_OS_SECURITY_SETUP is true"
    )
    info_messages = [call.args[0] for call in logger_spy.info.call_args_list if call.args]
    assert any("Skipping OpenSearch security setup at startup" in msg for msg in info_messages), (
        f"expected skip log line not emitted; got: {info_messages}"
    )
