"""Health endpoint tests."""

import json
from unittest.mock import Mock

import pytest

from api import health


@pytest.mark.asyncio
async def test_health_check_reports_langflow_capability(monkeypatch):
    monkeypatch.setattr(health, "is_langflow_disabled", Mock(return_value=True))

    response = await health.health_check(Mock())

    assert response.status_code == 200
    assert json.loads(response.body) == {"status": "ok", "langflow_enabled": False}
