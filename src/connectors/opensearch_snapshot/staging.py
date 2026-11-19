"""Staging of a picked snapshot's files into a repository OpenSearch can read.

Two stores: ``fs`` (shared directory listed in ``path.repo``) and ``s3`` (the
backend uploads with its own keys; OpenSearch reads with its keystore client).
Both copy exactly the files of a :class:`~.source.StagingManifest`, validating
every key against the supported repository layout first.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import shutil
import stat
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

from config.settings import (
    get_snapshot_staging_path,
    get_snapshot_staging_repo_location,
    get_snapshot_staging_s3_settings,
    get_snapshot_staging_type,
)

from .endpoint_policy import EndpointPolicyError, install_request_guard, validate_endpoint
from .naming import is_valid_slug, repo_name
from .source import (
    ManifestFile,
    SnapshotSource,
    SnapshotSourceError,
    StagingManifest,
    validate_repo_key,
)

ProgressCallback = Callable[[int, int], Any]

_CONCURRENCY = 4
_MULTIPART_PART_BYTES = 8 * 1024 * 1024
_FOOTER_TAIL = 8
_CODEC_KEY_RE = re.compile(
    r"(?:(?:snap|meta)-[A-Za-z0-9_-]+\.dat"
    r"|indices/[A-Za-z0-9_-]+/(?:meta-[A-Za-z0-9_-]+\.dat"
    r"|[0-9]+/(?:index-[A-Za-z0-9_-]+|snap-[A-Za-z0-9_-]+\.dat)))",
    re.ASCII,
)


class StagingError(Exception):
    """Staging failed. ``str()`` is user-safe."""


class StagingStore(Protocol):
    kind: Literal["fs", "s3"]

    def repository_name(self, slug: str, generation: int) -> str: ...

    def repository_body(self, slug: str, generation: int) -> dict: ...

    async def stage(
        self,
        slug: str,
        generation: int,
        source: SnapshotSource,
        manifest: StagingManifest,
        on_progress: ProgressCallback | None = None,
    ) -> int: ...

    async def remove(self, slug: str, generation: int | None = None) -> None: ...

    def free_bytes(self) -> int | None: ...


class _FooterCrc:
    """Streaming CRC32 over everything except the trailing 8 bytes (Lucene footer checksum)."""

    def __init__(self) -> None:
        self.crc = 0
        self.tail = b""

    def feed(self, chunk: bytes) -> None:
        buf = self.tail + chunk
        if len(buf) > _FOOTER_TAIL:
            self.crc = zlib.crc32(buf[:-_FOOTER_TAIL], self.crc)
            self.tail = buf[-_FOOTER_TAIL:]
        else:
            self.tail = buf

    def matches(self, expected: int | None) -> bool:
        if len(self.tail) != _FOOTER_TAIL:
            return False
        stored = int.from_bytes(self.tail, "big")
        if stored != self.crc:
            return False
        return expected is None or expected == self.crc


def _needs_footer_check(entry: ManifestFile) -> bool:
    return entry.crc32 is not None or _CODEC_KEY_RE.fullmatch(entry.key) is not None


def _check_target(slug: str, generation: int) -> None:
    if not is_valid_slug(slug):
        raise StagingError("invalid import identifier")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        raise StagingError("invalid import generation")


async def _notify(callback: ProgressCallback | None, done: int, total: int) -> None:
    if callback is None:
        return
    result = callback(done, total)
    if inspect.isawaitable(result):
        await result


async def _pin_check(source: SnapshotSource, manifest: StagingManifest) -> None:
    try:
        latest = await source.repository_generation()
    except SnapshotSourceError as exc:
        raise StagingError("source repository changed during copy") from exc
    if latest != manifest.repository_generation:
        raise StagingError("source repository changed during copy")


def _validated_files(manifest: StagingManifest) -> tuple[ManifestFile, ...]:
    for entry in manifest.files:
        try:
            validate_repo_key(entry.key)
        except SnapshotSourceError as exc:
            raise StagingError("manifest contains an unsupported object key") from exc
        if entry.size < 0:
            raise StagingError("manifest contains an invalid object size")
    return manifest.files


async def _run_all(files: tuple[ManifestFile, ...], worker: Callable[[ManifestFile], Any]) -> None:
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(entry: ManifestFile) -> None:
        async with sem:
            await worker(entry)

    try:
        async with asyncio.TaskGroup() as group:
            for entry in files:
                group.create_task(one(entry))
    except* StagingError as group_exc:
        raise group_exc.exceptions[0] from None
    except* SnapshotSourceError as group_exc:
        raise StagingError(str(group_exc.exceptions[0])) from None


# ---------------------------------------------------------------------------
# fs
# ---------------------------------------------------------------------------


def _fs_ensure_dir(root: Path, parts: list[str]) -> Path:
    """Create/validate each directory below ``root`` without following symlinks."""
    current = root
    for part in parts:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            try:
                os.mkdir(current, 0o755)
                os.chmod(current, 0o755)
                continue
            except FileExistsError:  # created concurrently by another file's worker
                info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode):
            raise StagingError("staging directory contains a symbolic link")
        if not stat.S_ISDIR(info.st_mode):
            raise StagingError("staging path conflicts with an existing file")
    return current


def _fs_existing_ok(path: Path, entry: ManifestFile) -> bool:
    """True when ``path`` is a regular file that already satisfies ``entry``."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        raise StagingError("staging directory contains a symbolic link")
    if not stat.S_ISREG(info.st_mode) or info.st_size != entry.size:
        return False
    if not _needs_footer_check(entry):
        return True
    footer = _FooterCrc()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            footer.feed(chunk)
    return footer.matches(entry.crc32)


