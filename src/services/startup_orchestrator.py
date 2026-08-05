"""Startup orchestration for the OpenRAG backend.

Runs after services are constructed and the FastAPI lifespan begins.
Bootstraps OpenSearch (when not in IBM auth mode), reingests bundled docs
on upgrade, refreshes them if remote content changed, syncs Langflow MCP
server URLs, and reapplies user settings if Langflow flows were reset.
"""

from config.settings import (
    FETCH_OPENRAG_DOCS_AT_STARTUP,
    OPENRAG_BOOTSTRAP_OS_SECURITY_ON_STARTUP,
    OPENRAG_SKIP_OS_SECURITY_SETUP,
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


async def _update_mcp_server_urls(langflow_mcp_service) -> None:
    """Update MCP server URLs (patch localhost and convert to streamable HTTP)."""
    try:
        result = await langflow_mcp_service.update_all_mcp_server_urls()
        logger.info("Updated MCP server URLs after settings change", **result)
    except Exception as mcp_error:
        logger.warning(f"Failed to update MCP server URLs after settings change: {str(mcp_error)}")


async def startup_tasks(services) -> None:
    """Startup tasks"""
    from config.settings import IBM_AUTH_ENABLED

    logger.info("Starting startup tasks")
    await TelemetryClient.send_event(Category.APPLICATION_STARTUP, MessageId.ORB_APP_START_INIT)

    # Warm the in-process cache of workspace-level OAuth connector credential
    # overrides (see services.connector_oauth_config_service) so BaseConnector's
    # synchronous get_client_id()/get_client_secret() resolve overrides without a
    # DB session. Reuses the same lazy session factory wired into workspace_config_service.
    try:
        from services.connector_oauth_config_service import warm_cache

        await warm_cache(services["workspace_config_service"]._session_factory)
    except Exception as e:
        logger.error(
            "Failed to warm connector OAuth config cache — overrides unavailable "
            "until the next restart, env vars still work",
            error=str(e),
        )

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

        # Setup OpenSearch security (roles and mappings) after connection is established.
        # Skip entirely when the platform manages the security context externally
        # (SaaS / CPD): the call would otherwise either fail with 403/401 or
        # overwrite a curated config. Also skip when the lifespan-level
        # bootstrap (driven by OPENRAG_SERVICE_TOKEN) has already handled it.
        if OPENRAG_SKIP_OS_SECURITY_SETUP:
            logger.info(
                "Skipping OpenSearch security setup at startup "
                "(OPENRAG_SKIP_OS_SECURITY_SETUP=true)"
            )
        elif OPENRAG_BOOTSTRAP_OS_SECURITY_ON_STARTUP:
            logger.info(
                "Skipping OpenSearch security setup in startup_tasks "
                "(handled by lifespan bootstrap)"
            )
        else:
            try:
                from utils.opensearch_utils import setup_opensearch_security

                await setup_opensearch_security(clients.opensearch)
                logger.info("OpenSearch security configuration completed successfully")
            except Exception as e:
                logger.warning(
                    "Failed to setup OpenSearch security configuration - continuing anyway",
                    error=str(e),
                )

        if get_openrag_config().knowledge.disable_ingest_with_langflow:
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

    # Ensure all configured flows exist in Langflow (create-only, never overwrites existing).
    # If a flow does not exist, it is created and active configuration settings are reapplied.
    try:
        flows_service = services["flows_service"]
        await flows_service.ensure_flows_exist()
    except Exception as e:
        logger.error(
            "Failed to ensure Langflow flows exist at startup — "
            "flows may be missing until the next restart",
            error=str(e),
        )

    # Older Langflow databases may have plain-string globals stored as Credential
    # variables because environment-seeded globals used Credential by default.
    try:
        from api.settings.langflow_sync import ensure_required_langflow_global_variables

        await ensure_required_langflow_global_variables(get_openrag_config())
        logger.info("Ensured required Langflow global variables")
    except Exception as e:
        logger.error(
            "Failed to ensure required Langflow global variables at startup",
            error=str(e),
        )
