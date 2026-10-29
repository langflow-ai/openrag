import time
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import db.engine as db_engine
import db.models  # noqa: F401  (registers tables)
from config.settings import LANGFLOW_INGEST_CALLBACK_TTL_SECONDS
from db.migrations_runtime import _already_done
from services import indexed_time_backfill as backfill

EARLIEST = "2026-10-15T14:00:10.123456+00:00"
NOW_MS = time.time() * 1000
OLD_MS = NOW_MS - (LANGFLOW_INGEST_CALLBACK_TTL_SECONDS + 3600) * 1000
RECENT_MS = NOW_MS - 1000


def _bucket(run, min_t, max_t, earliest=EARLIEST):
    return {
        "key": {"run": run},
        "min_t": {"value": min_t},
        "max_t": {"value": max_t},
        "earliest": {"hits": {"hits": [{"_source": {"indexed_time": earliest}}]}},
    }


def _page(buckets, after_key=None, **extra):
    agg = {"buckets": buckets}
    if after_key:
        agg["after_key"] = after_key
    return {"aggregations": {"runs": agg}, "_shards": {"failed": 0}, **extra}


def _split_run(run="run-1", max_t=None):
    return _bucket(run, OLD_MS - 5000, OLD_MS if max_t is None else max_t)


def _client(*pages, update=None):
    client = MagicMock()
    client.indices.exists = AsyncMock(return_value=True)
    client.indices.refresh = AsyncMock()
    client.search = AsyncMock(side_effect=list(pages))
    client.update_by_query = AsyncMock(return_value=update or {"updated": 3})
    return client


@pytest_asyncio.fixture
async def session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_engine, "SessionLocal", factory)
    yield factory
    await engine.dispose()


@pytest.fixture
def use_client(monkeypatch):
    def _use(client):
        monkeypatch.setattr(backfill.clients, "opensearch", client, raising=False)
        monkeypatch.setattr(backfill, "get_index_name", lambda: "documents")
        return client

    return _use


async def _is_done(factory):
    async with factory() as session:
        return await _already_done(session, backfill.MIGRATION_NAME)


@pytest.mark.asyncio
async def test_split_old_run_is_updated_with_exact_earliest_string(session_factory, use_client):
    client = use_client(_client(_page([_split_run()])))

    await backfill.run_indexed_time_backfill()

    client.update_by_query.assert_awaited_once()
    kwargs = client.update_by_query.await_args.kwargs
    assert kwargs["body"]["script"]["params"]["times"] == {"run-1": EARLIEST}
    assert kwargs["body"]["query"] == {"terms": {"ingest_run_id": ["run-1"]}}
    assert kwargs["conflicts"] == "proceed"
    assert kwargs["wait_for_completion"] is True
    assert kwargs["request_timeout"] == 300
    assert await _is_done(session_factory)


@pytest.mark.asyncio
async def test_uniform_run_is_not_selected(session_factory, use_client):
    client = use_client(_client(_page([_bucket("run-1", OLD_MS, OLD_MS)])))

    await backfill.run_indexed_time_backfill()

    client.update_by_query.assert_not_awaited()
    client.indices.refresh.assert_not_awaited()
    assert await _is_done(session_factory)


