"""Public /v2/* route registrations (API-key auth)."""

from fastapi import FastAPI

from api.v2 import files as v2_files


def register_public_v2_routes(app: FastAPI):

    # Files endpoints (composite-agg cursor pagination)
    app.add_api_route(
        "/v2/files/search",
        v2_files.search_files,
        methods=["GET"],
        tags=["public"],
    )
    app.add_api_route(
        "/v2/files",
        v2_files.list_files,
        methods=["GET"],
        tags=["public"],
    )
