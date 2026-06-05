"""Internal v0 route registrations.

All endpoints not under /v1/* and not the MCP mount.

Auth and service injection are handled inside each handler via FastAPI
Depends, not here. This module only wires URL → handler.
"""

from fastapi import FastAPI, status

from api import (
    auth,
    chat,
    connectors,
    docling,
    documents,
    files,
    flows,
    knowledge_filter,
    langflow_files,
    langflow_ingest,
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
from api import keys as api_keys
from api.health import health_check, opensearch_health_ready
from api.schemas.tasks import ErrorResponse, TaskRetryResponse
from connectors.registry import get_connector_classes


def register_internal_routes(app: FastAPI):
    # Langflow Files endpoints
    app.add_api_route(
        "/langflow/files/upload",
        langflow_files.upload_user_file,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/langflow/ingest",
        langflow_files.run_ingestion,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/langflow/files",
        langflow_files.delete_user_files,
        methods=["DELETE"],
        tags=["internal"],
    )
    app.add_api_route(
        "/langflow/upload_ingest",
        langflow_files.upload_and_ingest_user_file,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/internal/ingest/chunks",
        langflow_ingest.ingest_langflow_chunks,
        methods=["POST"],
        tags=["internal"],
    )

    # Upload endpoints
    app.add_api_route("/upload_context", upload.upload_context, methods=["POST"], tags=["internal"])
    app.add_api_route("/upload_path", upload.upload_path, methods=["POST"], tags=["internal"])
    app.add_api_route("/upload_options", upload.upload_options, methods=["GET"], tags=["internal"])
    app.add_api_route("/upload_bucket", upload.upload_bucket, methods=["POST"], tags=["internal"])

    # Task endpoints
    # Literal sub-paths must be registered before the parameterised /{task_id}
    # so Starlette does not absorb "enhanced" as a task_id value.
    app.add_api_route(
        "/tasks/enhanced", tasks.all_tasks_enhanced, methods=["GET"], tags=["internal"]
    )
    app.add_api_route("/tasks/{task_id}", tasks.task_status, methods=["GET"], tags=["internal"])
    app.add_api_route(
        "/tasks/{task_id}/enhanced",
        tasks.task_status_enhanced,
        methods=["GET"],
        tags=["internal"],
    )
    app.add_api_route("/tasks", tasks.all_tasks, methods=["GET"], tags=["internal"])
    app.add_api_route(
        "/tasks/{task_id}/retry",
        tasks.retry_task,
        methods=["POST"],
        tags=["internal"],
        status_code=status.HTTP_202_ACCEPTED,
        response_model=TaskRetryResponse,
        responses={
            400: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )
    app.add_api_route(
        "/tasks/{task_id}/cancel",
        tasks.cancel_task,
        methods=["POST"],
        tags=["internal"],
    )

    # Search endpoint
    app.add_api_route("/search", search.search, methods=["POST"], tags=["internal"])

    # File listing/search endpoints
    app.add_api_route("/files", files.list_files, methods=["GET"], tags=["internal"])
    app.add_api_route("/files/search", files.search_files, methods=["GET"], tags=["internal"])

    # Knowledge Filter endpoints
    app.add_api_route(
        "/knowledge-filter",
        knowledge_filter.create_knowledge_filter,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/knowledge-filter/search",
        knowledge_filter.search_knowledge_filters,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/knowledge-filter/{filter_id}",
        knowledge_filter.get_knowledge_filter,
        methods=["GET"],
        tags=["internal"],
    )
    app.add_api_route(
        "/knowledge-filter/{filter_id}",
        knowledge_filter.update_knowledge_filter,
        methods=["PUT"],
        tags=["internal"],
    )
    app.add_api_route(
        "/knowledge-filter/{filter_id}",
        knowledge_filter.delete_knowledge_filter,
        methods=["DELETE"],
        tags=["internal"],
    )

    # Knowledge Filter Subscription endpoints
    app.add_api_route(
        "/knowledge-filter/{filter_id}/subscribe",
        knowledge_filter.subscribe_to_knowledge_filter,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/knowledge-filter/{filter_id}/subscriptions",
        knowledge_filter.list_knowledge_filter_subscriptions,
        methods=["GET"],
        tags=["internal"],
    )
    app.add_api_route(
        "/knowledge-filter/{filter_id}/subscribe/{subscription_id}",
        knowledge_filter.cancel_knowledge_filter_subscription,
        methods=["DELETE"],
        tags=["internal"],
    )

    # Knowledge Filter Webhook endpoint (no auth required - called by OpenSearch)
    app.add_api_route(
        "/knowledge-filter/{filter_id}/webhook/{subscription_id}",
        knowledge_filter.knowledge_filter_webhook,
        methods=["POST"],
        tags=["internal"],
    )

    # Chat endpoints
    app.add_api_route("/chat", chat.chat_endpoint, methods=["POST"], tags=["internal"])
    app.add_api_route("/langflow", chat.langflow_endpoint, methods=["POST"], tags=["internal"])

    # Chat history endpoints
    app.add_api_route(
        "/chat/history", chat.chat_history_endpoint, methods=["GET"], tags=["internal"]
    )
    app.add_api_route(
        "/langflow/history",
        chat.langflow_history_endpoint,
        methods=["GET"],
        tags=["internal"],
    )

    # Session deletion endpoint
    app.add_api_route(
        "/sessions/{session_id}",
        chat.delete_session_endpoint,
        methods=["DELETE"],
        tags=["internal"],
    )

    # Authentication endpoints
    app.add_api_route("/auth/init", auth.auth_init, methods=["POST"], tags=["internal"])
    app.add_api_route("/auth/callback", auth.auth_callback, methods=["POST"], tags=["internal"])
    app.add_api_route("/auth/me", auth.auth_me, methods=["GET"], tags=["internal"])
    app.add_api_route("/auth/logout", auth.auth_logout, methods=["POST"], tags=["internal"])
    app.add_api_route("/auth/ibm/login", auth.ibm_login, methods=["POST"], tags=["internal"])

    # Connector endpoints
    app.add_api_route("/connectors", connectors.list_connectors, methods=["GET"], tags=["internal"])
    # Per-connector routes (defaults, configure, bucket listing, etc.) — registered before
    # the generic /{connector_type}/... routes to avoid path shadowing.
    for cls in get_connector_classes():
        cls.register_routes(app)
    app.add_api_route(
        "/connectors/{connector_type}/sync",
        connectors.connector_sync,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/check-duplicates",
        connectors.connector_check_duplicates,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/sync-preview",
        connectors.connector_sync_preview,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/sync-all",
        connectors.sync_all_connectors,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/sync-all-preview",
        connectors.connectors_sync_all_preview,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/status",
        connectors.connector_status,
        methods=["GET"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/token",
        connectors.connector_token,
        methods=["GET"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/disconnect",
        connectors.connector_disconnect,
        methods=["DELETE"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/webhook",
        connectors.connector_webhook,
        methods=["POST", "GET"],
        tags=["internal"],
    )
    app.add_api_route(
        "/connectors/{connector_type}/{connection_id}/browse",
        connectors.browse_connection_files,
        methods=["GET"],
        tags=["internal"],
    )

    # Document endpoints
    app.add_api_route(
        "/documents/check-filename",
        documents.check_filename_exists,
        methods=["GET"],
        tags=["internal"],
    )
    app.add_api_route(
        "/documents/delete-by-filename",
        documents.delete_documents_by_filename,
        methods=["POST"],
        tags=["internal"],
    )

    # OIDC endpoints
    app.add_api_route(
        "/.well-known/openid-configuration",
        oidc.oidc_discovery,
        methods=["GET"],
        tags=["internal"],
    )
    app.add_api_route("/auth/jwks", oidc.jwks_endpoint, methods=["GET"], tags=["internal"])
    app.add_api_route(
        "/auth/introspect",
        oidc.token_introspection,
        methods=["POST"],
        tags=["internal"],
    )

    # Settings endpoints
    app.add_api_route("/settings", settings.get_settings, methods=["GET"], tags=["internal"])
    app.add_api_route("/settings", settings.update_settings, methods=["POST"], tags=["internal"])
    app.add_api_route(
        "/onboarding/state",
        settings.update_onboarding_state,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/openrag-docs/refresh",
        settings.refresh_openrag_docs,
        methods=["POST"],
        tags=["internal"],
    )

    # Provider health check endpoint
    app.add_api_route(
        "/provider/health",
        provider_health.check_provider_health,
        methods=["GET"],
        tags=["internal"],
    )

    # Health check endpoints
    app.add_api_route("/health", health_check, methods=["GET"], tags=["internal"])
    app.add_api_route("/search/health", opensearch_health_ready, methods=["GET"], tags=["internal"])

    # Models endpoints
    app.add_api_route(
        "/models/openai", models.get_openai_models, methods=["POST"], tags=["internal"]
    )
    app.add_api_route(
        "/models/anthropic",
        models.get_anthropic_models,
        methods=["POST"],
        tags=["internal"],
    )
    app.add_api_route(
        "/models/ollama", models.get_ollama_models, methods=["GET"], tags=["internal"]
    )
    app.add_api_route("/models/ibm", models.get_ibm_models, methods=["POST"], tags=["internal"])

    # Onboarding endpoints
    app.add_api_route("/onboarding", settings.onboarding, methods=["POST"], tags=["internal"])
    app.add_api_route(
        "/onboarding/rollback",
        settings.rollback_onboarding,
        methods=["POST"],
        tags=["internal"],
    )

    # Docling preset update endpoint
    app.add_api_route(
        "/settings/docling-preset",
        settings.update_docling_preset,
        methods=["PATCH"],
        tags=["internal"],
    )

    # Nudges endpoints
    app.add_api_route(
        "/nudges", nudges.nudges_from_kb_endpoint, methods=["POST"], tags=["internal"]
    )
    app.add_api_route(
        "/nudges/{chat_id}",
        nudges.nudges_from_chat_id_endpoint,
        methods=["POST"],
        tags=["internal"],
    )

    # Flow reset endpoint
    app.add_api_route(
        "/reset-flow/{flow_type}",
        flows.reset_flow_endpoint,
        methods=["POST"],
        tags=["internal"],
    )

    # Router upload ingest endpoint
    app.add_api_route(
        "/router/upload_ingest",
        router.upload_ingest_router,
        methods=["POST"],
        tags=["internal"],
    )

    # Docling service proxy
    app.add_api_route("/docling/health", docling.health, methods=["GET"], tags=["internal"])

    # ===== Users Endpoints (JWT auth) =====
    from api import config as config_api
    from api import users as users_api

    app.include_router(users_api.router)
    # Public — must work pre-auth so the onboarding wizard can render.
    app.include_router(config_api.router)

    # ===== API Key Management Endpoints (JWT auth for UI) =====
    app.add_api_route("/keys", api_keys.list_keys_endpoint, methods=["GET"], tags=["internal"])
    app.add_api_route("/keys", api_keys.create_key_endpoint, methods=["POST"], tags=["internal"])
    app.add_api_route(
        "/keys/{key_id}",
        api_keys.revoke_key_endpoint,
        methods=["DELETE"],
        tags=["internal"],
    )