def _fs_open_part(path: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(path, flags, 0o644)
    except FileExistsError:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            raise StagingError("staging directory contains a symbolic link") from None
        os.unlink(path)  # stale partial file from an interrupted run
        return os.open(path, flags, 0o644)


def _fs_remove_tree(path: Path) -> None:
    """Remove a directory tree; symlinks are unlinked, never followed."""
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            _fs_remove_tree(Path(entry.path))
        else:
            os.unlink(entry.path)
    os.rmdir(path)


class FsStagingStore:
    kind: Literal["fs", "s3"] = "fs"

    def __init__(self, root: str | Path, repo_location: str):
        self._root = Path(os.path.abspath(root))
        self._repo_location = repo_location.rstrip("/")

    def repository_name(self, slug: str, generation: int) -> str:
        return repo_name(slug, generation)

    def repository_body(self, slug: str, generation: int) -> dict:
        _check_target(slug, generation)
        return {
            "type": "fs",
            "settings": {
                "location": f"{self._repo_location}/{slug}/g{generation}",
                "readonly": True,
            },
        }

    def free_bytes(self) -> int | None:
        probe = self._root
        while not probe.exists():
            if probe.parent == probe:
                return None
            probe = probe.parent
        try:
            return shutil.disk_usage(probe).free
        except OSError:
            return None

    def _generation_dir(self, slug: str, generation: int) -> Path:
        _check_target(slug, generation)
        self._root.mkdir(parents=True, exist_ok=True)
        return _fs_ensure_dir(self._root, [slug, f"g{generation}"])

    async def stage(
        self,
        slug: str,
        generation: int,
        source: SnapshotSource,
        manifest: StagingManifest,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        files = _validated_files(manifest)
        try:
            base = await asyncio.to_thread(self._generation_dir, slug, generation)
        except OSError as exc:
            raise StagingError("staging directory is not writable") from exc
        total = sum(f.size for f in files)
        done = 0

        async def stage_file(entry: ManifestFile) -> None:
            nonlocal done
            parts = entry.key.split("/")
            try:
                parent = _fs_ensure_dir(base, parts[:-1])  # fast syscalls: no cancellation window
                final = parent / parts[-1]
                if await asyncio.to_thread(_fs_existing_ok, final, entry):
                    done += entry.size
                    await _notify(on_progress, done, total)
                    return
                part_path = parent / f"{parts[-1]}.part"
                fd = _fs_open_part(part_path)
            except OSError as exc:
                raise StagingError("staging directory is not writable") from exc
            footer = _FooterCrc() if _needs_footer_check(entry) else None
            written = 0
            try:
                with os.fdopen(fd, "wb") as handle:
                    async for chunk in source.stream(entry.key, entry.size):
                        await asyncio.to_thread(handle.write, chunk)
                        if footer is not None:
                            footer.feed(chunk)
                        written += len(chunk)
                        done += len(chunk)
                    await asyncio.to_thread(handle.flush)
                    os.fchmod(handle.fileno(), 0o644)
                if written != entry.size:
                    raise StagingError("a staged file has an unexpected size")
                if footer is not None and not footer.matches(entry.crc32):
                    raise StagingError("a staged file failed its integrity check")
                os.replace(part_path, final)
            except BaseException as exc:
                done -= written
                try:
                    os.unlink(part_path)
                except OSError:
                    pass
                if isinstance(exc, OSError):
                    raise StagingError("staging directory is not writable") from exc
                raise
            await _notify(on_progress, done, total)

        await _run_all(files, stage_file)
        await _pin_check(source, manifest)
        return total

    async def remove(self, slug: str, generation: int | None = None) -> None:
        if not is_valid_slug(slug):
            raise StagingError("invalid import identifier")
        if generation is not None:
            _check_target(slug, generation)

        def run() -> None:
            slug_dir = self._root / slug
            try:
                info = os.lstat(slug_dir)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise StagingError("staging directory contains a symbolic link")
            if generation is None:
                _fs_remove_tree(slug_dir)
                return
            target = slug_dir / f"g{generation}"
            try:
                tinfo = os.lstat(target)
            except FileNotFoundError:
                tinfo = None
            if tinfo is not None:
                if stat.S_ISLNK(tinfo.st_mode) or not stat.S_ISDIR(tinfo.st_mode):
                    raise StagingError("staging directory contains a symbolic link")
                _fs_remove_tree(target)
            try:
                os.rmdir(slug_dir)  # only succeeds when no other generation remains
            except OSError:
                pass

        try:
            await asyncio.to_thread(run)
        except OSError as exc:
            raise StagingError("staging directory could not be removed") from exc


# ---------------------------------------------------------------------------
# s3
# ---------------------------------------------------------------------------


def _sse_kwargs(sse_type: str | None, kms_key_id: str | None) -> dict[str, str]:
    """Upload-time SSE headers. Unset/``bucket_default`` sends none (R26)."""
    value = (sse_type or "").strip()
    if value.lower() in ("", "bucket_default"):
        return {}
    if value.upper() == "AES256":
        return {"ServerSideEncryption": "AES256"}
    if value.lower() == "aws:kms":
        if not kms_key_id:
            raise StagingError("aws:kms staging encryption requires a KMS key id")
        return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key_id}
    raise StagingError("unsupported staging encryption type")


class S3StagingStore:
    kind: Literal["fs", "s3"] = "s3"

    def __init__(self, settings: dict[str, str | None], *, s3_client: Any | None = None):
        bucket = settings.get("bucket")
        if not bucket:
            raise StagingError("S3 staging requires a bucket")
        access, secret = settings.get("access_key"), settings.get("secret_key")
        if bool(access) != bool(secret):
            raise StagingError("S3 staging access key and secret key must be provided together")
        try:
            self._endpoint = validate_endpoint(settings.get("endpoint"))
        except EndpointPolicyError as exc:
            raise StagingError(str(exc)) from exc
        self._bucket = bucket
        self._region = settings.get("region") or "us-east-1"
        self._base = (settings.get("prefix") or "").strip("/")
        self._os_client_name = settings.get("client") or "openrag"
        self._sse = _sse_kwargs(settings.get("sse_type"), settings.get("sse_kms_key_id"))
        self._inflight: set[asyncio.Future[Any]] = set()
        self._client = s3_client if s3_client is not None else self._build_client(access, secret)

    def _build_client(self, access: str | None, secret: str | None) -> Any:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config

        signed = bool(access and secret)
        config = Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=60,
            signature_version=None if signed else UNSIGNED,
            s3={"addressing_style": "path"},
        )
        kwargs: dict[str, Any] = {"region_name": self._region, "config": config}
        if self._endpoint:
            kwargs["endpoint_url"] = self._endpoint
        if signed:
            kwargs["aws_access_key_id"] = access
            kwargs["aws_secret_access_key"] = secret
        client = boto3.session.Session().client("s3", **kwargs)
        install_request_guard(client, self._endpoint)
        return client

    def _base_path(self, slug: str, generation: int | None = None) -> str:
        pieces = [p for p in (self._base, slug) if p]
        if generation is not None:
            pieces.append(f"g{generation}")
        return "/".join(pieces)

    def repository_name(self, slug: str, generation: int) -> str:
        return repo_name(slug, generation)

    def repository_body(self, slug: str, generation: int) -> dict:
        _check_target(slug, generation)
        settings: dict[str, Any] = {
            "bucket": self._bucket,
            "base_path": self._base_path(slug, generation),
            "client": self._os_client_name,
            "readonly": True,
        }
        if self._endpoint:
            settings["endpoint"] = self._endpoint
            settings["path_style_access"] = True
        if self._region:
            settings["region"] = self._region
        return {"type": "s3", "settings": settings}

    def free_bytes(self) -> int | None:
        return None

    async def _call(
        self,
        fn: Callable[..., Any],
        /,
        *,
        _on_result: Callable[[Any], None] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run a blocking SDK call in a worker thread and track it until it settles.

        A thread cannot be interrupted: cancelling the awaiter leaves the call
        running. Tracking lets :meth:`_drain` wait for it, and ``_on_result`` sees
        its result even when the awaiter is gone.
        """
        task = asyncio.ensure_future(asyncio.to_thread(fn, **kwargs))
        self._inflight.add(task)

        def settled(done: asyncio.Future[Any]) -> None:
            self._inflight.discard(done)
            if not done.cancelled() and done.exception() is None and _on_result is not None:
                _on_result(done.result())

        task.add_done_callback(settled)
        try:
            return await asyncio.shield(task)
        except EndpointPolicyError as exc:
            raise StagingError(str(exc)) from None
        except Exception as exc:
            if hasattr(exc, "response") or type(exc).__module__.startswith("botocore"):
                raise StagingError("the staging bucket rejected the request") from None
            raise

    async def _drain(self) -> None:
        """Wait until every tracked worker-thread call has settled.

        A cancellation that arrives while draining is deferred until the calls have
        settled and then re-raised, so cancellation is preserved but never races a write.
        """
        cancelled = False
        while True:
            pending = [task for task in self._inflight if not task.done()]
            if not pending:
                break
            try:
                await asyncio.wait(pending)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def _existing_size(self, key: str) -> int | None:
        try:
            resp = await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except EndpointPolicyError as exc:
            raise StagingError(str(exc)) from None
        except Exception as exc:
            response = getattr(exc, "response", None)
            if isinstance(response, dict) and (
                response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404
                or str(response.get("Error", {}).get("Code")) in ("404", "NoSuchKey", "NotFound")
            ):
                return None
            raise StagingError("the staging bucket rejected the request") from None
        return int(resp["ContentLength"])

    async def _upload(self, key: str, entry: ManifestFile, source: SnapshotSource) -> int:
        footer = _FooterCrc() if _needs_footer_check(entry) else None
        buffer = bytearray()
        upload_id: str | None = None
        parts: list[dict[str, Any]] = []
        written = 0

        def remember_upload(resp: Any) -> None:
            nonlocal upload_id
            upload_id = resp["UploadId"]

        def forget_upload(_resp: Any) -> None:
            nonlocal upload_id
            upload_id = None

        async def flush_part() -> None:
            if upload_id is None:
                # ``remember_upload`` also runs when this task is cancelled mid-call, so
                # the abort below still knows the upload id.
                await self._call(
                    self._client.create_multipart_upload,
                    _on_result=remember_upload,
                    Bucket=self._bucket,
                    Key=key,
                    **self._sse,
                )
            number = len(parts) + 1
            resp = await self._call(
                self._client.upload_part,
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                PartNumber=number,
                Body=bytes(buffer),
            )
            parts.append({"ETag": resp["ETag"], "PartNumber": number})
            buffer.clear()

        try:
            async for chunk in source.stream(entry.key, entry.size):
                written += len(chunk)
                if footer is not None:
                    footer.feed(chunk)
                buffer.extend(chunk)
                while len(buffer) >= _MULTIPART_PART_BYTES:
                    tail = bytes(buffer[_MULTIPART_PART_BYTES:])
                    del buffer[_MULTIPART_PART_BYTES:]
                    await flush_part()
                    buffer.extend(tail)
            if written != entry.size:
                raise StagingError("a staged object has an unexpected size")
            if footer is not None and not footer.matches(entry.crc32):
                raise StagingError("a staged object failed its integrity check")
            if upload_id is None:
                await self._call(
                    self._client.put_object,
                    Bucket=self._bucket,
                    Key=key,
                    Body=bytes(buffer),
                    **self._sse,
                )
            else:
                if buffer:
                    await flush_part()
                await self._call(
                    self._client.complete_multipart_upload,
                    _on_result=forget_upload,
                    Bucket=self._bucket,
                    Key=key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
                upload_id = None
        except BaseException:
            # Cancellation abandons the awaiter, not the worker thread: let the write
            # that was in flight settle before aborting or before cleanup can list/delete.
            await self._drain()
            if upload_id is not None:
                try:
                    await asyncio.shield(
                        asyncio.to_thread(
                            self._client.abort_multipart_upload,
                            Bucket=self._bucket,
                            Key=key,
                            UploadId=upload_id,
                        )
                    )
                except Exception:
                    pass
            raise
        size = await self._existing_size(key)
        if size != entry.size:
            raise StagingError("a staged object has an unexpected size")
        return written

    async def stage(
        self,
        slug: str,
        generation: int,
        source: SnapshotSource,
        manifest: StagingManifest,
        on_progress: ProgressCallback | None = None,
    ) -> int:
        _check_target(slug, generation)
        files = _validated_files(manifest)
        base = self._base_path(slug, generation)
        total = sum(f.size for f in files)
        done = 0

        async def stage_file(entry: ManifestFile) -> None:
            nonlocal done
            key = f"{base}/{entry.key}"
            if await self._existing_size(key) == entry.size:
                done += entry.size
            else:
                done += await self._upload(key, entry, source)
            await _notify(on_progress, done, total)

        try:
            await _run_all(files, stage_file)
        except BaseException:
            await self._drain()
            raise
        await _pin_check(source, manifest)
        return total

    async def remove(self, slug: str, generation: int | None = None) -> None:
        if not is_valid_slug(slug):
            raise StagingError("invalid import identifier")
        if generation is not None:
            _check_target(slug, generation)
        await self._drain()  # a write still running in a thread must not land after the delete
        prefix = self._base_path(slug, generation) + "/"
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = await self._call(self._client.list_objects_v2, **kwargs)
            keys = [{"Key": item["Key"]} for item in page.get("Contents") or []]
            if keys:
                await self._call(
                    self._client.delete_objects,
                    Bucket=self._bucket,
                    Delete={"Objects": keys, "Quiet": True},
                )
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")
            if not token:
                return


def get_staging_store() -> StagingStore:
    """Build the configured store from ``OPENRAG_SNAPSHOT_STAGING_*`` settings."""
    if get_snapshot_staging_type() == "s3":
        return S3StagingStore(get_snapshot_staging_s3_settings())
    return FsStagingStore(get_snapshot_staging_path(), get_snapshot_staging_repo_location())


__all__ = [
    "FsStagingStore",
    "S3StagingStore",
    "StagingError",
    "StagingStore",
    "get_staging_store",
]
