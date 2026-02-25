import asyncio
import atexit
import os
import subprocess

# Configure structured logging early
from connectors.langflow_connector_service import LangflowConnectorService
from connectors.service import ConnectorService
from services.flows_service import FlowsService
from utils.container_utils import detect_container_environment
from utils.embeddings import create_dynamic_index_body
from utils.logging_config import configure_from_env, get_logger
from utils.telemetry import TelemetryClient, Category, MessageId
from fastapi import FastAPI
from fastapi.responses import JSONResponse


# API endpoints
from api import (
    auth,
    chat,
    connectors,
    docling,
    documents,
    flows,
    knowledge_filter,
    langflow_files,
    models,
    nudges,
    oidc,
    provider_health,
    router,
    search,
    settings,
    tasks,
    upload,
)

from api.connector_router import ConnectorRouter
from services.api_key_service import APIKeyService
from api import keys as api_keys
from api.v1 import chat as v1_chat, search as v1_search, documents as v1_documents, settings as v1_settings, models as v1_models, knowledge_filters as v1_knowledge_filters

# Configuration and setup
from config.settings import (
    API_KEYS_INDEX_BODY,
    API_KEYS_INDEX_NAME,
    DISABLE_INGEST_WITH_LANGFLOW,
    INGESTION_TIMEOUT,
    INDEX_BODY,
    SESSION_SECRET,
    clients,
    get_embedding_model,
    get_index_name,
    is_no_auth_mode,
    get_openrag_config,
)
from services.auth_service import AuthService
from services.langflow_mcp_service import LangflowMCPService
from services.chat_service import ChatService

# Services
from services.document_service import DocumentService
from services.knowledge_filter_service import KnowledgeFilterService

# Configuration and setup
# Services
from services.langflow_file_service import LangflowFileService
from services.models_service import ModelsService
from services.monitor_service import MonitorService
from services.search_service import SearchService
from services.task_service import TaskService
from session_manager import SessionManager

configure_from_env()
logger = get_logger(__name__)

# Files to exclude from startup ingestion
EXCLUDED_INGESTION_FILES = {"warmup_ocr.pdf"}


async def wait_for_opensearch():
    """Wait for OpenSearch to be ready, delegating to the shared utility."""
    from utils.opensearch_utils import wait_for_opensearch as _wait_for_opensearch, OpenSearchNotReadyError
    try:
        await _wait_for_opensearch(clients.opensearch)
        await TelemetryClient.send_event(Category.OPENSEARCH_SETUP, MessageId.ORB_OS_CONN_ESTABLISHED)
    except OpenSearchNotReadyError:
        await TelemetryClient.send_event(Category.OPENSEARCH_SETUP, MessageId.ORB_OS_TIMEOUT)
        raise


async def configure_alerting_security():
    """Configure OpenSearch alerting plugin security settings"""
    try:
        # For testing, disable backend role filtering to allow all authenticated users
        # In production, you'd want to configure proper roles instead
        alerting_settings = {
            "persistent": {
                "plugins.alerting.filter_by_backend_roles": "false",
                "opendistro.alerting.filter_by_backend_roles": "false",
                "opensearch.notifications.general.filter_by_backend_roles": "false",
            }
        }

        # Use admin client (clients.opensearch uses admin credentials)
        response = await clients.opensearch.cluster.put_settings(body=alerting_settings)
        logger.info(
            "Alerting security settings configured successfully", response=response
        )
    except Exception as e:
        logger.warning("Failed to configure alerting security settings", error=str(e))
        # Don't fail startup if alerting config fails


async def _ensure_opensearch_index():
    """Ensure OpenSearch index exists when using traditional connector service."""
    try:
        index_name = get_index_name()
        # Check if index already exists
        if await clients.opensearch.indices.exists(index=index_name):
            logger.debug("OpenSearch index already exists", index_name=index_name)
            return

        # Create the index with hard-coded INDEX_BODY (uses OpenAI embedding dimensions)
        await clients.opensearch.indices.create(index=index_name, body=INDEX_BODY)
        logger.info(
            "Created OpenSearch index for traditional connector service",
            index_name=index_name,
            vector_dimensions=INDEX_BODY["mappings"]["properties"]["chunk_embedding"][
                "dimension"
            ],
        )
        await TelemetryClient.send_event(Category.OPENSEARCH_INDEX, MessageId.ORB_OS_INDEX_CREATED)

    except Exception as e:
        logger.error(
            "Failed to initialize OpenSearch index for traditional connector service",
            error=str(e),
            index_name=get_index_name(),
        )
        await TelemetryClient.send_event(Category.OPENSEARCH_INDEX, MessageId.ORB_OS_INDEX_CREATE_FAIL)
        # Don't raise the exception to avoid breaking the initialization
        # The service can still function, document operations might fail later


