"""Discovery metadata for the managed URL connector."""

from typing import Any

from connectors.base import BaseConnector


class URLConnector(BaseConnector):
    CONNECTOR_TYPE = "url"
    CONNECTOR_KIND = "managed"
    ALWAYS_CONNECTED = True
    CONNECTOR_NAME = "URL"
    CONNECTOR_DESCRIPTION = "Crawl public website content into OpenRAG"
    CONNECTOR_ICON = "url"

    @classmethod
    def is_available(cls, manager, user_id: str | None = None) -> bool:
        return True

    @classmethod
    def register_routes(cls, app) -> None:
        from .api import (
            create_source,
            delete_page,
            delete_source,
            get_source,
            list_sources,
            sync_page,
            sync_source,
        )

        app.add_api_route(
            "/connectors/url/sources", create_source, methods=["POST"], tags=["internal"]
        )
        app.add_api_route(
            "/connectors/url/sources", list_sources, methods=["GET"], tags=["internal"]
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}", get_source, methods=["GET"], tags=["internal"]
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}/sync",
            sync_source,
            methods=["POST"],
            tags=["internal"],
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}",
            delete_source,
            methods=["DELETE"],
            tags=["internal"],
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}/pages/{page_id}/sync",
            sync_page,
            methods=["POST"],
            tags=["internal"],
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}/pages/{page_id}",
            delete_page,
            methods=["DELETE"],
            tags=["internal"],
        )

    async def authenticate(self) -> bool:
        return True

    async def setup_subscription(self) -> str:
        raise NotImplementedError("URL sources do not use subscriptions")

    async def list_files(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("URL sources use /connectors/url/sources")
