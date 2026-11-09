"""Unit tests for src/api/flows.py endpoints across all run modes."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.flows import (
    BulkUpdateFlowsRequest,
    DismissFlowsUpdateRequest,
    bulk_update_flows_endpoint,
    dismiss_flows_update_endpoint,
    get_flows_updates_endpoint,
)
from session_manager import User


@pytest.mark.asyncio
async def test_get_flows_updates_endpoint_returns_updates():
    """Verify get_flows_updates_endpoint returns updates regardless of mode."""
    flows_service = MagicMock()
    flows_service.get_flows_updates_available = AsyncMock(
        return_value=[
            {
                "flow_type": "retrieval",
                "flow_id": "flow-retrieval-123",
                "is_custom": False,
                "dismissed": False,
            }
        ]
    )
    user = MagicMock(spec=User)
    user.db_user_id = None
    user.user_id = "user_123"

    response = await get_flows_updates_endpoint(flows_service=flows_service, user=user)

    assert response.status_code == 200
    data = json.loads(response.body)
    assert data["success"] is True
    assert len(data["updates"]) == 1
    assert data["updates"][0]["flow_type"] == "retrieval"


@pytest.mark.asyncio
async def test_bulk_update_flows_endpoint_executes():
    """Verify bulk_update_flows_endpoint executes update."""
    flows_service = MagicMock()
    flows_service.bulk_update_flows = AsyncMock(
        return_value=[{"flow_type": "retrieval", "success": True}]
    )
    user = MagicMock(spec=User)

    request = BulkUpdateFlowsRequest(flow_types=["retrieval"], backup_custom=True)
    response = await bulk_update_flows_endpoint(
        request=request, flows_service=flows_service, user=user
    )

    assert response.status_code == 200
    data = json.loads(response.body)
    assert data["success"] is True
    assert data["results"][0]["flow_type"] == "retrieval"


@pytest.mark.asyncio
async def test_dismiss_flows_update_endpoint_executes():
    """Verify dismiss_flows_update_endpoint executes dismissal."""
    flows_service = MagicMock()
    user = MagicMock(spec=User)
    user.db_user_id = None
    user.user_id = "user_123"

    request = DismissFlowsUpdateRequest(flow_types=["retrieval"])
    response = await dismiss_flows_update_endpoint(
        request=request, flows_service=flows_service, user=user
    )

    assert response.status_code == 200
    data = json.loads(response.body)
    assert data["success"] is True
    flows_service.dismiss_flows_updates.assert_called_once_with(["retrieval"], user_id="user_123")