async def init_index():
    """Initialize OpenSearch index and security roles"""
    try:
        await wait_for_opensearch()

        # Get the configured embedding model from user configuration
        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model
        embedding_provider = config.knowledge.embedding_provider
        embedding_provider_config = config.get_embedding_provider_config()

        # Create dynamic index body based on the configured embedding model
        # Pass provider and endpoint for dynamic dimension resolution (Ollama probing)
        dynamic_index_body = await create_dynamic_index_body(
            embedding_model,
            provider=embedding_provider,
            endpoint=getattr(embedding_provider_config, "endpoint", None)
        )

        # Create documents index
        index_name = get_index_name()
        if not await clients.opensearch.indices.exists(index=index_name):
            await clients.opensearch.indices.create(
                index=index_name, body=dynamic_index_body
            )
            logger.info(
                "Created OpenSearch index",
                index_name=index_name,
                embedding_model=embedding_model,
            )
            await TelemetryClient.send_event(Category.OPENSEARCH_INDEX, MessageId.ORB_OS_INDEX_CREATED)
        else:
            logger.info(
                "Index already exists, skipping creation",
                index_name=index_name,
                embedding_model=embedding_model,
            )
            await TelemetryClient.send_event(Category.OPENSEARCH_INDEX, MessageId.ORB_OS_INDEX_EXISTS)

        # Create knowledge filters index
        knowledge_filter_index_name = "knowledge_filters"
        knowledge_filter_index_body = {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "analyzer": "standard"},
                    "description": {"type": "text", "analyzer": "standard"},
                    "query_data": {"type": "text"},  # Store as text for searching
                    "owner": {"type": "keyword"},
                    "allowed_users": {"type": "keyword"},
                    "allowed_groups": {"type": "keyword"},
                    "subscriptions": {"type": "object"},  # Store subscription data
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            }
        }

        if not await clients.opensearch.indices.exists(index=knowledge_filter_index_name):
            await clients.opensearch.indices.create(
                index=knowledge_filter_index_name, body=knowledge_filter_index_body
            )
            logger.info(
                "Created knowledge filters index", index_name=knowledge_filter_index_name
            )
            await TelemetryClient.send_event(Category.OPENSEARCH_INDEX, MessageId.ORB_OS_KF_INDEX_CREATED)
        else:
            logger.info(
                "Knowledge filters index already exists, skipping creation",
                index_name=knowledge_filter_index_name,
            )

        # Create API keys index for public API authentication
        if not await clients.opensearch.indices.exists(index=API_KEYS_INDEX_NAME):
            await clients.opensearch.indices.create(
                index=API_KEYS_INDEX_NAME, body=API_KEYS_INDEX_BODY
            )
            logger.info(
                "Created API keys index", index_name=API_KEYS_INDEX_NAME
            )
        else:
            logger.info(
                "API keys index already exists, skipping creation",
                index_name=API_KEYS_INDEX_NAME,
            )

        # Configure alerting plugin security settings
        await configure_alerting_security()

    except Exception as e:
        error_msg = str(e).lower()
        if "disk usage exceeded" in error_msg or "flood-stage watermark" in error_msg:
             logger.error("OpenSearch disk usage exceeded flood-stage watermark. Index creation failed.")
             raise Exception(
                 "OpenSearch disk space is full (flood-stage watermark exceeded). "
                 "Please free up disk space on your Docker volume or host machine to continue."
             ) from e
        raise e


async def init_index_when_ready():
    """Wait for the OpenSearch service to be ready and then initialize the OpenSearch index."""
    await wait_for_opensearch()
    await init_index()


def generate_jwt_keys():
    """Generate RSA keys for JWT signing if they don't exist"""
    keys_dir = "keys"
    private_key_path = os.path.join(keys_dir, "private_key.pem")
    public_key_path = os.path.join(keys_dir, "public_key.pem")

    # Create keys directory if it doesn't exist
    os.makedirs(keys_dir, exist_ok=True)

    # Generate keys if they don't exist
    if not os.path.exists(private_key_path):
        try:
            # Generate private key
            subprocess.run(
                ["openssl", "genrsa", "-out", private_key_path, "2048"],
                check=True,
                capture_output=True,
            )

            # Set restrictive permissions on private key (readable by owner only)
            os.chmod(private_key_path, 0o600)

            # Generate public key
            subprocess.run(
                [
                    "openssl",
                    "rsa",
                    "-in",
                    private_key_path,
                    "-pubout",
                    "-out",
                    public_key_path,
                ],
                check=True,
                capture_output=True,
            )

            # Set permissions on public key (readable by all)
            os.chmod(public_key_path, 0o644)

            logger.info("Generated RSA keys for JWT signing")
        except subprocess.CalledProcessError as e:
            logger.error("Failed to generate RSA keys", error=str(e))
            TelemetryClient.send_event_sync(Category.SERVICE_INITIALIZATION, MessageId.ORB_SVC_JWT_KEY_FAIL)
            raise
    else:
        # Ensure correct permissions on existing keys
        try:
            os.chmod(private_key_path, 0o600)
            os.chmod(public_key_path, 0o644)
            logger.info("RSA keys already exist, ensured correct permissions")
        except OSError as e:
            logger.warning("Failed to set permissions on existing keys", error=str(e))


