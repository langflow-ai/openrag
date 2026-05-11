"""Public /v1/* route registrations (API-key auth)."""

from fastapi import FastAPI

from api.v1 import (
    chat as v1_chat,
)
from api.v1 import (
    documents as v1_documents,
)
from api.v1 import (
    knowledge_filters as v1_knowledge_filters,
)
from api.v1 import (
    models as v1_models,
)
from api.v1 import (
    search as v1_search,
)
from api.v1 import (
    settings as v1_settings,
)


def register_public_v1_routes(app: FastAPI):

    # Chat endpoints
    app.add_api_route("/v1/chat", v1_chat.chat_create_endpoint, methods=["POST"], tags=["public"])
    app.add_api_route("/v1/chat", v1_chat.chat_list_endpoint, methods=["GET"], tags=["public"])
    app.add_api_route(
        "/v1/chat/{chat_id}",
        v1_chat.chat_get_endpoint,
        methods=["GET"],
        tags=["public"],
    )
    app.add_api_route(
        "/v1/chat/{chat_id}",
        v1_chat.chat_delete_endpoint,
        methods=["DELETE"],
        tags=["public"],
    )

    # Search endpoint
    app.add_api_route("/v1/search", v1_search.search_endpoint, methods=["POST"], tags=["public"])

    # Documents endpoints
    app.add_api_route(
        "/v1/documents/ingest",
        v1_documents.ingest_endpoint,
        methods=["POST"],
        tags=["public"],
    )
    app.add_api_route(
        "/v1/tasks/{task_id}",
        v1_documents.task_status_endpoint,
        methods=["GET"],
        tags=["public"],
    )
    app.add_api_route(
        "/v1/documents",
        v1_documents.delete_document_endpoint,
        methods=["DELETE"],
        tags=["public"],
    )

    # Settings endpoints
    app.add_api_route(
        "/v1/settings",
        v1_settings.get_settings_endpoint,
        methods=["GET"],
        tags=["public"],
    )
    app.add_api_route(
        "/v1/settings",
        v1_settings.update_settings_endpoint,
        methods=["POST"],
        tags=["public"],
    )

    # Models endpoint
    app.add_api_route(
        "/v1/models/{provider}",
        v1_models.list_models_endpoint,
        methods=["GET"],
        tags=["public"],
    )

    # Knowledge filters endpoints
    app.add_api_route(
        "/v1/knowledge-filters",
        v1_knowledge_filters.create_endpoint,
        methods=["POST"],
        tags=["public"],
    )
    app.add_api_route(
        "/v1/knowledge-filters/search",
        v1_knowledge_filters.search_endpoint,
        methods=["POST"],
        tags=["public"],
    )
    app.add_api_route(
        "/v1/knowledge-filters/{filter_id}",
        v1_knowledge_filters.get_endpoint,
        methods=["GET"],
        tags=["public"],
    )
    app.add_api_route(
        "/v1/knowledge-filters/{filter_id}",
        v1_knowledge_filters.update_endpoint,
        methods=["PUT"],
        tags=["public"],
    )
    app.add_api_route(
        "/v1/knowledge-filters/{filter_id}",
        v1_knowledge_filters.delete_endpoint,
        methods=["DELETE"],
        tags=["public"],
    )
