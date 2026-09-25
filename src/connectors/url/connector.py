"""Discovery metadata for the managed URL connector."""

from typing import Any

from fastapi import Depends

from config.settings import is_url_connector_enabled
from connectors.base import BaseConnector, ConnectorDocument


class URLConnector(BaseConnector):
    CONNECTOR_TYPE = "url"
    CONNECTOR_KIND = "managed"
    ALWAYS_CONNECTED = True
    CONNECTOR_NAME = "URL"
    CONNECTOR_DESCRIPTION = "Crawl public website content into OpenRAG"
    CONNECTOR_ICON = "url"

    @classmethod
    def is_available(cls, manager, user_id: str | None = None) -> bool:
        return is_url_connector_enabled()

    @classmethod
    def register_routes(cls, app) -> None:
        if not is_url_connector_enabled():
            return

        from .api import (
            create_source,
            delete_page,
            delete_source,
            get_source,
            list_sources,
            require_url_connector_enabled,
            sync_page,
            sync_source,
        )

        route_dependencies = [Depends(require_url_connector_enabled)]

        app.add_api_route(
            "/connectors/url/sources",
            create_source,
            methods=["POST"],
            tags=["internal"],
            dependencies=route_dependencies,
        )
        app.add_api_route(
            "/connectors/url/sources",
            list_sources,
            methods=["GET"],
            tags=["internal"],
            dependencies=route_dependencies,
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}",
            get_source,
            methods=["GET"],
            tags=["internal"],
            dependencies=route_dependencies,
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}/sync",
            sync_source,
            methods=["POST"],
            tags=["internal"],
            dependencies=route_dependencies,
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}",
            delete_source,
            methods=["DELETE"],
            tags=["internal"],
            dependencies=route_dependencies,
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}/pages/{page_id}/sync",
            sync_page,
            methods=["POST"],
            tags=["internal"],
            dependencies=route_dependencies,
        )
        app.add_api_route(
            "/connectors/url/sources/{source_id}/pages/{page_id}",
            delete_page,
            methods=["DELETE"],
            tags=["internal"],
            dependencies=route_dependencies,
        )

    async def authenticate(self) -> bool:
        return True

    async def setup_subscription(self) -> str:
        raise NotImplementedError("URL sources do not use subscriptions")

    async def list_files(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("URL sources use /connectors/url/sources")

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        raise NotImplementedError("URL sources use /connectors/url/sources")

    async def handle_webhook(self, payload: dict[str, Any]) -> list[str]:
        raise NotImplementedError("URL sources do not use webhooks")

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        raise NotImplementedError("URL sources do not use subscriptions")
