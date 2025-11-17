# Configure structured logging early
from connectors.langflow_connector_service import LangflowConnectorService
from connectors.service import ConnectorService
from services.flows_service import FlowsService
from utils.embeddings import create_dynamic_index_body
from utils.logging_config import configure_from_env, get_logger

configure_from_env()
logger = get_logger(__name__)

import asyncio
import atexit
import mimetypes
import multiprocessing
import os
import subprocess
from functools import partial

from starlette.applications import Starlette
from starlette.routing import Route

# Set multiprocessing start method to 'spawn' for CUDA compatibility
multiprocessing.set_start_method("spawn", force=True)

# Create process pool FIRST, before any torch/CUDA imports
from utils.process_pool import process_pool  # isort: skip
import torch

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

# Existing services
from api.connector_router import ConnectorRouter
from auth_middleware import optional_auth, require_auth

# Configuration and setup
from config.settings import (
    DISABLE_INGEST_WITH_LANGFLOW,
    INDEX_BODY,
    INDEX_NAME,
    SESSION_SECRET,
    clients,
    get_embedding_model,
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

logger.info(
    "CUDA device information",
    cuda_available=torch.cuda.is_available(),
    cuda_version=torch.version.cuda,
)


async def wait_for_opensearch():
    """Wait for OpenSearch to be ready with retries"""
    max_retries = 30
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            await clients.opensearch.info()
            logger.info("OpenSearch is ready")
            return
        except Exception as e:
            logger.warning(
                "OpenSearch not ready yet",
                attempt=attempt + 1,
                max_retries=max_retries,
                error=str(e),
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                raise Exception("OpenSearch failed to become ready")


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
        # Check if index already exists
        if await clients.opensearch.indices.exists(index=INDEX_NAME):
            logger.debug("OpenSearch index already exists", index_name=INDEX_NAME)
            return

        # Create the index with hard-coded INDEX_BODY (uses OpenAI embedding dimensions)
        await clients.opensearch.indices.create(index=INDEX_NAME, body=INDEX_BODY)
        logger.info(
            "Created OpenSearch index for traditional connector service",
            index_name=INDEX_NAME,
            vector_dimensions=INDEX_BODY["mappings"]["properties"]["chunk_embedding"][
                "dimension"
            ],
        )

    except Exception as e:
        logger.error(
            "Failed to initialize OpenSearch index for traditional connector service",
            error=str(e),
            index_name=INDEX_NAME,
        )
        # Don't raise the exception to avoid breaking the initialization
        # The service can still function, document operations might fail later


async def init_index():
    """Initialize OpenSearch index and security roles"""
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
    if not await clients.opensearch.indices.exists(index=INDEX_NAME):
        await clients.opensearch.indices.create(
            index=INDEX_NAME, body=dynamic_index_body
        )
        logger.info(
            "Created OpenSearch index",
            index_name=INDEX_NAME,
            embedding_model=embedding_model,
        )
    else:
        logger.info(
            "Index already exists, skipping creation",
            index_name=INDEX_NAME,
            embedding_model=embedding_model,
        )

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
    else:
        logger.info(
            "Knowledge filters index already exists, skipping creation",
            index_name=knowledge_filter_index_name,
        )

    # Configure alerting plugin security settings
    await configure_alerting_security()


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
            raise
    else:
        # Ensure correct permissions on existing keys
        try:
            os.chmod(private_key_path, 0o600)
            os.chmod(public_key_path, 0o644)
            logger.info("RSA keys already exist, ensured correct permissions")
        except OSError as e:
            logger.warning("Failed to set permissions on existing keys", error=str(e))


async def init_index_when_ready():
    """Initialize OpenSearch index when it becomes available"""
    try:
        await init_index()
        logger.info("OpenSearch index initialization completed successfully")
    except Exception as e:
        logger.error("OpenSearch index initialization failed", error=str(e))
        logger.warning(
            "OIDC endpoints will still work, but document operations may fail until OpenSearch is ready"
        )


async def ingest_default_documents_when_ready(services):
    """Scan the local documents folder and ingest files like a non-auth upload."""
    try:
        logger.info(
            "Ingesting default documents when ready",
            disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW,
        )
        base_dir = os.path.abspath(os.path.join(os.getcwd(), "documents"))
        if not os.path.isdir(base_dir):
            logger.info(
                "Default documents directory not found; skipping ingestion",
                base_dir=base_dir,
            )
            return

        # Collect files recursively
        file_paths = [
            os.path.join(root, fn)
            for root, _, files in os.walk(base_dir)
            for fn in files
        ]

        if not file_paths:
            logger.info(
                "No default documents found; nothing to ingest", base_dir=base_dir
            )
            return

        if DISABLE_INGEST_WITH_LANGFLOW:
            await _ingest_default_documents_openrag(services, file_paths)
        else:
            await _ingest_default_documents_langflow(services, file_paths)

    except Exception as e:
        logger.error("Default documents ingestion failed", error=str(e))


async def _ingest_default_documents_langflow(services, file_paths):
    """Ingest default documents using Langflow upload-ingest-delete pipeline."""
    langflow_file_service = services["langflow_file_service"]
    session_manager = services["session_manager"]
    task_service = services["task_service"]

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
        "OpenSearchHybrid-Ve6bS": {
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
        replace_duplicates=False,
    )

    logger.info(
        "Started Langflow ingestion task for default documents",
        task_id=task_id,
        file_count=len(file_paths),
    )


async def _ingest_default_documents_openrag(services, file_paths):
    """Ingest default documents using traditional OpenRAG processor."""
    logger.info(
        "Using traditional OpenRAG ingestion for default documents",
        file_count=len(file_paths),
    )

    # Build a processor that DOES NOT set 'owner' on documents (owner_user_id=None)
    from models.processors import DocumentFileProcessor

    processor = DocumentFileProcessor(
        services["document_service"],
        owner_user_id=None,
        jwt_token=None,
        owner_name=None,
        owner_email=None,
        is_sample_data=True,  # Mark as sample data
    )

    task_id = await services["task_service"].create_custom_task(
        "anonymous", file_paths, processor
    )
    logger.info(
        "Started traditional OpenRAG ingestion task",
        task_id=task_id,
        file_count=len(file_paths),
    )


async def startup_tasks(services):
    """Startup tasks"""
    logger.info("Starting startup tasks")
    # Only initialize basic OpenSearch connection, not the index
    # Index will be created after onboarding when we know the embedding model
    await wait_for_opensearch()

    if DISABLE_INGEST_WITH_LANGFLOW:
        await _ensure_opensearch_index()

    # Configure alerting security
    await configure_alerting_security()


async def initialize_services():
    """Initialize all services and their dependencies"""
    # Generate JWT keys if they don't exist
    generate_jwt_keys()

    # Initialize clients (now async to generate Langflow API key)
    await clients.initialize()

    # Initialize session manager
    session_manager = SessionManager(SESSION_SECRET)

    # Initialize services
    document_service = DocumentService(session_manager=session_manager)
    search_service = SearchService(session_manager)
    task_service = TaskService(document_service, process_pool)
    chat_service = ChatService()
    flows_service = FlowsService()
    knowledge_filter_service = KnowledgeFilterService(session_manager)
    models_service = ModelsService()
    monitor_service = MonitorService(session_manager)

    # Set process pool for document service
    document_service.process_pool = process_pool

    # Initialize connector service

    # Initialize both connector services
    langflow_connector_service = LangflowConnectorService(
        task_service=task_service,
        session_manager=session_manager,
    )
    openrag_connector_service = ConnectorService(
        patched_async_client=clients,  # Pass the clients object itself
        process_pool=process_pool,
        embed_model=get_embedding_model(),
        index_name=INDEX_NAME,
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
    else:
        logger.info("[CONNECTORS] Skipping connection loading in no-auth mode")

    langflow_file_service = LangflowFileService()

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
    }


async def create_app():
    """Create and configure the Starlette application"""
    services = await initialize_services()

    # Create route handlers with service dependencies injected
    routes = [
        # Langflow Files endpoints
        Route(
            "/langflow/files/upload",
            optional_auth(services["session_manager"])(
                partial(
                    langflow_files.upload_user_file,
                    langflow_file_service=services["langflow_file_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/langflow/ingest",
            require_auth(services["session_manager"])(
                partial(
                    langflow_files.run_ingestion,
                    langflow_file_service=services["langflow_file_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/langflow/files",
            require_auth(services["session_manager"])(
                partial(
                    langflow_files.delete_user_files,
                    langflow_file_service=services["langflow_file_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["DELETE"],
        ),
        Route(
            "/langflow/upload_ingest",
            require_auth(services["session_manager"])(
                partial(
                    langflow_files.upload_and_ingest_user_file,
                    langflow_file_service=services["langflow_file_service"],
                    session_manager=services["session_manager"],
                    task_service=services["task_service"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/upload_context",
            require_auth(services["session_manager"])(
                partial(
                    upload.upload_context,
                    document_service=services["document_service"],
                    chat_service=services["chat_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/upload_path",
            require_auth(services["session_manager"])(
                partial(
                    upload.upload_path,
                    task_service=services["task_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/upload_options",
            require_auth(services["session_manager"])(
                partial(
                    upload.upload_options, session_manager=services["session_manager"]
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/upload_bucket",
            require_auth(services["session_manager"])(
                partial(
                    upload.upload_bucket,
                    task_service=services["task_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/tasks/{task_id}",
            require_auth(services["session_manager"])(
                partial(
                    tasks.task_status,
                    task_service=services["task_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/tasks",
            require_auth(services["session_manager"])(
                partial(
                    tasks.all_tasks,
                    task_service=services["task_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/tasks/{task_id}/cancel",
            require_auth(services["session_manager"])(
                partial(
                    tasks.cancel_task,
                    task_service=services["task_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        # Search endpoint
        Route(
            "/search",
            require_auth(services["session_manager"])(
                partial(
                    search.search,
                    search_service=services["search_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        # Knowledge Filter endpoints
        Route(
            "/knowledge-filter",
            require_auth(services["session_manager"])(
                partial(
                    knowledge_filter.create_knowledge_filter,
                    knowledge_filter_service=services["knowledge_filter_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/knowledge-filter/search",
            require_auth(services["session_manager"])(
                partial(
                    knowledge_filter.search_knowledge_filters,
                    knowledge_filter_service=services["knowledge_filter_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/knowledge-filter/{filter_id}",
            require_auth(services["session_manager"])(
                partial(
                    knowledge_filter.get_knowledge_filter,
                    knowledge_filter_service=services["knowledge_filter_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/knowledge-filter/{filter_id}",
            require_auth(services["session_manager"])(
                partial(
                    knowledge_filter.update_knowledge_filter,
                    knowledge_filter_service=services["knowledge_filter_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["PUT"],
        ),
        Route(
            "/knowledge-filter/{filter_id}",
            require_auth(services["session_manager"])(
                partial(
                    knowledge_filter.delete_knowledge_filter,
                    knowledge_filter_service=services["knowledge_filter_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["DELETE"],
        ),
        # Knowledge Filter Subscription endpoints
        Route(
            "/knowledge-filter/{filter_id}/subscribe",
            require_auth(services["session_manager"])(
                partial(
                    knowledge_filter.subscribe_to_knowledge_filter,
                    knowledge_filter_service=services["knowledge_filter_service"],
                    monitor_service=services["monitor_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/knowledge-filter/{filter_id}/subscriptions",
            require_auth(services["session_manager"])(
                partial(
                    knowledge_filter.list_knowledge_filter_subscriptions,
                    knowledge_filter_service=services["knowledge_filter_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/knowledge-filter/{filter_id}/subscribe/{subscription_id}",
            require_auth(services["session_manager"])(
                partial(
                    knowledge_filter.cancel_knowledge_filter_subscription,
                    knowledge_filter_service=services["knowledge_filter_service"],
                    monitor_service=services["monitor_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["DELETE"],
        ),
        # Knowledge Filter Webhook endpoint (no auth required - called by OpenSearch)
        Route(
            "/knowledge-filter/{filter_id}/webhook/{subscription_id}",
            partial(
                knowledge_filter.knowledge_filter_webhook,
                knowledge_filter_service=services["knowledge_filter_service"],
                session_manager=services["session_manager"],
            ),
            methods=["POST"],
        ),
        # Chat endpoints
        Route(
            "/chat",
            require_auth(services["session_manager"])(
                partial(
                    chat.chat_endpoint,
                    chat_service=services["chat_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/langflow",
            require_auth(services["session_manager"])(
                partial(
                    chat.langflow_endpoint,
                    chat_service=services["chat_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        # Chat history endpoints
        Route(
            "/chat/history",
            require_auth(services["session_manager"])(
                partial(
                    chat.chat_history_endpoint,
                    chat_service=services["chat_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/langflow/history",
            require_auth(services["session_manager"])(
                partial(
                    chat.langflow_history_endpoint,
                    chat_service=services["chat_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        # Session deletion endpoint
        Route(
            "/sessions/{session_id}",
            require_auth(services["session_manager"])(
                partial(
                    chat.delete_session_endpoint,
                    chat_service=services["chat_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["DELETE"],
        ),
        # Authentication endpoints
        Route(
            "/auth/init",
            optional_auth(services["session_manager"])(
                partial(
                    auth.auth_init,
                    auth_service=services["auth_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/auth/callback",
            partial(
                auth.auth_callback,
                auth_service=services["auth_service"],
                session_manager=services["session_manager"],
            ),
            methods=["POST"],
        ),
        Route(
            "/auth/me",
            optional_auth(services["session_manager"])(
                partial(
                    auth.auth_me,
                    auth_service=services["auth_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/auth/logout",
            require_auth(services["session_manager"])(
                partial(
                    auth.auth_logout,
                    auth_service=services["auth_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        # Connector endpoints
        Route(
            "/connectors",
            require_auth(services["session_manager"])(
                partial(
                    connectors.list_connectors,
                    connector_service=services["connector_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/connectors/{connector_type}/sync",
            require_auth(services["session_manager"])(
                partial(
                    connectors.connector_sync,
                    connector_service=services["connector_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/connectors/{connector_type}/status",
            require_auth(services["session_manager"])(
                partial(
                    connectors.connector_status,
                    connector_service=services["connector_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/connectors/{connector_type}/token",
            require_auth(services["session_manager"])(
                partial(
                    connectors.connector_token,
                    connector_service=services["connector_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/connectors/{connector_type}/webhook",
            partial(
                connectors.connector_webhook,
                connector_service=services["connector_service"],
                session_manager=services["session_manager"],
            ),
            methods=["POST", "GET"],
        ),
        # Document endpoints
        Route(
            "/documents/check-filename",
            require_auth(services["session_manager"])(
                partial(
                    documents.check_filename_exists,
                    document_service=services["document_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/documents/delete-by-filename",
            require_auth(services["session_manager"])(
                partial(
                    documents.delete_documents_by_filename,
                    document_service=services["document_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        # OIDC endpoints
        Route(
            "/.well-known/openid-configuration",
            partial(oidc.oidc_discovery, session_manager=services["session_manager"]),
            methods=["GET"],
        ),
        Route(
            "/auth/jwks",
            partial(oidc.jwks_endpoint, session_manager=services["session_manager"]),
            methods=["GET"],
        ),
        Route(
            "/auth/introspect",
            partial(
                oidc.token_introspection, session_manager=services["session_manager"]
            ),
            methods=["POST"],
        ),
        # Settings endpoints
        Route(
            "/settings",
            require_auth(services["session_manager"])(
                partial(
                    settings.get_settings, session_manager=services["session_manager"]
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/settings",
            require_auth(services["session_manager"])(
                partial(
                    settings.update_settings,
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        # Provider health check endpoint
        Route(
            "/provider/health",
            require_auth(services["session_manager"])(
                provider_health.check_provider_health
            ),
            methods=["GET"],
        ),
        # Models endpoints
        Route(
            "/models/openai",
            require_auth(services["session_manager"])(
                partial(
                    models.get_openai_models,
                    models_service=services["models_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/models/anthropic",
            require_auth(services["session_manager"])(
                partial(
                    models.get_anthropic_models,
                    models_service=services["models_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/models/ollama",
            require_auth(services["session_manager"])(
                partial(
                    models.get_ollama_models,
                    models_service=services["models_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET"],
        ),
        Route(
            "/models/ibm",
            require_auth(services["session_manager"])(
                partial(
                    models.get_ibm_models,
                    models_service=services["models_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["GET", "POST"],
        ),
        # Onboarding endpoint
        Route(
            "/onboarding",
            require_auth(services["session_manager"])(
                partial(settings.onboarding, flows_service=services["flows_service"])
            ),
            methods=["POST"],
        ),
        # Docling preset update endpoint
        Route(
            "/settings/docling-preset",
            require_auth(services["session_manager"])(
                partial(
                    settings.update_docling_preset,
                    session_manager=services["session_manager"],
                )
            ),
            methods=["PATCH"],
        ),
        Route(
            "/nudges",
            require_auth(services["session_manager"])(
                partial(
                    nudges.nudges_from_kb_endpoint,
                    chat_service=services["chat_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/nudges/{chat_id}",
            require_auth(services["session_manager"])(
                partial(
                    nudges.nudges_from_chat_id_endpoint,
                    chat_service=services["chat_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/reset-flow/{flow_type}",
            require_auth(services["session_manager"])(
                partial(
                    flows.reset_flow_endpoint,
                    chat_service=services["flows_service"],
                )
            ),
            methods=["POST"],
        ),
        Route(
            "/router/upload_ingest",
            require_auth(services["session_manager"])(
                partial(
                    router.upload_ingest_router,
                    document_service=services["document_service"],
                    langflow_file_service=services["langflow_file_service"],
                    session_manager=services["session_manager"],
                    task_service=services["task_service"],
                )
            ),
            methods=["POST"],
        ),
        # Docling service proxy
        Route(
            "/docling/health",
            partial(docling.health),
            methods=["GET"],
        ),
    ]

    app = Starlette(debug=True, routes=routes)
    app.state.services = services  # Store services for cleanup
    app.state.background_tasks = set()

    # Add startup event handler
    @app.on_event("startup")
    async def startup_event():
        # Start index initialization in background to avoid blocking OIDC endpoints
        t1 = asyncio.create_task(startup_tasks(services))
        app.state.background_tasks.add(t1)
        t1.add_done_callback(app.state.background_tasks.discard)

    # Add shutdown event handler
    @app.on_event("shutdown")
    async def shutdown_event():
        await cleanup_subscriptions_proper(services)
        # Cleanup async clients
        await clients.cleanup()

    return app


def cleanup():
    """Cleanup on application shutdown"""
    # Cleanup process pools only (webhooks handled by Starlette shutdown)
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

    # Run the server (startup tasks now handled by Starlette startup event)
    uvicorn.run(
        app,
        workers=1,
        host="0.0.0.0",
        port=8000,
        reload=False,  # Disable reload since we're running from main
    )
