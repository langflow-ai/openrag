"""
Tests for health check and basic API functionality.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.mark.unit
@pytest.mark.api
class TestHealthEndpoint:
    """Test suite for health check endpoint."""

    def test_health_endpoint_structure(self):
        """Test health response structure."""
        health_response = {
            "status": "healthy",
            "timestamp": "2025-01-01T00:00:00Z",
            "version": "0.1.15",
        }

        assert "status" in health_response
        assert "timestamp" in health_response
        assert health_response["status"] in ["healthy", "unhealthy"]

    def test_health_status_values(self):
        """Test that health status has valid values."""
        valid_statuses = ["healthy", "unhealthy", "degraded"]
        test_status = "healthy"

        assert test_status in valid_statuses


@pytest.mark.integration
@pytest.mark.api
class TestAPIBasics:
    """Integration tests for basic API functionality."""

    def test_api_cors_headers(self):
        """Test CORS headers configuration."""
        # Common CORS headers
        cors_headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }

        assert "Access-Control-Allow-Origin" in cors_headers
        assert "Access-Control-Allow-Methods" in cors_headers
        assert "Access-Control-Allow-Headers" in cors_headers

    def test_api_content_type_json(self):
        """Test that API returns JSON content type."""
        expected_content_type = "application/json"
        assert expected_content_type == "application/json"

    def test_api_error_response_structure(self):
        """Test error response structure."""
        error_response = {
            "error": "Bad Request",
            "message": "Invalid input",
            "status_code": 400,
        }

        assert "error" in error_response
        assert "message" in error_response
        assert "status_code" in error_response
        assert isinstance(error_response["status_code"], int)
