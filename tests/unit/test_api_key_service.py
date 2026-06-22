from typing import Any, Dict

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.services.api_key_service import APIKeyService


@pytest.fixture
def api_key_service() -> tuple[APIKeyService, AsyncMock]:
    """Create an APIKeyService instance with mocked OpenSearch client."""
    service = APIKeyService()
    mock_client = AsyncMock()
    service._get_opensearch_client = MagicMock(return_value=mock_client)
    return service, mock_client


@pytest.mark.asyncio
async def test_api_key_lifecycle(api_key_service: tuple[APIKeyService, AsyncMock]) -> None:
    service, mock_client = api_key_service
    
    user_id = "test-user-123"
    
    mock_client.index = AsyncMock(return_value={"result": "created"})
    create_result = await service.create_key(user_id=user_id, user_email="test@example.com", name="Test Key")
    
    assert create_result["success"] is True
    assert create_result["api_key"].startswith("orag_")
    
    mock_client.search = AsyncMock(return_value={
        "hits": {"hits": [{"_source": {"key_id": create_result["key_id"], "revoked": False}}]}
    })
    list_result: Dict[str, Any] = await service.list_keys(user_id=user_id)
    
    assert list_result["success"] is True
    assert len(list_result["keys"]) == 1
    
    query_must = mock_client.search.call_args[1]["body"]["query"]["bool"]["must"]
    assert {"term": {"revoked": False}} in query_must
    
    mock_client.get = AsyncMock(return_value={"_source": {"user_id": user_id}})
    mock_client.update = AsyncMock(return_value={"result": "updated"})
    revoke_result: Dict[str, Any] = await service.revoke_key(user_id=user_id, key_id=create_result["key_id"])
    
    assert revoke_result["success"] is True
    
    mock_client.search = AsyncMock(return_value={"hits": {"hits": []}})
    list_result_after: Dict[str, Any] = await service.list_keys(user_id=user_id)
    
    assert list_result_after["success"] is True
    assert len(list_result_after["keys"]) == 0
