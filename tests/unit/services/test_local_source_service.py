from unittest.mock import AsyncMock

import pytest

from services.local_source_service import (
    LocalSourceNotFoundError,
    LocalSourcePreviewUnsupportedError,
    collect_ingest_files,
    delete_local_source,
    find_local_source,
    get_local_source_archive_stats,
    is_source_archiving_enabled,
    local_source_url,
    resolve_ingestion_path,
    resolve_local_source_download,
    source_id_from_local_source_url,
    stage_local_source,
)

DOCUMENT_ID = "abcdefghijklmnopqrstuvwx"
SOURCE_ID = f"{DOCUMENT_ID}.{'a' * 32}"


@pytest.fixture
def documents_path(tmp_path, monkeypatch):
    """Configure an isolated documents directory for archive tests."""
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    monkeypatch.delenv("OPENRAG_DOCUMENTS_HOST_PATH", raising=False)
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_HOST_PATH", raising=False)
    monkeypatch.delenv("OPENRAG_PUBLIC_URL", raising=False)
    return tmp_path


@pytest.mark.asyncio
async def test_committed_source_is_moved_and_resolvable(documents_path):
    """Keep a committed source in the archive and resolve its download URL."""
    source = documents_path / "inbox" / "message.eml"
    source.parent.mkdir()
    source.write_bytes(b"From: sender@example.com\n\nHello")

    staged = await stage_local_source(source, DOCUMENT_ID, "Original message.eml")
    staged.commit()

    assert not source.exists()
    assert staged.archived_path.read_bytes().endswith(b"Hello")
    assert staged.source_id.startswith(f"{DOCUMENT_ID}.")
    assert find_local_source(staged.source_id) == staged.archived_path.resolve()
    assert local_source_url(staged.source_id) == f"/api/source-files/{staged.source_id}"


@pytest.mark.asyncio
async def test_resolve_download_authorizes_and_returns_archived_source(documents_path):
    """Resolve a retained source only after a visible chunk authorizes it."""
    source = documents_path / "inbox" / "report.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-preview")
    staged = await stage_local_source(source, DOCUMENT_ID, source.name)
    staged.commit()
    client = AsyncMock()
    client.search.return_value = {"hits": {"total": {"value": 1}}}

    resolved = await resolve_local_source_download(
        staged.source_id,
        opensearch_client=client,
        index="test-index",
        preview=True,
    )

    assert resolved.path == staged.archived_path.resolve()
    assert resolved.media_type == "application/pdf"
    assert client.search.await_args.kwargs["index"] == "test-index"
    query = client.search.await_args.kwargs["body"]["query"]
    assert query["bool"]["filter"][1]["wildcard"]["source_url"]["value"] == (
        f"*/api/source-files/{staged.source_id}"
    )


@pytest.mark.asyncio
async def test_resolve_download_hides_invalid_invisible_or_missing_sources(documents_path):
    """Treat invalid, invisible, and locally absent retained sources as missing."""
    client = AsyncMock()

    with pytest.raises(LocalSourceNotFoundError):
        await resolve_local_source_download(
            "invalid",
            opensearch_client=client,
            index="test-index",
        )
    client.search.assert_not_awaited()

    client.search.return_value = {"hits": {"total": {"value": 0}}}
    with pytest.raises(LocalSourceNotFoundError):
        await resolve_local_source_download(
            SOURCE_ID,
            opensearch_client=client,
            index="test-index",
        )

    client.search.return_value = {"hits": {"total": {"value": 1}}}
    with pytest.raises(LocalSourceNotFoundError):
        await resolve_local_source_download(
            SOURCE_ID,
            opensearch_client=client,
            index="test-index",
        )


@pytest.mark.asyncio
async def test_resolve_preview_rejects_unsupported_media_type(documents_path):
    """Reject active content before returning a source for inline preview."""
    source = documents_path / "inbox" / "page.html"
    source.parent.mkdir()
    source.write_text("<script>alert('unsafe')</script>")
    staged = await stage_local_source(source, DOCUMENT_ID, source.name)
    staged.commit()
    client = AsyncMock()
    client.search.return_value = {"hits": {"total": {"value": 1}}}

    with pytest.raises(LocalSourcePreviewUnsupportedError):
        await resolve_local_source_download(
            staged.source_id,
            opensearch_client=client,
            index="test-index",
            preview=True,
        )


@pytest.mark.asyncio
async def test_failed_source_is_returned_to_inbox(documents_path):
    """Restore a staged source to its original path when indexing fails."""
    source = documents_path / "inbox" / "report.pdf"
    source.parent.mkdir()
    source.write_bytes(b"pdf")

    staged = await stage_local_source(source, DOCUMENT_ID, source.name)
    await staged.rollback()

    assert source.read_bytes() == b"pdf"
    assert find_local_source(staged.source_id) is None


