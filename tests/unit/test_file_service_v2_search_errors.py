from unittest.mock import AsyncMock, MagicMock

import pytest
from opensearchpy.exceptions import ConnectionError as OSConnectionError
from opensearchpy.exceptions import NotFoundError

from services.file_service_v2 import FileServiceV2


def _service(search_side_effect):
    client = MagicMock()
    client.search = AsyncMock(side_effect=search_side_effect)
    sm = MagicMock()
    sm.get_user_opensearch_client.return_value = client
    svc = FileServiceV2(sm)
    svc._get_file_count = AsyncMock(return_value=(0, False))
    return svc


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_by", ["filename", "chunk_count"])
async def test_opensearch_failure_propagates(sort_by):
    svc = _service(OSConnectionError("N/A", "boom", Exception("down")))
    with pytest.raises(OSConnectionError):
        await svc.list_files(user_id="u", sort_by=sort_by)


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_by", ["filename", "chunk_count"])
async def test_missing_index_returns_empty(sort_by):
    err = NotFoundError(404, "index_not_found_exception", {})
    svc = _service(err)
    result = await svc.list_files(user_id="u", sort_by=sort_by)
    assert result["files"] == []
    assert result["total"] == 0
