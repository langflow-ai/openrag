"""sync_connector_files must enumerate the whole source, not just the first page.

Two bugs made it stop early on every connector:

  - it asked for a synthetic page size (100) whenever the caller set no
    max_files, and
  - it looked for the continuation token under ``nextPageToken``, a key no
    connector in this repo emits — they all return ``next_page_token``.

Together those silently capped a sync at 100 files: the connectors that
paginate internally (all three bucket ones, and Google Drive) honoured the cap
and then reported no token, so there was nothing to continue with. SharePoint,
which returns a real Graph ``$skiptoken``, had its token dropped on the floor.

The user-visible symptom is the same as an overwrite not propagating: a file
past the first page is never re-ingested, so its stale copy stays in Knowledge.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _file(i: int) -> dict:
    return {"id": f"b1::k{i}.pdf", "name": f"k{i}.pdf", "mimeType": "application/pdf"}


def _internally_paginating_connector(total: int):
    """A bucket-style connector: caps to max_files itself, never returns a token.

    Mirrors S3/COS/Azure (and Google Drive), where the SDK walks the pages and
    the connector hands back one flat list.
    """
    connector = MagicMock()
    connector.CONNECTOR_TYPE = "aws_s3"
    connector.is_authenticated = True
    connector.cfg = None
    seen: list[int | None] = []

    async def list_files(page_token=None, max_files=None, **kwargs):
        seen.append(max_files)
        files = [_file(i) for i in range(total)]
        if isinstance(max_files, int) and max_files > 0:
            files = files[:max_files]
        return {"files": files, "next_page_token": None}

    connector.list_files = AsyncMock(side_effect=list_files)
    return connector, seen


def _token_paginating_connector(pages: list[list[dict]]):
    """A SharePoint-style connector returning a real next_page_token per page."""
    connector = MagicMock()
    connector.CONNECTOR_TYPE = "sharepoint"
    connector.is_authenticated = True
    connector.cfg = None
    requested_tokens: list[str | None] = []

    async def list_files(page_token=None, max_files=None, **kwargs):
        requested_tokens.append(page_token)
        index = 0 if page_token is None else int(page_token)
        is_last = index == len(pages) - 1
        return {
            "files": pages[index],
            "next_page_token": None if is_last else str(index + 1),
        }

    connector.list_files = AsyncMock(side_effect=list_files)
    return connector, requested_tokens


def _service(connector):
    from connectors.service import ConnectorService

    service = ConnectorService.__new__(ConnectorService)
    service.session_manager = MagicMock()
    service.session_manager.get_user = MagicMock(
        return_value=MagicMock(name="u", email="u@example.com")
    )
    service.models_service = MagicMock()
    service.langflow_service = None
    service.task_service = MagicMock()
    service.task_service.document_service = MagicMock()
    service.task_service.create_custom_task = AsyncMock(return_value="task-1")
    service.get_connector = AsyncMock(return_value=connector)
    service._get_effective_sync_jwt = AsyncMock(return_value="jwt")
    return service


def _processed_ids(service) -> list[str]:
    """The file ids handed to the task processor."""
    return service.task_service.create_custom_task.await_args.args[1]


@pytest.mark.asyncio
async def test_uncapped_sync_takes_every_file_not_just_the_first_hundred():
    connector, requested_max_files = _internally_paginating_connector(total=150)
    service = _service(connector)

    await service.sync_connector_files("conn-1", "alice")

    assert len(_processed_ids(service)) == 150
    # No cap was requested, so the connector was free to return everything.
    assert requested_max_files == [None]


@pytest.mark.asyncio
async def test_explicit_max_files_still_caps():
    connector, requested_max_files = _internally_paginating_connector(total=150)
    service = _service(connector)

    await service.sync_connector_files("conn-1", "alice", max_files=20)

    assert len(_processed_ids(service)) == 20
    assert requested_max_files == [20]


@pytest.mark.asyncio
async def test_token_paginated_connector_is_followed_across_pages():
    """SharePoint's $skiptoken was read under the wrong key and dropped."""
    pages = [[_file(0), _file(1)], [_file(2), _file(3)], [_file(4)]]
    connector, requested_tokens = _token_paginating_connector(pages)
    service = _service(connector)

    await service.sync_connector_files("conn-1", "alice")

    assert len(_processed_ids(service)) == 5
    assert requested_tokens == [None, "1", "2"]


@pytest.mark.asyncio
async def test_token_paginated_connector_continues_after_empty_page():
    pages = [[], [_file(0), _file(1)]]
    connector, requested_tokens = _token_paginating_connector(pages)
    service = _service(connector)

    await service.sync_connector_files("conn-1", "alice")

    assert _processed_ids(service) == ["b1::k0.pdf", "b1::k1.pdf"]
    assert requested_tokens == [None, "1"]


@pytest.mark.asyncio
async def test_token_paginated_connector_stops_at_aggregate_max_files():
    pages = [[_file(i) for i in range(start, start + 15)] for start in (0, 15, 30)]
    connector, requested_tokens = _token_paginating_connector(pages)
    service = _service(connector)

    await service.sync_connector_files("conn-1", "alice", max_files=20)

    assert _processed_ids(service) == [f"b1::k{i}.pdf" for i in range(20)]
    assert requested_tokens == [None, "1"]


@pytest.mark.asyncio
async def test_camel_case_token_still_paginates():
    """Tolerated alias: a connector written against the old key still works."""
    connector = MagicMock()
    connector.CONNECTOR_TYPE = "sharepoint"
    connector.is_authenticated = True
    connector.cfg = None
    calls: list[str | None] = []

    async def list_files(page_token=None, max_files=None, **kwargs):
        calls.append(page_token)
        if page_token is None:
            return {"files": [_file(0)], "nextPageToken": "p2"}
        return {"files": [_file(1)], "nextPageToken": None}

    connector.list_files = AsyncMock(side_effect=list_files)
    service = _service(connector)

    await service.sync_connector_files("conn-1", "alice")

    assert len(_processed_ids(service)) == 2
    assert calls == [None, "p2"]


@pytest.mark.asyncio
async def test_filename_filter_matches_beyond_the_first_page():
    """The filter is why truncation is a correctness bug, not just a slow sync.

    _sync_existing_connector_files' fallback branch passes the indexed filenames
    here. A file past the cap was never listed, so it never matched the filter
    and never got re-ingested — its stale copy stayed in Knowledge.
    """
    connector, _ = _internally_paginating_connector(total=150)
    service = _service(connector)

    await service.sync_connector_files("conn-1", "alice", filename_filter={"k0.pdf", "k130.pdf"})

    assert sorted(_processed_ids(service)) == ["b1::k0.pdf", "b1::k130.pdf"]