def _get_documents_dir():
    """Get the documents directory path, handling both Docker and local environments."""
    # In Docker, the volume is mounted at /app/openrag-documents
    # Locally, we use openrag-documents
    container_env = detect_container_environment()
    if container_env:
        path = os.path.abspath("/app/openrag-documents")
        logger.debug(f"Running in {container_env}, using container path: {path}")
        return path
    else:
        path = os.path.abspath(os.path.join(os.getcwd(), "openrag-documents"))
        logger.debug(f"Running locally, using local path: {path}")
        return path


async def ingest_default_documents_when_ready(
    document_service, task_service, langflow_file_service, session_manager
):
    """Scan the local documents folder and ingest files like a non-auth upload."""
    try:
        logger.info(
            "Ingesting default documents when ready",
            disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW,
        )
        await TelemetryClient.send_event(Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_START)
        base_dir = _get_documents_dir()
        if not os.path.isdir(base_dir):
            raise FileNotFoundError(f"Default documents directory not found: {base_dir}")

        # Collect files recursively, excluding warmup files
        file_paths = [
            os.path.join(root, fn)
            for root, _, files in os.walk(base_dir)
            for fn in files
            if fn not in EXCLUDED_INGESTION_FILES
        ]

        if not file_paths:
            raise FileNotFoundError(f"No default documents found in {base_dir}")

        if DISABLE_INGEST_WITH_LANGFLOW:
            await _ingest_default_documents_openrag(
                document_service, task_service, file_paths
            )
        else:
            await _ingest_default_documents_langflow(
                langflow_file_service, session_manager, task_service, file_paths
            )

        await TelemetryClient.send_event(Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_COMPLETE)

    except Exception as e:
        logger.error("Default documents ingestion failed", error=str(e))
        await TelemetryClient.send_event(Category.DOCUMENT_INGESTION, MessageId.ORB_DOC_DEFAULT_FAILED)
        raise


async def _ingest_default_documents_langflow(
    langflow_file_service, session_manager, task_service, file_paths
):
    """Ingest default documents using Langflow upload-ingest-delete pipeline."""

    logger.info(
        "Using Langflow ingestion pipeline for default documents",
        file_count=len(file_paths),
    )

    # Use AnonymousUser details for default documents
    from session_manager import AnonymousUser

    anonymous_user = AnonymousUser()

    # Get JWT token using same logic as DocumentFileProcessor
    # This will handle anonymous JWT creation if needed for anonymous user
    effective_jwt = None

    # Let session manager handle anonymous JWT creation if needed
    if session_manager:
        # This call will create anonymous JWT if needed (same as DocumentFileProcessor)
        session_manager.get_user_opensearch_client(
            anonymous_user.user_id, effective_jwt
        )
        # Get the JWT that was created by session manager
        if hasattr(session_manager, "_anonymous_jwt"):
            effective_jwt = session_manager._anonymous_jwt

    # Prepare tweaks for default documents with anonymous user metadata
    default_tweaks = {
        "OpenSearchVectorStoreComponentMultimodalMultiEmbedding-By9U4": {
            "docs_metadata": [
                {"key": "owner", "value": None},
                {"key": "owner_name", "value": anonymous_user.name},
                {"key": "owner_email", "value": anonymous_user.email},
                {"key": "connector_type", "value": "system_default"},
                {"key": "is_sample_data", "value": "true"},
            ]
        }
    }

    # Create a langflow upload task for trackable progress
    task_id = await task_service.create_langflow_upload_task(
        user_id=None,  # Anonymous user
        file_paths=file_paths,
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        jwt_token=effective_jwt,
        owner_name=anonymous_user.name,
        owner_email=anonymous_user.email,
        session_id=None,  # No session for default documents
        tweaks=default_tweaks,
        settings=None,  # Use default ingestion settings
        delete_after_ingest=True,  # Clean up after ingestion
        replace_duplicates=True,
    )

    logger.info(
        "Started Langflow ingestion task for default documents",
        task_id=task_id,
        file_count=len(file_paths),
    )

