import pytest

from services.local_source_service import (
    collect_ingest_files,
    find_local_source,
    get_local_source_archive_stats,
    is_source_archiving_enabled,
    local_source_url,
    resolve_ingestion_path,
    stage_local_source,
)

DOCUMENT_ID = "abcdefghijklmnopqrstuvwx"
SOURCE_ID = f"{DOCUMENT_ID}.{'a' * 32}"


@pytest.fixture
def documents_path(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENRAG_DOCUMENTS_PATH", str(tmp_path))
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_PATH", raising=False)
    monkeypatch.delenv("OPENRAG_DOCUMENTS_HOST_PATH", raising=False)
    monkeypatch.delenv("OPENRAG_INDEXED_DOCUMENTS_HOST_PATH", raising=False)
    monkeypatch.delenv("OPENRAG_PUBLIC_URL", raising=False)
    return tmp_path


@pytest.mark.asyncio
async def test_committed_source_is_moved_and_resolvable(documents_path):
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
async def test_failed_source_is_returned_to_inbox(documents_path):
    source = documents_path / "inbox" / "report.pdf"
    source.parent.mkdir()
    source.write_bytes(b"pdf")

    staged = await stage_local_source(source, DOCUMENT_ID, source.name)
    await staged.rollback()

    assert source.read_bytes() == b"pdf"
    assert find_local_source(staged.source_id) is None


def test_collection_excludes_archive_and_symlinks(documents_path):
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
    monkeypatch.setenv("OPENRAG_PUBLIC_URL", "https://rag.example.com/")

    assert local_source_url(SOURCE_ID) == (f"https://rag.example.com/api/source-files/{SOURCE_ID}")


def test_archive_stats_expose_ingestion_and_archive_paths(documents_path):
    stats = get_local_source_archive_stats()

    assert stats["ingestion_path"] == str(documents_path.resolve())
    assert stats["path"] == str((documents_path / ".openrag-indexed").resolve())
    assert stats["used_bytes"] == 0
    assert stats["filesystem_total_bytes"] > 0
    assert stats["filesystem_free_bytes"] > 0


def test_archive_stats_can_skip_recursive_size_scan(documents_path, monkeypatch):
    archived = documents_path / ".openrag-indexed" / SOURCE_ID / "old.txt"
    archived.parent.mkdir(parents=True)
    archived.write_text("old")

    def unexpected_walk(*_args, **_kwargs):
        raise AssertionError("archive tree should not be scanned")

    monkeypatch.setattr("services.local_source_service.os.walk", unexpected_walk)

    stats = get_local_source_archive_stats(include_used_bytes=False)

    assert stats["used_bytes"] is None


def test_archive_stats_map_runtime_paths_to_host_paths(documents_path, monkeypatch):
    monkeypatch.setenv("OPENRAG_DOCUMENTS_HOST_PATH", "/srv/openrag/inbox")

    stats = get_local_source_archive_stats()

    assert stats["ingestion_host_path"] == "/srv/openrag/inbox"
    assert stats["host_path"] == "/srv/openrag/inbox/.openrag-indexed"


def test_api_ingestion_path_is_confined_to_documents_root(documents_path):
    source = documents_path / "inbox" / "message.eml"
    source.parent.mkdir()
    source.write_text("message")

    assert resolve_ingestion_path("inbox/message.eml") == source.resolve()
    assert resolve_ingestion_path(str(source)) == source.resolve()
    assert resolve_ingestion_path(str(documents_path.parent)) is None


@pytest.mark.asyncio
async def test_multi_user_mode_disables_and_rejects_local_archiving(documents_path, monkeypatch):
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
