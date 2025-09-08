import sys

# Configure structured logging early
from utils.logging_config import configure_from_env, get_logger

configure_from_env()
logger = get_logger(__name__)

import asyncio
import atexit
import multiprocessing
import os
import subprocess
from functools import partial

from starlette.applications import Starlette
from starlette.routing import Route

# Set multiprocessing start method to 'spawn' for CUDA compatibility
multiprocessing.set_start_method("spawn", force=True)

# Create process pool FIRST, before any torch/CUDA imports
from utils.process_pool import process_pool

import torch

# API endpoints
from api import (
    auth,
    chat,
    connectors,
    knowledge_filter,
    langflow_files,
    oidc,
    search,
    settings,
    tasks,
    upload,
)
from auth_middleware import optional_auth, require_auth

# Configuration and setup
from config.settings import (
    INDEX_BODY,
    INDEX_NAME,
    SESSION_SECRET,
    clients,
    is_no_auth_mode,
)

# Existing services
from connectors.service import ConnectorService
from services.auth_service import AuthService
from services.chat_service import ChatService

# Services
from services.document_service import DocumentService
from services.knowledge_filter_service import KnowledgeFilterService

# Configuration and setup
# Services
from services.langflow_file_service import LangflowFileService
from services.monitor_service import MonitorService
from services.search_service import SearchService
from services.task_service import TaskService
from session_manager import SessionManager
from utils.process_pool import process_pool

# API endpoints


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


async def init_index():
    """Initialize OpenSearch index and security roles"""
    await wait_for_opensearch()

    # Create documents index
    if not await clients.opensearch.indices.exists(index=INDEX_NAME):
        await clients.opensearch.indices.create(index=INDEX_NAME, body=INDEX_BODY)
        logger.info("Created OpenSearch index", index_name=INDEX_NAME)
    else:
        logger.info("Index already exists, skipping creation", index_name=INDEX_NAME)

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

            logger.info("Generated RSA keys for JWT signing")
        except subprocess.CalledProcessError as e:
            logger.error("Failed to generate RSA keys", error=str(e))
            raise
    else:
        logger.info("RSA keys already exist, skipping generation")


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
        logger.info("Ingesting default documents when ready")
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

        # Build a processor that DOES NOT set 'owner' on documents (owner_user_id=None)
        from models.processors import DocumentFileProcessor

        processor = DocumentFileProcessor(
            services["document_service"],
            owner_user_id=None,
            jwt_token=None,
            owner_name=None,
            owner_email=None,
        )

        task_id = await services["task_service"].create_custom_task(
            "anonymous", file_paths, processor
        )
        logger.info(
            "Started default documents ingestion task",
            task_id=task_id,
            file_count=len(file_paths),
        )
    except Exception as e:
        logger.error("Default documents ingestion failed", error=str(e))


async def startup_tasks(services):
    """Startup tasks"""
    logger.info("Starting startup tasks")
    await init_index()
    await ingest_default_documents_when_ready(services)


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
    knowledge_filter_service = KnowledgeFilterService(session_manager)
    monitor_service = MonitorService(session_manager)

    # Set process pool for document service
    document_service.process_pool = process_pool

    # Initialize connector service
    connector_service = ConnectorService(
        patched_async_client=clients.patched_async_client,
        process_pool=process_pool,
        embed_model="text-embedding-3-small",
        index_name=INDEX_NAME,
        task_service=task_service,
        session_manager=session_manager,
    )

    # Initialize auth service
    auth_service = AuthService(session_manager, connector_service)

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
        "langflow_file_service": langflow_file_service,
        "auth_service": auth_service,
        "connector_service": connector_service,
        "knowledge_filter_service": knowledge_filter_service,
        "monitor_service": monitor_service,
        "session_manager": session_manager,
    }


async def create_app():
    """Create and configure the Starlette application"""
    services = await initialize_services()

    # Create route handlers with service dependencies injected
    routes = [
        # Upload endpoints
        Route(
            "/upload",
            require_auth(services["session_manager"])(
                partial(
                    upload.upload,
                    document_service=services["document_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
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
        # Settings endpoint
        Route(
            "/settings",
            require_auth(services["session_manager"])(
                partial(
                    settings.get_settings, session_manager=services["session_manager"]
                )
            ),
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

    return app


async def startup():
    """Application startup tasks"""
    await init_index()
    # Get services from app state if needed for initialization
    # services = app.state.services
    # await services['connector_service'].initialize()


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
