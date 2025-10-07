"""
Tests for base connector functionality.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.mark.unit
@pytest.mark.connector
class TestBaseConnector:
    """Test suite for base connector functionality."""

    def test_connector_config_structure(self, sample_connector_config: dict):
        """Test connector configuration structure."""
        assert "connector_type" in sample_connector_config
        assert "credentials" in sample_connector_config
        assert "settings" in sample_connector_config

    def test_connector_credentials(self, sample_connector_config: dict):
        """Test connector credentials structure."""
        credentials = sample_connector_config["credentials"]

        assert isinstance(credentials, dict)
        assert len(credentials) > 0

    def test_connector_type_validation(self, sample_connector_config: dict):
        """Test that connector type is valid."""
        valid_types = ["google_drive", "onedrive", "sharepoint"]
        connector_type = sample_connector_config["connector_type"]

        assert connector_type in valid_types

    def test_connector_settings(self, sample_connector_config: dict):
        """Test connector settings structure."""
        settings = sample_connector_config["settings"]

        assert isinstance(settings, dict)


@pytest.mark.integration
@pytest.mark.connector
class TestConnectorIntegration:
    """Integration tests for connector functionality."""

    def test_google_drive_connector_initialization(
        self, google_drive_connector
    ):
        """Test Google Drive connector initialization."""
        assert google_drive_connector is not None
        assert hasattr(google_drive_connector, "CONNECTOR_NAME")

    def test_onedrive_connector_initialization(self, onedrive_connector):
        """Test OneDrive connector initialization."""
        assert onedrive_connector is not None
        assert hasattr(onedrive_connector, "CONNECTOR_NAME")

    def test_sharepoint_connector_initialization(
        self, sharepoint_connector
    ):
        """Test SharePoint connector initialization."""
        assert sharepoint_connector is not None
        assert hasattr(sharepoint_connector, "CONNECTOR_NAME")

    def test_connection_manager_initialization(self, connection_manager):
        """Test ConnectionManager initialization."""
        assert connection_manager is not None
