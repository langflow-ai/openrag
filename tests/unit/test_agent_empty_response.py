from types import SimpleNamespace

import pytest

from agent import async_response


@pytest.mark.asyncio
async def test_async_response_rejects_empty_output_text():
    class Responses:
        async def create(self, **_kwargs):
            return SimpleNamespace(id="empty-response", error=None, output_text="")

    client = SimpleNamespace(responses=Responses(), default_headers={}, api_key="test-key")

    with pytest.raises(ValueError, match="empty response"):
        await async_response(client, prompt="hello", model="flow-id")
