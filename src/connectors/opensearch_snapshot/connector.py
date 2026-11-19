"""Discovery metadata and route registration for the OpenSearch snapshot connector."""

from typing import Any

from fastapi import Depends

from connectors.base import BaseConnector, ConnectorDocument


class OpenSearchSnapshotConnector(BaseConnector):
    CONNECTOR_TYPE = "opensearch_snapshot"
    CONNECTOR_KIND = "managed"
    ALWAYS_CONNECTED = True
    CONNECTOR_NAME = "OpenSearch snapshot"
    CONNECTOR_DESCRIPTION = (
        "Import indices from an OpenSearch snapshot repository as searchable datasets"
    )
    CONNECTOR_ICON = "opensearch"

    @classmethod
    def is_available(cls, manager, user_id: str | None = None) -> bool:
        from config.settings import is_snapshot_import_available

        return is_snapshot_import_available()[0]

    @classmethod
    def register_routes(cls, app) -> None:
        from . import api
        from .service import SnapshotError

        app.add_exception_handler(SnapshotError, api.snapshot_error_handler)
        base = "/connectors/opensearch_snapshot"
        gated = [Depends(api.require_snapshot_import_enabled)]

        def add(
            path: str,
            endpoint,
            method: str,
            *,
            status_code: int | None = None,
            is_gated: bool = True,
        ) -> None:
            app.add_api_route(
                f"{base}{path}",
                endpoint,
                methods=[method],
                tags=["internal"],
                dependencies=gated if is_gated else [],
                status_code=status_code,
            )

        # The card must be able to ask whether the feature is on, so /status is never gated.
        add("/status", api.get_status, "GET", is_gated=False)
        add("/sources", api.create_source, "POST")
        add("/sources", api.list_sources, "GET")
        add("/sources/{source_id}", api.patch_source, "PATCH")
        add("/sources/{source_id}", api.delete_source, "DELETE")
        add("/sources/{source_id}/snapshots", api.list_snapshots, "GET")
        add("/sources/{source_id}/preflight", api.source_preflight, "POST")
        add("/imports", api.create_import, "POST")
        add("/imports", api.list_imports, "GET")
        add("/imports/{import_id}", api.get_import, "GET")
        add("/imports/{import_id}/datasets/{dataset_id}", api.patch_dataset, "PATCH")
        add("/imports/{import_id}/activate", api.activate_import, "POST")
        add("/imports/{import_id}/share", api.share_import, "POST")
        add("/imports/{import_id}/reimport/preflight", api.reimport_preflight, "POST")
        add("/imports/{import_id}/reimport", api.reimport, "POST")
        add("/imports/{import_id}", api.delete_import, "DELETE")
        add("/datasets", api.list_datasets, "GET")

    async def authenticate(self) -> bool:
        return True

    async def setup_subscription(self) -> str:
        raise NotImplementedError("Snapshot imports do not use subscriptions")

    async def list_files(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Snapshot imports use /connectors/opensearch_snapshot/imports")

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        raise NotImplementedError("Snapshot imports use /connectors/opensearch_snapshot/imports")

    async def handle_webhook(self, payload: dict[str, Any]) -> list[str]:
        raise NotImplementedError("Snapshot imports do not use webhooks")

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        raise NotImplementedError("Snapshot imports do not use subscriptions")
