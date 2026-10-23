import pytest
from fastapi import HTTPException

from api.search import SearchBody, search


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", ["created_after", "created_before"])
async def test_non_string_bound_in_filters_is_rejected(bound):
    body = SearchBody(query="*", filters={bound: 123})
    with pytest.raises(HTTPException) as exc:
        await search(body, search_service=None, session_manager=None, user=None)
    assert exc.value.status_code == 422
