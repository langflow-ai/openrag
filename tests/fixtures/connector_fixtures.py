"""
Connector fixtures for testing various data source connectors.
"""

import pytest
from pathlib import Path
import sys
from typing import AsyncGenerator

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def google_drive_connector():
    """Provide a GoogleDriveConnector instance for testing."""
    from connectors.google_drive.connector import GoogleDriveConnector

    config = {
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "token_file": "test_token.json",
    }
    return GoogleDriveConnector(config)


@pytest.fixture
def onedrive_connector():
    """Provide a OneDriveConnector instance for testing."""
    from connectors.onedrive.connector import OneDriveConnector

    config = {
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "token_file": "test_token.json",
    }
    return OneDriveConnector(config)


@pytest.fixture
def sharepoint_connector():
    """Provide a SharePointConnector instance for testing."""
    from connectors.sharepoint.connector import SharePointConnector

    config = {
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "token_file": "test_token.json",
    }
    return SharePointConnector(config)


@pytest.fixture
def connector_service():
    """Provide a ConnectorService instance for testing."""
    from connectors.service import ConnectorService

    return ConnectorService()


@pytest.fixture
def connection_manager():
    """Provide a ConnectionManager instance for testing."""
    from connectors.connection_manager import ConnectionManager

    return ConnectionManager()


@pytest.fixture
def langflow_connector_service():
    """Provide a LangflowConnectorService instance for testing."""
    from connectors.langflow_connector_service import LangflowConnectorService

    return LangflowConnectorService()


@pytest.fixture
def sample_google_drive_file() -> dict:
    """Provide sample Google Drive file metadata."""
    return {
        "id": "test_file_id_123",
        "name": "test_document.pdf",
        "mimeType": "application/pdf",
        "modifiedTime": "2025-01-01T00:00:00.000Z",
        "size": "1024000",
        "webViewLink": "https://drive.google.com/file/d/test_file_id_123/view",
    }


@pytest.fixture
def sample_onedrive_item() -> dict:
    """Provide sample OneDrive item metadata."""
    return {
        "id": "test_item_id_123",
        "name": "test_document.docx",
        "size": 2048000,
        "lastModifiedDateTime": "2025-01-01T00:00:00Z",
        "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        "webUrl": "https://onedrive.live.com/test_item_id_123",
    }


@pytest.fixture
def sample_sharepoint_item() -> dict:
    """Provide sample SharePoint item metadata."""
    return {
        "id": "test_sp_item_123",
        "name": "test_presentation.pptx",
        "size": 3072000,
        "lastModifiedDateTime": "2025-01-01T00:00:00Z",
        "file": {"mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation"},
        "webUrl": "https://sharepoint.com/sites/test/test_presentation.pptx",
    }


@pytest.fixture
def mock_google_drive_credentials() -> dict:
    """Provide mock Google Drive OAuth credentials."""
    return {
        "client_id": "test_google_client_id.apps.googleusercontent.com",
        "client_secret": "test_google_client_secret",
        "refresh_token": "test_google_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
    }


@pytest.fixture
def mock_microsoft_credentials() -> dict:
    """Provide mock Microsoft OAuth credentials for OneDrive/SharePoint."""
    return {
        "client_id": "test_microsoft_client_id",
        "client_secret": "test_microsoft_client_secret",
        "tenant_id": "test_tenant_id",
        "refresh_token": "test_microsoft_refresh_token",
    }
