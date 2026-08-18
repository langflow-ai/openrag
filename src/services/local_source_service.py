"""Archive and resolve original files ingested from a local documents path."""

from __future__ import annotations

import asyncio
import errno
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from config.paths import get_documents_path

ARCHIVE_DIRNAME = ".openrag-indexed"
DOCUMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
SOURCE_ID_PATTERN = re.compile(r"^(?P<document_id>[A-Za-z0-9_-]{16,128})\.(?P<nonce>[a-f0-9]{32})$")


def get_indexed_documents_path() -> Path:
    """Return the persistent directory used for successfully indexed originals."""
    configured = os.getenv("OPENRAG_INDEXED_DOCUMENTS_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(get_documents_path()).expanduser().resolve() / ARCHIVE_DIRNAME).resolve()


def is_source_archiving_enabled() -> bool:
    """Return the live workspace setting used when a request has no override."""
    from config.settings import get_openrag_config, is_no_auth_mode

    return bool(is_no_auth_mode() and get_openrag_config().archiving.enabled)


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def get_local_source_archive_stats(
    *, include_used_bytes: bool = True
) -> dict[str, int | str | None]:
    """Return archive paths and filesystem usage.

    Computing the retained byte count requires walking the entire archive, so
    callers used by general application settings can opt out. The Archiving UI
    explicitly requests the complete measurement.
    """
    ingestion_root = Path(get_documents_path()).expanduser().resolve()
    archive_root = get_indexed_documents_path()
    ingestion_host_path = os.getenv("OPENRAG_DOCUMENTS_HOST_PATH") or None
    archive_host_path = os.getenv("OPENRAG_INDEXED_DOCUMENTS_HOST_PATH") or None
    if archive_host_path is None and ingestion_host_path:
        try:
            archive_relative_path = archive_root.relative_to(ingestion_root)
            archive_host_path = str(Path(ingestion_host_path) / archive_relative_path)
        except ValueError:
            pass
    measured_used_bytes = 0
    if include_used_bytes and archive_root.is_dir():
        for current_root, _, filenames in os.walk(archive_root):
            current = Path(current_root)
            for filename in filenames:
                candidate = current / filename
                if candidate.is_symlink():
                    continue
                try:
                    measured_used_bytes += candidate.stat().st_size
                except OSError:
                    continue
    used_bytes = measured_used_bytes if include_used_bytes else None

    usage = shutil.disk_usage(_nearest_existing_parent(archive_root))
    return {
        "ingestion_path": str(ingestion_root),
        "ingestion_host_path": ingestion_host_path,
        "path": str(archive_root),
        "host_path": archive_host_path,
        "used_bytes": used_bytes,
        "filesystem_total_bytes": usage.total,
        "filesystem_free_bytes": usage.free,
    }


def document_id_from_source_id(source_id: str) -> str | None:
    match = SOURCE_ID_PATTERN.fullmatch(source_id)
    return match.group("document_id") if match else None


def source_id_from_local_source_url(source_url: str | None) -> str | None:
    """Extract a backend-managed source ID from its relative or public URL."""
    if not source_url:
        return None

    parsed = urlsplit(source_url)
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        return None
    if parsed.query or parsed.fragment:
        return None

    marker = "/api/source-files/"
    _prefix, separator, encoded_source_id = parsed.path.rpartition(marker)
    if not separator or not encoded_source_id or "/" in encoded_source_id:
        return None

    source_id = unquote(encoded_source_id)
    return source_id if SOURCE_ID_PATTERN.fullmatch(source_id) else None


def local_source_url(source_id: str) -> str:
    """Build the browser-facing download URL stored with indexed chunks."""
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise ValueError("Invalid source ID")
    path = f"/api/source-files/{quote(source_id, safe='')}"
    public_url = os.getenv("OPENRAG_PUBLIC_URL", "").strip().rstrip("/")
    if public_url:
        parsed = urlsplit(public_url)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OPENRAG_PUBLIC_URL must be an HTTP(S) URL without credentials")
    return f"{public_url}{path}" if public_url else path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_ingestion_path(requested_path: str | None = None) -> Path | None:
    """Resolve a path inside the configured ingestion root.

    Public API clients may trigger ingestion for files written into the shared
    documents volume, but must never be able to traverse into arbitrary server
    paths. Relative paths are interpreted from ``OPENRAG_DOCUMENTS_PATH``.
    """
    ingestion_root = Path(get_documents_path()).expanduser().resolve()
    candidate = Path(requested_path or ".").expanduser()
    if not candidate.is_absolute():
        candidate = ingestion_root / candidate
    candidate = candidate.resolve()
    if candidate == ingestion_root or _is_relative_to(candidate, ingestion_root):
        return candidate
    return None


def collect_ingest_files(directory: str | os.PathLike[str]) -> list[str]:
    """Collect a regular file or directory, excluding the archive and symlinks."""
    root = Path(directory).expanduser().resolve()
    archive_root = get_indexed_documents_path()
    if root.is_file() and not root.is_symlink():
        if root.name.endswith(".part"):
            return []
        return [] if _is_relative_to(root, archive_root) else [str(root)]
    if not root.is_dir() or _is_relative_to(root, archive_root):
        return []
    files: list[str] = []

    for current_root, directory_names, filenames in os.walk(root):
        current = Path(current_root).resolve()
        directory_names[:] = [
            name
            for name in directory_names
            if not _is_relative_to((current / name).resolve(), archive_root)
        ]
        for filename in filenames:
            candidate = current / filename
            if filename.endswith(".part"):
                continue
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if _is_relative_to(candidate.resolve(), archive_root):
                continue
            files.append(str(candidate))

    return sorted(files)


def _unique_archive_path(directory: Path, filename: str) -> Path:
    safe_name = Path(filename).name or "document"
    destination = directory / safe_name
    if not destination.exists():
        return destination

    suffix = Path(safe_name).suffix
    stem = safe_name[: -len(suffix)] if suffix else safe_name
    while True:
        candidate = directory / f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
        if not candidate.exists():
            return candidate


def _move_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(str(source), str(destination))


@dataclass
class StagedLocalSource:
    """A source moved to its stable archive location before indexing."""

    original_path: Path
    archived_path: Path
    source_id: str
    committed: bool = False

    def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        """Return an uncommitted source to the inbox after failed ingestion."""
        if self.committed or not self.archived_path.exists():
            return

        destination = self.original_path
        if destination.exists():
            suffix = destination.suffix
            stem = destination.name[: -len(suffix)] if suffix else destination.name
            destination = destination.with_name(
                f"{stem}.openrag-recovered-{uuid.uuid4().hex[:8]}{suffix}"
            )

        await asyncio.to_thread(_move_file, self.archived_path, destination)
        try:
            self.archived_path.parent.rmdir()
        except OSError:
            pass


async def stage_local_source(
    file_path: str | os.PathLike[str], document_id: str, filename: str
) -> StagedLocalSource:
    """Move a local source into the persistent archive, ready for indexing."""
    from config.settings import is_no_auth_mode

    if not is_no_auth_mode():
        raise ValueError("Local source archiving is disabled in multi-user mode")
    if not DOCUMENT_ID_PATTERN.fullmatch(document_id):
        raise ValueError("Invalid document ID")

    source = Path(file_path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Local source must be a regular file")

    source_id = f"{document_id}.{uuid.uuid4().hex}"
    archive_directory = get_indexed_documents_path() / source_id
    destination = _unique_archive_path(archive_directory, filename)
    await asyncio.to_thread(_move_file, source, destination)
    return StagedLocalSource(
        original_path=source,
        archived_path=destination,
        source_id=source_id,
    )


def find_local_source(source_id: str) -> Path | None:
    """Resolve an archived source without allowing traversal or symlink escapes."""
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        return None

    archive_root = get_indexed_documents_path()
    document_directory = archive_root / source_id
    if not document_directory.is_dir():
        return None

    for candidate in sorted(document_directory.iterdir()):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if _is_relative_to(resolved, archive_root):
            return resolved
    return None


def _delete_local_source_directory(source_id: str) -> bool:
    if not SOURCE_ID_PATTERN.fullmatch(source_id):
        return False

    archive_root = get_indexed_documents_path().resolve()
    source_directory = archive_root / source_id
    if source_directory.is_symlink() or not source_directory.is_dir():
        return False

    resolved_directory = source_directory.resolve()
    if resolved_directory.parent != archive_root:
        return False

    shutil.rmtree(resolved_directory)
    return True


async def delete_local_source(source_id: str) -> bool:
    """Delete one validated backend-managed source archive directory."""
    return await asyncio.to_thread(_delete_local_source_directory, source_id)