def test_collection_excludes_archive_and_symlinks(documents_path):
    """Exclude archived, partial, and symlinked files from path ingestion."""
    inbox = documents_path / "inbox"
    inbox.mkdir()
    source = inbox / "document.txt"
    source.write_text("hello")

    archived = documents_path / ".openrag-indexed" / DOCUMENT_ID / "old.txt"
    archived.parent.mkdir(parents=True)
    archived.write_text("old")
    (inbox / "linked.txt").symlink_to(source)
    (inbox / ".upload.part").write_text("incomplete")

    assert collect_ingest_files(documents_path) == [str(source.resolve())]
    assert collect_ingest_files(source) == [str(source.resolve())]
    assert collect_ingest_files(inbox / ".upload.part") == []
    assert collect_ingest_files(archived) == []


def test_public_url_can_make_download_link_absolute(documents_path, monkeypatch):
    """Prefix local source links with the configured public URL."""
    monkeypatch.setenv("OPENRAG_PUBLIC_URL", "https://rag.example.com/")

    assert local_source_url(SOURCE_ID) == (f"https://rag.example.com/api/source-files/{SOURCE_ID}")


@pytest.mark.parametrize(
    "source_url",
    [
        f"/api/source-files/{SOURCE_ID}",
        f"https://rag.example.com/api/source-files/{SOURCE_ID}",
        f"https://rag.example.com/openrag/api/source-files/{SOURCE_ID}",
    ],
)
def test_source_id_is_extracted_only_from_local_source_urls(source_url):
    """Extract source IDs from valid backend-managed source URLs."""
    assert source_id_from_local_source_url(source_url) == SOURCE_ID


@pytest.mark.parametrize(
    "source_url",
    [
        None,
        "https://openarchiver.example.com/api/documents/123",
        f"s3://bucket/api/source-files/{SOURCE_ID}",
        f"/api/source-files/{SOURCE_ID}/extra",
        "/api/source-files/not-a-source-id",
    ],
)
def test_remote_or_invalid_source_url_is_not_treated_as_local(source_url):
    """Reject remote and malformed URLs as local source references."""
    assert source_id_from_local_source_url(source_url) is None


@pytest.mark.asyncio
async def test_delete_local_source_removes_only_validated_archive(documents_path):
    """Delete validated archive directories without permitting traversal."""
    archived = documents_path / ".openrag-indexed" / SOURCE_ID / "report.pdf"
    archived.parent.mkdir(parents=True)
    archived.write_bytes(b"pdf")

    assert await delete_local_source(SOURCE_ID) is True
    assert not archived.parent.exists()
    assert await delete_local_source("../outside") is False


def test_archive_stats_expose_ingestion_and_archive_paths(documents_path):
    """Report archive paths and filesystem capacity."""
    stats = get_local_source_archive_stats()

    assert stats["ingestion_path"] == str(documents_path.resolve())
    assert stats["path"] == str((documents_path / ".openrag-indexed").resolve())
    assert stats["used_bytes"] == 0
    assert stats["filesystem_total_bytes"] > 0
    assert stats["filesystem_free_bytes"] > 0


def test_archive_stats_can_skip_recursive_size_scan(documents_path, monkeypatch):
    """Skip the archive tree walk when used-byte statistics are not requested."""
    archived = documents_path / ".openrag-indexed" / SOURCE_ID / "old.txt"
    archived.parent.mkdir(parents=True)
    archived.write_text("old")

    def unexpected_walk(*_args, **_kwargs):
        """Fail if the archive tree is scanned."""
        raise AssertionError("archive tree should not be scanned")

    monkeypatch.setattr("services.local_source_service.os.walk", unexpected_walk)

    stats = get_local_source_archive_stats(include_used_bytes=False)

    assert stats["used_bytes"] is None


def test_archive_stats_map_runtime_paths_to_host_paths(documents_path, monkeypatch):
    """Map runtime archive paths to their configured host-visible paths."""
    monkeypatch.setenv("OPENRAG_DOCUMENTS_HOST_PATH", "/srv/openrag/inbox")

    stats = get_local_source_archive_stats()

    assert stats["ingestion_host_path"] == "/srv/openrag/inbox"
    assert stats["host_path"] == "/srv/openrag/inbox/.openrag-indexed"


def test_api_ingestion_path_is_confined_to_documents_root(documents_path):
    """Resolve API ingestion paths only inside the documents root."""
    source = documents_path / "inbox" / "message.eml"
    source.parent.mkdir()
    source.write_text("message")

    assert resolve_ingestion_path("inbox/message.eml") == source.resolve()
    assert resolve_ingestion_path(str(source)) == source.resolve()
    assert resolve_ingestion_path(str(documents_path.parent)) is None


@pytest.mark.asyncio
async def test_multi_user_mode_disables_and_rejects_local_archiving(documents_path, monkeypatch):
    """Disable and reject local source archiving in multi-user mode."""
    source = documents_path / "message.eml"
    source.write_text("message")
    monkeypatch.setattr("config.settings.is_no_auth_mode", lambda: False)
    monkeypatch.setattr(
        "config.settings.get_openrag_config",
        lambda: type("Config", (), {"archiving": type("Archiving", (), {"enabled": True})()})(),
    )

    assert is_source_archiving_enabled() is False
    with pytest.raises(ValueError, match="disabled in multi-user mode"):
        await stage_local_source(source, DOCUMENT_ID, source.name)
    assert source.exists()