@pytest.mark.asyncio
async def test_split_run_within_ttl_window_is_deferred(session_factory, use_client):
    ttl_ms = LANGFLOW_INGEST_CALLBACK_TTL_SECONDS * 1000
    run = _bucket("run-1", NOW_MS - ttl_ms // 2, RECENT_MS)
    client = use_client(_client(_page([run])))

    await backfill.run_indexed_time_backfill()

    client.update_by_query.assert_not_awaited()
    assert not await _is_done(session_factory)


@pytest.mark.asyncio
async def test_run_past_ttl_since_start_but_recent_max_is_still_deferred(
    session_factory, use_client
):
    # min_t + TTL has passed (the token is expired), but the run was written to
    # recently, so the conservative inactivity guard still defers it.
    ttl_ms = LANGFLOW_INGEST_CALLBACK_TTL_SECONDS * 1000
    run = _bucket("run-1", NOW_MS - 2 * ttl_ms, RECENT_MS)
    assert run["min_t"]["value"] + ttl_ms < NOW_MS
    client = use_client(_client(_page([run])))

    await backfill.run_indexed_time_backfill()

    client.update_by_query.assert_not_awaited()
    assert not await _is_done(session_factory)


@pytest.mark.asyncio
async def test_old_split_run_outside_ttl_window_is_selected(session_factory, use_client):
    ttl_ms = LANGFLOW_INGEST_CALLBACK_TTL_SECONDS * 1000
    run = _bucket("run-1", NOW_MS - 3 * ttl_ms, NOW_MS - 2 * ttl_ms)
    client = use_client(_client(_page([run])))

    await backfill.run_indexed_time_backfill()

    client.update_by_query.assert_awaited_once()
    assert await _is_done(session_factory)


@pytest.mark.asyncio
async def test_any_deferred_run_blocks_completion_and_retries_next_boot(
    session_factory, use_client
):
    deferred = _split_run("run-recent", max_t=RECENT_MS)
    client = use_client(_client(_page([_split_run("run-old"), deferred])))

    await backfill.run_indexed_time_backfill()

    # The eligible run is still repaired, but the deferred one keeps the
    # migration open.
    assert client.update_by_query.await_args.kwargs["body"]["script"]["params"]["times"] == {
        "run-old": EARLIEST
    }
    assert not await _is_done(session_factory)

    # Next boot: the deferred run has aged out, so it is repaired and the
    # migration completes.
    aged = _split_run("run-recent")
    client.search.side_effect = [_page([aged])]
    client.update_by_query.reset_mock()

    await backfill.run_indexed_time_backfill()

    client.update_by_query.assert_awaited_once()
    assert await _is_done(session_factory)


@pytest.mark.asyncio
async def test_follows_after_key_until_absent(session_factory, use_client):
    client = use_client(
        _client(
            _page([_split_run("run-1")], after_key={"run": "run-1"}),
            _page([_split_run("run-2")]),
        )
    )

    await backfill.run_indexed_time_backfill()

    assert client.search.await_count == 2
    assert client.search.await_args_list[1].kwargs["body"]["aggs"]["runs"]["composite"][
        "after"
    ] == {"run": "run-1"}
    assert client.update_by_query.await_count == 2
    assert await _is_done(session_factory)


@pytest.mark.asyncio
async def test_update_failures_are_not_marked_done(session_factory, use_client):
    use_client(_client(_page([_split_run()]), update={"updated": 1, "failures": [{"x": 1}]}))

    await backfill.run_indexed_time_backfill()

    assert not await _is_done(session_factory)


@pytest.mark.asyncio
async def test_version_conflicts_are_not_marked_done(session_factory, use_client):
    use_client(_client(_page([_split_run()]), update={"updated": 1, "version_conflicts": 2}))

    await backfill.run_indexed_time_backfill()

    assert not await _is_done(session_factory)


@pytest.mark.asyncio
async def test_update_timeout_is_not_marked_done(session_factory, use_client):
    use_client(_client(_page([_split_run()]), update={"updated": 1, "timed_out": True}))

    await backfill.run_indexed_time_backfill()

    assert not await _is_done(session_factory)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "partial", [{"timed_out": True}, {"_shards": {"failed": 1}}], ids=["timed_out", "shards"]
)
async def test_partial_scan_is_not_marked_done(session_factory, use_client, partial):
    client = use_client(_client({**_page([_split_run()]), **partial}))

    await backfill.run_indexed_time_backfill()

    client.update_by_query.assert_not_awaited()
    assert not await _is_done(session_factory)


@pytest.mark.asyncio
async def test_missing_index_is_a_clean_pass(session_factory, use_client):
    client = use_client(_client())
    client.indices.exists.return_value = False

    await backfill.run_indexed_time_backfill()

    client.search.assert_not_awaited()
    assert await _is_done(session_factory)


@pytest.mark.asyncio
async def test_search_error_does_not_escape_or_mark_done(session_factory, use_client):
    client = use_client(_client())
    client.search.side_effect = RuntimeError("boom")

    await backfill.run_indexed_time_backfill()

    assert not await _is_done(session_factory)


@pytest.mark.asyncio
async def test_cancellation_is_re_raised(session_factory, use_client):
    import asyncio

    client = use_client(_client())
    client.search.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await backfill.run_indexed_time_backfill()
    assert not await _is_done(session_factory)


@pytest.mark.asyncio
async def test_already_done_skips_opensearch(session_factory, use_client):
    client = use_client(_client(_page([_split_run()])))
    await backfill.run_indexed_time_backfill()
    client.search.reset_mock()
    client.update_by_query.reset_mock()

    await backfill.run_indexed_time_backfill()

    client.indices.exists.assert_awaited_once()
    client.search.assert_not_awaited()
    client.update_by_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_only_when_documents_were_updated(session_factory, use_client):
    client = use_client(_client(_page([_split_run()]), update={"updated": 0}))
    await backfill.run_indexed_time_backfill()
    client.indices.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_runs_once_after_updates(session_factory, use_client):
    client = use_client(
        _client(
            _page([_split_run("run-1")], after_key={"run": "run-1"}),
            _page([_split_run("run-2")]),
        )
    )
    await backfill.run_indexed_time_backfill()
    client.indices.refresh.assert_awaited_once_with(index="documents")


@pytest.mark.asyncio
async def test_returns_early_without_session_factory_or_client(monkeypatch, use_client):
    client = use_client(_client(_page([_split_run()])))
    monkeypatch.setattr(db_engine, "SessionLocal", None)

    await backfill.run_indexed_time_backfill()

    client.indices.exists.assert_not_awaited()
