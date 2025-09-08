import sys

# Configure structured logging early
from connectors.langflow_connector_service import LangflowConnectorService
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
    router,
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
    DISABLE_INGEST_WITH_LANGFLOW,
    INDEX_BODY,
    INDEX_NAME,
    SESSION_SECRET,
    clients,
    is_no_auth_mode,
)

# Existing services
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
from api import (
    router,
    nudges,
    upload,
    search,
    chat,
    auth,
    connectors,
    tasks,
    oidc,
    knowledge_filter,
    settings,
)


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
        logger.info("Ingesting default documents when ready", disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW)
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
    
    logger.info(
        "Using Langflow ingestion pipeline for default documents",
        file_count=len(file_paths),
    )
    
    success_count = 0
    error_count = 0
    
    for file_path in file_paths:
        try:
            logger.debug("Processing file with Langflow pipeline", file_path=file_path)
            
            # Read file content
            with open(file_path, 'rb') as f:
                content = f.read()
            
            # Create file tuple for upload
            filename = os.path.basename(file_path)
            # Determine content type based on file extension
            import mimetypes
            content_type, _ = mimetypes.guess_type(filename)
            if not content_type:
                content_type = 'application/octet-stream'
            
            file_tuple = (filename, content, content_type)
            
            # Use langflow upload_and_ingest_file method
            result = await langflow_file_service.upload_and_ingest_file(
                file_tuple=file_tuple,
                jwt_token=None,  # No auth for default documents
                delete_after_ingest=True,  # Clean up after ingestion
            )
            
            logger.info(
                "Successfully ingested file via Langflow",
                file_path=file_path,
                result_status=result.get("status"),
            )
            success_count += 1
            
        except Exception as e:
            logger.error(
                "Failed to ingest file via Langflow",
                file_path=file_path,
                error=str(e),
            )
            error_count += 1
    
    logger.info(
        "Langflow ingestion completed",
        success_count=success_count,
        error_count=error_count,
        total_files=len(file_paths),
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
    connector_service = LangflowConnectorService(
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
            "/router/upload_ingest",
            require_auth(services["session_manager"])(
                partial(
                    router.upload_ingest_router,
                    document_service=services["document_service"],
                    langflow_file_service=services["langflow_file_service"],
                    session_manager=services["session_manager"],
                )
            ),
            methods=["POST"],
        ),
    ]