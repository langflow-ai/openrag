"""Service container — constructs all application services and wires their dependencies.

Returns a dict consumed by routes (via FastAPI Depends) and the lifespan hook.
"""

from api.connector_router import ConnectorRouter
from config.settings import (
    INGESTION_TIMEOUT,
    JWT_SIGNING_KEY,
    SESSION_SECRET,
    clients,
    config_manager,
    get_embedding_model,
    get_index_name,
    is_no_auth_mode,
)
from connectors.langflow_connector_service import LangflowConnectorService
from connectors.service import ConnectorService
from services.api_key_service import APIKeyService
from services.auth_service import AuthService
from services.chat_service import ChatService
from services.document_service import DocumentService
from services.flows_service import FlowsService
from services.knowledge_filter_service import KnowledgeFilterService
from services.langflow_file_service import LangflowFileService
from services.langflow_mcp_service import LangflowMCPService
from services.models_service import ModelsService
from services.monitor_service import MonitorService
from services.search_service import SearchService, register_search_service
from services.task_service import TaskService
from session_manager import SessionManager
from utils.jwt_keygen import generate_jwt_keys
from utils.logging_config import get_logger
from utils.telemetry import Category, MessageId, TelemetryClient

logger = get_logger(__name__)


async def initialize_services():
    """Initialize all services and their dependencies"""
    await TelemetryClient.send_event(Category.SERVICE_INITIALIZATION, MessageId.ORB_SVC_INIT_START)
    from config.settings import IBM_AUTH_ENABLED

    if IBM_AUTH_ENABLED:
        logger.info("IBM auth mode enabled — JWT validation delegated to Traefik")

    # Generate JWT keys if they don't exist, a JWT signing key isn't specified,
    # and IBM auth is not enabled (IBM mode delegates all auth to Traefik)
    if not JWT_SIGNING_KEY and not IBM_AUTH_ENABLED:
        generate_jwt_keys()

    # Initialize clients (now async to generate Langflow API key)
    try:
        await clients.initialize()
    except Exception as e:
        logger.error("Failed to initialize clients", error=str(e))
        await TelemetryClient.send_event(
            Category.SERVICE_INITIALIZATION, MessageId.ORB_SVC_OS_CLIENT_FAIL
        )
        raise

    session_manager = SessionManager(SESSION_SECRET)

    models_service = ModelsService()
    document_service = DocumentService(
        session_manager=session_manager,
        models_service=models_service,
        docling_service=clients.docling_service,
    )
    search_service = SearchService(session_manager, models_service)
    register_search_service(search_service)
    task_service = TaskService(
        document_service,
        models_service,
        ingestion_timeout=INGESTION_TIMEOUT,
        docling_service=clients.docling_service,
    )
    flows_service = FlowsService()
    chat_service = ChatService(flows_service=flows_service)
    knowledge_filter_service = KnowledgeFilterService(session_manager)
    monitor_service = MonitorService(session_manager)
    langflow_file_service = LangflowFileService(
        flows_service=flows_service,
        docling_service=clients.docling_service,
    )
    langflow_mcp_service = LangflowMCPService()

    langflow_connector_service = LangflowConnectorService(
        task_service=task_service,
        session_manager=session_manager,
        flows_service=flows_service,
        docling_service=clients.docling_service,
    )
    openrag_connector_service = ConnectorService(
        patched_async_client=clients,
        embed_model=get_embedding_model(),
        index_name=get_index_name(),
        task_service=task_service,
        session_manager=session_manager,
        models_service=models_service,
        document_service=document_service,
        docling_service=clients.docling_service,
    )

    connector_service = ConnectorRouter(
        langflow_connector_service=langflow_connector_service,
        openrag_connector_service=openrag_connector_service,
    )

    auth_service = AuthService(
        session_manager,
        connector_service,
        flows_service,
        langflow_mcp_service=langflow_mcp_service,
    )

    # Load persisted connector connections at startup so webhooks and syncs
    # can resolve existing subscriptions immediately after server boot
    # Skip in no-auth mode since connectors require OAuth
    if not is_no_auth_mode():
        try:
            await connector_service.initialize()
            loaded_count = len(connector_service.connection_manager.connections)
            logger.info(
                "Loaded persisted connector connections on startup",
                loaded_count=loaded_count,
            )
        except Exception as e:
            logger.error("Failed to load persisted connections on startup", error=str(e))
            await TelemetryClient.send_event(
                Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_LOAD_FAILED
            )
    else:
        logger.info("[CONNECTORS] Skipping connection loading in no-auth mode")

    await TelemetryClient.send_event(
        Category.SERVICE_INITIALIZATION, MessageId.ORB_SVC_INIT_SUCCESS
    )

    api_key_service = APIKeyService(session_manager)

    # ===== RBAC service =====
    # We do NOT open the SQL engine here. `create_app()` runs inside an
    # `asyncio.run(...)` whose loop is closed BEFORE uvicorn starts its
    # own loop — any AsyncEngine bound to this loop would be dead by
    # then. Instead, RBACService takes a *lazy* session-factory getter
    # that resolves `db.engine.SessionLocal` at call time — that
    # attribute is filled in by the lifespan startup event running on
    # uvicorn's loop. Alembic upgrade is run synchronously from __main__
    # before `asyncio.run(create_app())` so the schema is in place by
    # the time the lifespan opens the engine.
    from db import engine as _db_engine_mod
    from services.rbac_service import RBACService
    from services.workspace_config_service import WorkspaceConfigService

    def _lazy_session_factory():
        sl = _db_engine_mod.SessionLocal
        if sl is None:
            raise RuntimeError(
                "DB engine not yet initialized. RBACService called before lifespan startup."
            )
        return sl()

    rbac_service = RBACService(_lazy_session_factory)

    # WorkspaceConfigService — DB-first reads of what config.yaml holds,
    # with the legacy ConfigManager kept as the yaml fallback during
    # Phase B (dual-write).
    workspace_config_service = WorkspaceConfigService(
        config_manager=config_manager,
        session_factory=_lazy_session_factory,
    )

    # Plumb the session factory into the two chat-history services
    # (session_ownership + conversation_persistence). They lazy-resolve
    # `db.engine.SessionLocal` as a fallback, but setting it here makes
    # the wiring explicit and avoids the import path on the hot loop.
    from services.conversation_persistence_service import conversation_persistence
    from services.session_ownership_service import session_ownership_service

    session_ownership_service._session_factory = _lazy_session_factory
    conversation_persistence._session_factory = _lazy_session_factory

    return {
        "document_service": document_service,
        "search_service": search_service,
        "task_service": task_service,
        "chat_service": chat_service,
        "flows_service": flows_service,
        "langflow_file_service": langflow_file_service,
        "auth_service": auth_service,
        "connector_service": connector_service,
        "knowledge_filter_service": knowledge_filter_service,
        "models_service": models_service,
        "monitor_service": monitor_service,
        "session_manager": session_manager,
        "api_key_service": api_key_service,
        "langflow_mcp_service": langflow_mcp_service,
        "docling_service": clients.docling_service,
        "rbac_service": rbac_service,
        "workspace_config_service": workspace_config_service,
    }
