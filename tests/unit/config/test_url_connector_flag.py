"""Tests for the managed URL connector feature flag."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.search import SearchBody, search
from config.settings import is_url_connector_enabled
from connectors.url.api import require_url_connector_enabled
from connectors.url.connector import URLConnector


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OPENRAG_URL_CONNECTOR_ENABLED", raising=False)

    assert is_url_connector_enabled() is False
    assert URLConnector.is_available(None) is False


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on", "TRUE"])
def test_enabled_with_truthy_values(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_URL_CONNECTOR_ENABLED", flag)

    assert is_url_connector_enabled() is True
    assert URLConnector.is_available(None) is True
    assert require_url_connector_enabled() is None


@pytest.mark.parametrize("flag", ["false", "0", "no", "off", ""])
def test_disabled_values_hide_routes_and_reject_direct_api_access(monkeypatch, flag):
    monkeypatch.setenv("OPENRAG_URL_CONNECTOR_ENABLED", flag)
    app = FastAPI()

    URLConnector.register_routes(app)

    assert "/connectors/url/sources" not in {route.path for route in app.routes}
    with pytest.raises(HTTPException, match="Website connector is not enabled") as exc_info:
        require_url_connector_enabled()
    assert exc_info.value.status_code == 404


def test_enabled_flag_registers_url_routes(monkeypatch):
    monkeypatch.setenv("OPENRAG_URL_CONNECTOR_ENABLED", "true")
    app = FastAPI()

    URLConnector.register_routes(app)

    assert "/connectors/url/sources" in {route.path for route in app.routes}


def test_registered_url_routes_reject_requests_if_the_flag_is_disabled(monkeypatch):
    monkeypatch.setenv("OPENRAG_URL_CONNECTOR_ENABLED", "true")
    app = FastAPI()
    URLConnector.register_routes(app)
    monkeypatch.setenv("OPENRAG_URL_CONNECTOR_ENABLED", "false")

    response = TestClient(app).get("/connectors/url/sources")

    assert response.status_code == 404
    assert response.json() == {"detail": "Website connector is not enabled"}


@pytest.mark.asyncio
async def test_website_page_search_rejects_disabled_connector(monkeypatch):
    monkeypatch.setenv("OPENRAG_URL_CONNECTOR_ENABLED", "false")

    with pytest.raises(HTTPException, match="Website connector is not enabled") as exc_info:
        await search(
            SearchBody(
                query="*",
                filters={"web_source_ids": ["source-1"]},
                resultMode="website_pages",
            ),
            search_service=None,
            session=None,
            user=None,
        )

    assert exc_info.value.status_code == 404
