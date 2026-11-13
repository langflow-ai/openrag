"""Native chat storage validation is performed by request endpoints."""

import app.container as container


def test_service_container_no_longer_blocks_file_storage_startup():
    """Langflow deployments can start without the native DB-backed endpoint."""
    assert not hasattr(container, "_validate_native_chat_storage_mode")
