import asyncio
from unittest.mock import AsyncMock

import pytest

from models.processors import TaskProcessor


@pytest.mark.asyncio
async def test_check_filename_exists_does_not_requery_successfully_checked_aliases_on_retry():
    """Once an alias is checked successfully, retries should continue from pending aliases."""
    processor = TaskProcessor()
    opensearch_client = AsyncMock()

    async def _search_side_effect(*, index, body):
        candidate = body["query"]["term"]["filename"]
        if candidate == "report.md" and _search_side_effect.md_calls == 0:
            _search_side_effect.md_calls += 1
            raise asyncio.TimeoutError("transient timeout")
        return {"hits": {"hits": []}}

    _search_side_effect.md_calls = 0
    opensearch_client.search.side_effect = _search_side_effect

    exists = await processor.check_filename_exists("report.txt", opensearch_client)

    assert exists is False

    queried_candidates = [
        call.kwargs["body"]["query"]["term"]["filename"]
        for call in opensearch_client.search.await_args_list
    ]
    # Expected sequence:
    # 1) report.txt succeeds (no hits)
    # 2) report.md times out
    # 3) retry continues from pending alias only -> report.md
    assert queried_candidates == ["report.txt", "report.md", "report.md"]