async def health_check(request):
    """Simple liveness probe: Indicates that the OpenRAG Backend service is online and running."""
    return JSONResponse({"status": "ok"}, status_code=200)


async def opensearch_health_ready(request):
    """Readiness probe: verifies OpenSearch dependency is reachable."""
    try:
        # Fast check that the cluster is reachable/auth works
        await asyncio.wait_for(clients.opensearch.info(), timeout=5.0)
        return JSONResponse(
            {"status": "ready", "dependencies": {"opensearch": "up"}},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse(
            {
                "status": "not_ready",
                "dependencies": {"opensearch": "down"},
                "error": str(e),
            },
            status_code=503,
        )

async def _ingest_default_documents_openrag(
    document_service, task_service, file_paths
):
    """Ingest default documents using traditional OpenRAG processor."""
    logger.info(
        "Using traditional OpenRAG ingestion for default documents",
        file_count=len(file_paths),
    )

    # Build a processor that DOES NOT set 'owner' on documents (owner_user_id=None)
    from models.processors import DocumentFileProcessor

    processor = DocumentFileProcessor(
        document_service,
        owner_user_id=None,
        jwt_token=None,
        owner_name=None,
        owner_email=None,
        is_sample_data=True,  # Mark as sample data
    )

    task_id = await task_service.create_custom_task(
        "anonymous", file_paths, processor
    )
    logger.info(
        "Started traditional OpenRAG ingestion task",
        task_id=task_id,
        file_count=len(file_paths),
    )


async def _update_mcp_servers_with_provider_credentials(services):
    """Update MCP servers with provider credentials at startup.

    This is especially important for no-auth mode where users don't go through
    the OAuth login flow that would normally set these credentials.
    """
    try:
        auth_service = services.get("auth_service")
        session_manager = services.get("session_manager")

        if not auth_service or not auth_service.langflow_mcp_service:
            logger.debug("MCP service not available, skipping credential update")
            return

        config = get_openrag_config()

        # Build global vars with provider credentials using utility function
        from utils.langflow_headers import build_mcp_global_vars_from_config

        global_vars = build_mcp_global_vars_from_config(config)

        # In no-auth mode, add the anonymous JWT token and user details
        if is_no_auth_mode() and session_manager:
            from session_manager import AnonymousUser

            # Create/get anonymous JWT for no-auth mode
            anonymous_jwt = session_manager.get_effective_jwt_token(None, None)
            if anonymous_jwt:
                global_vars["JWT"] = anonymous_jwt

            # Add anonymous user details
            anonymous_user = AnonymousUser()
            global_vars["OWNER"] = anonymous_user.user_id  # "anonymous"
            global_vars["OWNER_NAME"] = f'"{anonymous_user.name}"'  # "Anonymous User" (quoted for spaces)
            global_vars["OWNER_EMAIL"] = anonymous_user.email  # "anonymous@localhost"

            logger.info("Added anonymous JWT and user details to MCP servers for no-auth mode")

        if global_vars:
            result = await auth_service.langflow_mcp_service.update_mcp_servers_with_global_vars(global_vars)
            logger.info("Updated MCP servers with provider credentials at startup", **result)
        else:
            logger.debug("No provider credentials configured, skipping MCP server update")

    except Exception as e:
        logger.warning("Failed to update MCP servers with provider credentials at startup", error=str(e))
        # Don't fail startup if MCP update fails


async def startup_tasks(services):
    """Startup tasks"""
    logger.info("Starting startup tasks")
    await TelemetryClient.send_event(Category.APPLICATION_STARTUP, MessageId.ORB_APP_START_INIT)
    # Only initialize basic OpenSearch connection, not the index
    # Index will be created after onboarding when we know the embedding model
    await wait_for_opensearch()

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

    # Configure alerting security
    await configure_alerting_security()

    # Update MCP servers with provider credentials (especially important for no-auth mode)
    await _update_mcp_servers_with_provider_credentials(services)

    # Check if flows were reset and reapply settings if config is edited
    try:
        config = get_openrag_config()
        if config.edited:
            logger.info("Checking if Langflow flows were reset")
            flows_service = services["flows_service"]
            reset_flows = await flows_service.check_flows_reset()

            if reset_flows:
                logger.info(
                    f"Detected reset flows: {', '.join(reset_flows)}. Reapplying all settings."
                )
                await TelemetryClient.send_event(Category.FLOW_OPERATIONS, MessageId.ORB_FLOW_RESET_DETECTED)
                from api.settings import reapply_all_settings
                await reapply_all_settings(session_manager=services["session_manager"])
                logger.info("Successfully reapplied settings after detecting flow resets")
                await TelemetryClient.send_event(Category.FLOW_OPERATIONS, MessageId.ORB_FLOW_SETTINGS_REAPPLIED)
            else:
                logger.info("No flows detected as reset, skipping settings reapplication")
        else:
            logger.debug("Configuration not yet edited, skipping flow reset check")
    except Exception as e:
        logger.error(f"Failed to check flows reset or reapply settings: {str(e)}")
        await TelemetryClient.send_event(Category.FLOW_OPERATIONS, MessageId.ORB_FLOW_RESET_CHECK_FAIL)
        # Don't fail startup if this check fails


async def initialize_services():
    """Initialize all services and their dependencies"""
    await TelemetryClient.send_event(Category.SERVICE_INITIALIZATION, MessageId.ORB_SVC_INIT_START)
    # Generate JWT keys if they don't exist
    generate_jwt_keys()

    # Initialize clients (now async to generate Langflow API key)
    try:
        await clients.initialize()
    except Exception as e:
        logger.error("Failed to initialize clients", error=str(e))
        await TelemetryClient.send_event(Category.SERVICE_INITIALIZATION, MessageId.ORB_SVC_OS_CLIENT_FAIL)
        raise

    # Initialize session manager
    session_manager = SessionManager(SESSION_SECRET)

    # Initialize services
    document_service = DocumentService(session_manager=session_manager)
    search_service = SearchService(session_manager)
    task_service = TaskService(document_service, ingestion_timeout=INGESTION_TIMEOUT)
    chat_service = ChatService()
    flows_service = FlowsService()
    knowledge_filter_service = KnowledgeFilterService(session_manager)
    models_service = ModelsService()
    monitor_service = MonitorService(session_manager)

    # Initialize both connector services
    langflow_connector_service = LangflowConnectorService(
        task_service=task_service,
        session_manager=session_manager,
    )
    openrag_connector_service = ConnectorService(
        patched_async_client=clients,
        embed_model=get_embedding_model(),
        index_name=get_index_name(),
        task_service=task_service,
        session_manager=session_manager,
    )

    # Create connector router that chooses based on configuration
    connector_service = ConnectorRouter(
        langflow_connector_service=langflow_connector_service,
        openrag_connector_service=openrag_connector_service,
    )

    # Initialize auth service
    auth_service = AuthService(
        session_manager,
        connector_service,
        langflow_mcp_service=LangflowMCPService(),
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
            logger.warning(
                "Failed to load persisted connections on startup", error=str(e)
            )
            await TelemetryClient.send_event(Category.CONNECTOR_OPERATIONS, MessageId.ORB_CONN_LOAD_FAILED)
    else:
        logger.info("[CONNECTORS] Skipping connection loading in no-auth mode")

    await TelemetryClient.send_event(Category.SERVICE_INITIALIZATION, MessageId.ORB_SVC_INIT_SUCCESS)

    langflow_file_service = LangflowFileService()

    # API Key service for public API authentication
    api_key_service = APIKeyService(session_manager)

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
    }


async def create_app():
    """Create and configure the FastAPI application"""
    services = await initialize_services()

    app = FastAPI(title="OpenRAG API", version="0.2.4", debug=True)
    app.state.services = services  # Store services for cleanup
    app.state.background_tasks = set()

    # Register route handlers — auth and service injection done via FastAPI Depends() in each handler

    # Langflow Files endpoints
    app.add_api_route("/langflow/files/upload", langflow_files.upload_user_file, methods=["POST"], tags=["internal"])
    app.add_api_route("/langflow/ingest", langflow_files.run_ingestion, methods=["POST"], tags=["internal"])
    app.add_api_route("/langflow/files", langflow_files.delete_user_files, methods=["DELETE"], tags=["internal"])
    app.add_api_route("/langflow/upload_ingest", langflow_files.upload_and_ingest_user_file, methods=["POST"], tags=["internal"])

    # Upload endpoints
    app.add_api_route("/upload_context", upload.upload_context, methods=["POST"], tags=["internal"])
    app.add_api_route("/upload_path", upload.upload_path, methods=["POST"], tags=["internal"])
    app.add_api_route("/upload_options", upload.upload_options, methods=["GET"], tags=["internal"])
    app.add_api_route("/upload_bucket", upload.upload_bucket, methods=["POST"], tags=["internal"])

    # Task endpoints
    app.add_api_route("/tasks/{task_id}", tasks.task_status, methods=["GET"], tags=["internal"])
    app.add_api_route("/tasks", tasks.all_tasks, methods=["GET"], tags=["internal"])
    app.add_api_route("/tasks/{task_id}/cancel", tasks.cancel_task, methods=["POST"], tags=["internal"])

    # Search endpoint
    app.add_api_route("/search", search.search, methods=["POST"], tags=["internal"])

    # Knowledge Filter endpoints
    app.add_api_route("/knowledge-filter", knowledge_filter.create_knowledge_filter, methods=["POST"], tags=["internal"])
    app.add_api_route("/knowledge-filter/search", knowledge_filter.search_knowledge_filters, methods=["POST"], tags=["internal"])
    app.add_api_route("/knowledge-filter/{filter_id}", knowledge_filter.get_knowledge_filter, methods=["GET"], tags=["internal"])
    app.add_api_route("/knowledge-filter/{filter_id}", knowledge_filter.update_knowledge_filter, methods=["PUT"], tags=["internal"])
    app.add_api_route("/knowledge-filter/{filter_id}", knowledge_filter.delete_knowledge_filter, methods=["DELETE"], tags=["internal"])

    # Knowledge Filter Subscription endpoints
    app.add_api_route("/knowledge-filter/{filter_id}/subscribe", knowledge_filter.subscribe_to_knowledge_filter, methods=["POST"], tags=["internal"])
    app.add_api_route("/knowledge-filter/{filter_id}/subscriptions", knowledge_filter.list_knowledge_filter_subscriptions, methods=["GET"], tags=["internal"])
    app.add_api_route("/knowledge-filter/{filter_id}/subscribe/{subscription_id}", knowledge_filter.cancel_knowledge_filter_subscription, methods=["DELETE"], tags=["internal"])

    # Knowledge Filter Webhook endpoint (no auth required - called by OpenSearch)
    app.add_api_route("/knowledge-filter/{filter_id}/webhook/{subscription_id}", knowledge_filter.knowledge_filter_webhook, methods=["POST"], tags=["internal"])

    # Chat endpoints
    app.add_api_route("/chat", chat.chat_endpoint, methods=["POST"], tags=["internal"])
    app.add_api_route("/langflow", chat.langflow_endpoint, methods=["POST"], tags=["internal"])

    # Chat history endpoints
    app.add_api_route("/chat/history", chat.chat_history_endpoint, methods=["GET"], tags=["internal"])
    app.add_api_route("/langflow/history", chat.langflow_history_endpoint, methods=["GET"], tags=["internal"])

    # Session deletion endpoint
    app.add_api_route("/sessions/{session_id}", chat.delete_session_endpoint, methods=["DELETE"], tags=["internal"])

    # Authentication endpoints
    app.add_api_route("/auth/init", auth.auth_init, methods=["POST"], tags=["internal"])
    app.add_api_route("/auth/callback", auth.auth_callback, methods=["POST"], tags=["internal"])
    app.add_api_route("/auth/me", auth.auth_me, methods=["GET"], tags=["internal"])
    app.add_api_route("/auth/logout", auth.auth_logout, methods=["POST"], tags=["internal"])

    # Connector endpoints
    app.add_api_route("/connectors", connectors.list_connectors, methods=["GET"], tags=["internal"])
    app.add_api_route("/connectors/{connector_type}/sync", connectors.connector_sync, methods=["POST"], tags=["internal"])
    app.add_api_route("/connectors/sync-all", connectors.sync_all_connectors, methods=["POST"], tags=["internal"])
    app.add_api_route("/connectors/{connector_type}/status", connectors.connector_status, methods=["GET"], tags=["internal"])
    app.add_api_route("/connectors/{connector_type}/token", connectors.connector_token, methods=["GET"], tags=["internal"])
    app.add_api_route("/connectors/{connector_type}/disconnect", connectors.connector_disconnect, methods=["DELETE"], tags=["internal"])
    app.add_api_route("/connectors/{connector_type}/webhook", connectors.connector_webhook, methods=["POST", "GET"], tags=["internal"])

    # Document endpoints
    app.add_api_route("/documents/check-filename", documents.check_filename_exists, methods=["GET"], tags=["internal"])
    app.add_api_route("/documents/delete-by-filename", documents.delete_documents_by_filename, methods=["POST"], tags=["internal"])

    # OIDC endpoints
    app.add_api_route("/.well-known/openid-configuration", oidc.oidc_discovery, methods=["GET"], tags=["internal"])
    app.add_api_route("/auth/jwks", oidc.jwks_endpoint, methods=["GET"], tags=["internal"])
    app.add_api_route("/auth/introspect", oidc.token_introspection, methods=["POST"], tags=["internal"])

    # Settings endpoints
    app.add_api_route("/settings", settings.get_settings, methods=["GET"], tags=["internal"])
    app.add_api_route("/settings", settings.update_settings, methods=["POST"], tags=["internal"])
    app.add_api_route("/onboarding/state", settings.update_onboarding_state, methods=["POST"], tags=["internal"])

    # Provider health check endpoint
    app.add_api_route("/provider/health", provider_health.check_provider_health, methods=["GET"], tags=["internal"])

    # Health check endpoints
    app.add_api_route("/health", health_check, methods=["GET"], tags=["internal"])
    app.add_api_route("/search/health", opensearch_health_ready, methods=["GET"], tags=["internal"])

    # Models endpoints
    app.add_api_route("/models/openai", models.get_openai_models, methods=["POST"], tags=["internal"])
    app.add_api_route("/models/anthropic", models.get_anthropic_models, methods=["POST"], tags=["internal"])
    app.add_api_route("/models/ollama", models.get_ollama_models, methods=["GET"], tags=["internal"])
    app.add_api_route("/models/ibm", models.get_ibm_models, methods=["POST"], tags=["internal"])

    # Onboarding endpoints
    app.add_api_route("/onboarding", settings.onboarding, methods=["POST"], tags=["internal"])
    app.add_api_route("/onboarding/rollback", settings.rollback_onboarding, methods=["POST"], tags=["internal"])

    # Docling preset update endpoint
    app.add_api_route("/settings/docling-preset", settings.update_docling_preset, methods=["PATCH"], tags=["internal"])

    # Nudges endpoints
    app.add_api_route("/nudges", nudges.nudges_from_kb_endpoint, methods=["POST"], tags=["internal"])
    app.add_api_route("/nudges/{chat_id}", nudges.nudges_from_chat_id_endpoint, methods=["POST"], tags=["internal"])

    # Flow reset endpoint
    app.add_api_route("/reset-flow/{flow_type}", flows.reset_flow_endpoint, methods=["POST"], tags=["internal"])

    # Router upload ingest endpoint
    app.add_api_route("/router/upload_ingest", router.upload_ingest_router, methods=["POST"], tags=["internal"])

    # Docling service proxy
    app.add_api_route("/docling/health", docling.health, methods=["GET"], tags=["internal"])

    # ===== API Key Management Endpoints (JWT auth for UI) =====
    app.add_api_route("/keys", api_keys.list_keys_endpoint, methods=["GET"], tags=["internal"])
    app.add_api_route("/keys", api_keys.create_key_endpoint, methods=["POST"], tags=["internal"])
    app.add_api_route("/keys/{key_id}", api_keys.revoke_key_endpoint, methods=["DELETE"], tags=["internal"])

    # ===== Public API v1 Endpoints (API Key auth) =====
    # Chat endpoints
    app.add_api_route("/v1/chat", v1_chat.chat_create_endpoint, methods=["POST"], tags=["public"])
    app.add_api_route("/v1/chat", v1_chat.chat_list_endpoint, methods=["GET"], tags=["public"])
    app.add_api_route("/v1/chat/{chat_id}", v1_chat.chat_get_endpoint, methods=["GET"], tags=["public"])
    app.add_api_route("/v1/chat/{chat_id}", v1_chat.chat_delete_endpoint, methods=["DELETE"], tags=["public"])

    # Search endpoint
    app.add_api_route("/v1/search", v1_search.search_endpoint, methods=["POST"], tags=["public"])

    # Documents endpoints
    app.add_api_route("/v1/documents/ingest", v1_documents.ingest_endpoint, methods=["POST"], tags=["public"])
    app.add_api_route("/v1/tasks/{task_id}", v1_documents.task_status_endpoint, methods=["GET"], tags=["public"])
    app.add_api_route("/v1/documents", v1_documents.delete_document_endpoint, methods=["DELETE"], tags=["public"])

    # Settings endpoints
    app.add_api_route("/v1/settings", v1_settings.get_settings_endpoint, methods=["GET"], tags=["public"])
    app.add_api_route("/v1/settings", v1_settings.update_settings_endpoint, methods=["POST"], tags=["public"])

    # Models endpoint
    app.add_api_route("/v1/models/{provider}", v1_models.list_models_endpoint, methods=["GET"], tags=["public"])

    # Knowledge filters endpoints
    app.add_api_route("/v1/knowledge-filters", v1_knowledge_filters.create_endpoint, methods=["POST"], tags=["public"])
    app.add_api_route("/v1/knowledge-filters/search", v1_knowledge_filters.search_endpoint, methods=["POST"], tags=["public"])
    app.add_api_route("/v1/knowledge-filters/{filter_id}", v1_knowledge_filters.get_endpoint, methods=["GET"], tags=["public"])
    app.add_api_route("/v1/knowledge-filters/{filter_id}", v1_knowledge_filters.update_endpoint, methods=["PUT"], tags=["public"])
    app.add_api_route("/v1/knowledge-filters/{filter_id}", v1_knowledge_filters.delete_endpoint, methods=["DELETE"], tags=["public"])

    # Add startup event handler
    @app.on_event("startup")
    async def startup_event():
        await TelemetryClient.send_event(Category.APPLICATION_STARTUP, MessageId.ORB_APP_STARTED)
        # Start index initialization in background to avoid blocking OIDC endpoints
        t1 = asyncio.create_task(startup_tasks(services))
        app.state.background_tasks.add(t1)
        t1.add_done_callback(app.state.background_tasks.discard)

        # Start periodic task cleanup scheduler
        services["task_service"].start_cleanup_scheduler()

        # Start periodic flow backup task (every 5 minutes)
        async def periodic_backup():
            """Periodic backup task that runs every 15 minutes"""
            while True:
                try:
                    await asyncio.sleep(5 * 60)  # Wait 5 minutes

                    # Check if onboarding has been completed
                    config = get_openrag_config()
                    if not config.edited:
                        logger.debug("Onboarding not completed yet, skipping periodic backup")
                        continue

                    flows_service = services.get("flows_service")
                    if flows_service:
                        logger.info("Running periodic flow backup")
                        backup_results = await flows_service.backup_all_flows(only_if_changed=True)
                        if backup_results["backed_up"]:
                            logger.info(
                                "Periodic backup completed",
                                backed_up=len(backup_results["backed_up"]),
                                skipped=len(backup_results["skipped"]),
                            )
                        else:
                            logger.debug(
                                "Periodic backup: no flows changed",
                                skipped=len(backup_results["skipped"]),
                            )
                except asyncio.CancelledError:
                    logger.info("Periodic backup task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in periodic backup task: {str(e)}")
                    # Continue running even if one backup fails

        backup_task = asyncio.create_task(periodic_backup())
        app.state.background_tasks.add(backup_task)
        backup_task.add_done_callback(app.state.background_tasks.discard)

    # Add shutdown event handler
    @app.on_event("shutdown")
    async def shutdown_event():
        await TelemetryClient.send_event(Category.APPLICATION_SHUTDOWN, MessageId.ORB_APP_SHUTDOWN)
        await cleanup_subscriptions_proper(services)
        # Cleanup task service (cancels background tasks and process pool)
        await services["task_service"].shutdown()
        # Cleanup async clients
        await clients.cleanup()
        # Cleanup telemetry client
        from utils.telemetry.client import cleanup_telemetry_client
        await cleanup_telemetry_client()

    return app


def cleanup():
    """Cleanup on application shutdown"""
    # Cleanup process pools only (webhooks handled by FastAPI shutdown)
    logger.info("Application shutting down")
    pass


async def cleanup_subscriptions_proper(services):
    """Cancel all active webhook subscriptions"""
    logger.info("Cancelling active webhook subscriptions")

    try:
        connector_service = services["connector_service"]
        await connector_service.connection_manager.load_connections()

        # Get all active connections with webhook subscriptions
        all_connections = await connector_service.connection_manager.list_connections()
        active_connections = [
            c
            for c in all_connections
            if c.is_active and c.config.get("webhook_channel_id")
        ]

        for connection in active_connections:
            try:
                logger.info(
                    "Cancelling subscription for connection",
                    connection_id=connection.connection_id,
                )
                connector = await connector_service.get_connector(
                    connection.connection_id
                )
                if connector:
                    subscription_id = connection.config.get("webhook_channel_id")
                    await connector.cleanup_subscription(subscription_id)
                    logger.info(
                        "Cancelled subscription", subscription_id=subscription_id
                    )
            except Exception as e:
                logger.error(
                    "Failed to cancel subscription",
                    connection_id=connection.connection_id,
                    error=str(e),
                )

        logger.info(
            "Finished cancelling subscriptions",
            subscription_count=len(active_connections),
        )

    except Exception as e:
        logger.error("Failed to cleanup subscriptions", error=str(e))


if __name__ == "__main__":
    import uvicorn

    # TUI check already handled at top of file
    # Register cleanup function
    atexit.register(cleanup)

    # Create app asynchronously
    app = asyncio.run(create_app())

    # Enable or disable HTTP access logging events
    access_log = os.getenv("ACCESS_LOG", "true").lower() == "true"

    # Run the server (startup tasks now handled by FastAPI startup event)
    uvicorn.run(
        app,
        workers=1,
        host="0.0.0.0",
        port=8000,
        reload=False,  # Disable reload since we're running from main
        access_log=access_log,
    )
