"""Startup orchestration for the OpenRAG backend.

Runs after services are constructed and the FastAPI lifespan begins.
Bootstraps OpenSearch (when not in IBM auth mode), reingests bundled docs
on upgrade, refreshes them if remote content changed, syncs Langflow MCP
server URLs, and reapplies user settings if Langflow flows were reset.
"""

from config.settings import (
    DISABLE_INGEST_WITH_LANGFLOW,
    FETCH_OPENRAG_DOCS_AT_STARTUP,
    clients,
    get_openrag_config,
)
from services.default_docs_service import (
    _reingest_default_docs_on_upgrade_if_needed,
    refresh_default_openrag_docs,
)
from utils.logging_config import get_logger
from utils.opensearch_init import (
    _ensure_opensearch_index,
    configure_alerting_security,
    init_index,
    wait_for_opensearch,
)
from utils.telemetry import Category, MessageId, TelemetryClient

logger = get_logger(__name__)


async def _update_mcp_server_urls(langflow_mcp_service):
    """Update MCP server URLs (patch localhost and convert to streamable HTTP)."""
    try:
        result = await langflow_mcp_service.update_all_mcp_server_urls()
        logger.info("Updated MCP server URLs after settings change", **result)
    except Exception as mcp_error:
        logger.warning(f"Failed to update MCP server URLs after settings change: {str(mcp_error)}")


async def startup_tasks(services):
    """Startup tasks"""
    from config.settings import IBM_AUTH_ENABLED

    logger.info("Starting startup tasks")
    await TelemetryClient.send_event(Category.APPLICATION_STARTUP, MessageId.ORB_APP_START_INIT)

    # Update model registry to allow further search calls to be instant
    try:
        models_service = services["models_service"]
        await models_service.update_model_registry()
    except Exception as e:
        logger.error(
            "Failed to update model registry at startup — "
            "models may be missing until the next restart",
            error=str(e),
        )

    if IBM_AUTH_ENABLED:
        logger.info(
            "IBM auth mode: skipping startup OpenSearch checks. "
            "OpenSearch will be initialized during onboarding with user credentials."
        )
    else:
        # Only initialize basic OpenSearch connection, not the index
        # Index will be created after onboarding when we know the embedding model
        await wait_for_opensearch()

        # Setup OpenSearch security (roles and mappings) after connection is established
        try:
            from utils.opensearch_utils import setup_opensearch_security

            await setup_opensearch_security(clients.opensearch)
            logger.info("OpenSearch security configuration completed successfully")
        except Exception as e:
            logger.warning(
                "Failed to setup OpenSearch security configuration - continuing anyway",
                error=str(e),
            )

        if DISABLE_INGEST_WITH_LANGFLOW:
            await _ensure_opensearch_index()

        # Ensure that the OpenSearch index exists if onboarding was already completed
        # - Handles the case where OpenSearch is reset (e.g., volume deleted) after onboarding
        embedding_model = None
        try:
            config = get_openrag_config()
            embedding_model = config.knowledge.embedding_model

            if config.edited and embedding_model:
                logger.info(
                    "Ensuring that the OpenSearch index exists (after onboarding)...",
                    embedding_model=embedding_model,
                )

                await init_index()

                logger.info(
                    "Successfully ensured that the OpenSearch index exists (after onboarding).",
                    embedding_model=embedding_model,
                )
        except Exception as e:
            logger.error(
                "Failed to ensure that the OpenSearch index exists (after onboarding).",
                embedding_model=embedding_model,
                error=str(e),
            )
            raise

        await configure_alerting_security()

    # Reingest bundled OpenRAG docs once after application upgrade.
    upgrade_reingested = False
    try:
        upgrade_reingested = await _reingest_default_docs_on_upgrade_if_needed(
            services["document_service"],
            services["models_service"],
            services["task_service"],
            services["langflow_file_service"],
            services["session_manager"],
        )
    except Exception as e:
        logger.error("Default docs reingestion on upgrade failed", error=str(e))

    if FETCH_OPENRAG_DOCS_AT_STARTUP and not upgrade_reingested:
        try:
            await refresh_default_openrag_docs(
                services["document_service"],
                services["models_service"],
                services["task_service"],
                services["langflow_file_service"],
                services["session_manager"],
                force=False,
                reason="startup",
            )
        except Exception as e:
            logger.error("OpenRAG docs startup refresh failed", error=str(e))

    # Update MCP server URLs (patch localhost and convert to streamable HTTP)
    await _update_mcp_server_urls(services["langflow_mcp_service"])

    # Ensure all configured flows exist in Langflow (create-only, never overwrites).
    # This replaces LANGFLOW_LOAD_FLOWS_PATH, which performed a blind upsert on
    # every container start and discarded any user edits made in the Langflow UI.
    newly_created: set[str] = set()
    try:
        flows_service = services["flows_service"]
        newly_created = await flows_service.ensure_flows_exist()
    except Exception as e:
        logger.error(
            "Failed to ensure Langflow flows exist at startup — "
            "flows may be missing until the next restart",
            error=str(e),
        )

    # Check if flows were reset and reapply settings if config is edited
    try:
        config = get_openrag_config()
        if config.edited:
            logger.info("Checking if Langflow flows were reset")
            flows_service = services["flows_service"]
            reset_flows = await flows_service.check_flows_reset()
            # Exclude flows that were just seeded — they match the JSON by design,
            # not because they were externally reset.
            reset_flows = [f for f in reset_flows if f not in newly_created]

            if reset_flows:
                logger.info(
                    f"Detected reset flows: {', '.join(reset_flows)}. Reapplying all settings."
                )
                await TelemetryClient.send_event(
                    Category.FLOW_OPERATIONS, MessageId.ORB_FLOW_RESET_DETECTED
                )
                from api.settings import reapply_all_settings

                await reapply_all_settings(session_manager=services["session_manager"])
                logger.info("Successfully reapplied settings after detecting flow resets")
                await TelemetryClient.send_event(
                    Category.FLOW_OPERATIONS, MessageId.ORB_FLOW_SETTINGS_REAPPLIED
                )
            else:
                logger.info("No flows detected as reset, skipping settings reapplication")
        else:
            logger.debug("Configuration not yet edited, skipping flow reset check")
    except Exception as e:
        logger.error(f"Failed to check flows reset or reapply settings: {str(e)}")
        await TelemetryClient.send_event(
            Category.FLOW_OPERATIONS, MessageId.ORB_FLOW_RESET_CHECK_FAIL
        )
        # Don't fail startup if this check fails
