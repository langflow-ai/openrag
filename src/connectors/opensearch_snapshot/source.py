"""Read-only access to an OpenSearch snapshot repository stored in S3.

The backend never trusts repository content: every key derived from decoded
metadata is validated against the supported repository layout before use, and
all errors carry user-safe text (never credentials). Custom S3 endpoints are
always addressed path-style and every request attempt is re-checked against the
endpoint policy (see :mod:`.endpoint_policy`, including its DNS-rebinding note).
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from .endpoint_policy import EndpointPolicyError, install_request_guard, validate_endpoint
from .metadata import (
    IndexMetadataInfo,
    MetadataFormatError,
    RepoIndex,
    RepositoryData,
    RepoSnapshot,
    ShardSnapshotManifest,
    decode_index_metadata,
    decode_shard_snapshot,
    parse_index_latest,
    parse_repository_data,
)

T = TypeVar("T")

MAX_REPOSITORY_DATA_BYTES = 128 * 1024 * 1024
MAX_METADATA_BLOB_BYTES = 64 * 1024 * 1024
_STREAM_CHUNK = 1024 * 1024
_FETCH_CONCURRENCY = 8
_MAX_SHARDS = 10_000

_SAFE = r"[A-Za-z0-9_-]"
_REPO_KEY_RE = re.compile(
    r"(?:index\.latest"
    r"|index-[0-9]{1,19}"
    rf"|(?:snap|meta)-{_SAFE}{{1,64}}\.dat"
    rf"|indices/{_SAFE}{{1,64}}/(?:"
    rf"meta-{_SAFE}{{1,64}}\.dat"
    r"|[0-9]{1,5}/(?:"
    rf"index-{_SAFE}{{1,64}}"
    rf"|snap-{_SAFE}{{1,64}}\.dat"
    rf"|__{_SAFE}{{1,128}}(?:\.part[0-9]{{1,6}})?"
    r")))",
    re.ASCII,
)

_STATE_NAMES = {0: "IN_PROGRESS", 1: "SUCCESS", 2: "FAILED", 3: "PARTIAL", 4: "INCOMPATIBLE"}
_LISTABLE_STATES = ("SUCCESS", "PARTIAL")
_LIST_SIZE_SHARD_BUDGET = 2000  # shard manifests fetched per list_snapshots call
_DATA_BLOB_RE = re.compile(r"indices/[^/]+/[0-9]+/__[^/]+")


def _manifest_bytes(manifests: Sequence[ShardSnapshotManifest | None]) -> int:
    """Bytes of every data blob named by the readable shard manifests."""
    return sum(size for m in manifests if m is not None for f in m.files for _b, size in f.blobs())


def _folder_restore_estimate(
    listing: dict[str, int], manifests: Sequence[ShardSnapshotManifest | None]
) -> int:
    """Conservative restored size of an index copied as a whole folder.

    Uses every data blob in the folder (an upper bound: blobs of other snapshots
    are included) or the readable manifests, whichever is larger; when the folder
    has no recognisable data blobs the whole listing counts. Never 0 for a
    non-empty folder.
    """
    data = sum(size for key, size in listing.items() if _DATA_BLOB_RE.fullmatch(key))
    return max(data, _manifest_bytes(manifests)) or sum(listing.values())


def validate_repo_key(key: str) -> str:
    """Return ``key`` if it matches the supported repository layout, else raise."""
    if not isinstance(key, str) or _REPO_KEY_RE.fullmatch(key) is None:
        raise SnapshotSourceError("repository contains an unsupported object key")
    return key


class SnapshotSourceError(Exception):
    """Failure reading a snapshot repository. ``str()`` is user-safe."""


@dataclass(frozen=True)
class S3Location:
    bucket: str
    prefix: str = ""
    region: str = "us-east-1"
    endpoint_url: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    path_style: bool = True
    verify_tls: bool = True


@dataclass(frozen=True)
class IndexInfo:
    name: str
    repo_index_id: str
    meta_identifier: str
    size_bytes: int


@dataclass(frozen=True)
class SnapshotInfo:
    name: str
    uuid: str
    state: str
    version: str | None
    repository_generation: int
    indices: tuple[IndexInfo, ...]


@dataclass(frozen=True)
class SnapshotDetail(SnapshotInfo):
    index_metadata: dict[str, IndexMetadataInfo] = field(default_factory=dict)
    unreadable: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestFile:
    key: str
    size: int
    crc32: int | None = None  # Lucene footer CRC of the whole blob, when the manifest provides it


@dataclass(frozen=True)
class StagingManifest:
    snapshot_name: str
    snapshot_uuid: str
    repository_generation: int
    indices: tuple[str, ...]
    files: tuple[ManifestFile, ...]
    kind: Literal["exact", "folder"] = "exact"
    # (index name, restored-size estimate in bytes); see ``restored_bytes``.
    index_bytes: tuple[tuple[str, int], ...] = ()

    def restored_bytes(self, index: str) -> int | None:
        """Estimated bytes OpenSearch restores for ``index``; ``None`` when not recorded."""
        return dict(self.index_bytes).get(index)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


def _client_error_message(exc: Exception, what: str) -> str:
    code = ""
    status = None
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if code in ("NoSuchBucket",):
        return "the bucket does not exist"
    if code in ("NoSuchKey", "404", "NotFound") or status == 404:
        return f"{what} was not found"
    if code in ("AccessDenied", "AllAccessDisabled", "403", "Forbidden") or status == 403:
        return "access to the bucket was denied"
    if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "InvalidToken", "ExpiredToken"):
        return "the access key or secret key was rejected"
    return "the object store returned an error"


def _build_client(location: S3Location) -> Any:
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    signed = bool(location.access_key and location.secret_key)
    endpoint = (location.endpoint_url or "").strip() or None
    # A custom endpoint is always addressed path-style: virtual-host addressing would
    # send requests to ``<bucket>.<endpoint host>``, a name the endpoint policy never
    # validated. ``path_style`` only selects the addressing of the AWS default endpoint.
    path_style = endpoint is not None or location.path_style
    config = Config(
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=5,
        read_timeout=60,
        signature_version=None if signed else UNSIGNED,
        s3={"addressing_style": "path" if path_style else "virtual"},
    )
    kwargs: dict[str, Any] = {
        "region_name": location.region or "us-east-1",
        "config": config,
        "verify": location.verify_tls,
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    if signed:
        kwargs["aws_access_key_id"] = location.access_key
        kwargs["aws_secret_access_key"] = location.secret_key
    # A private Session never consults the ambient credential chain for an
    # unsigned client and receives explicit keys otherwise.
    client = boto3.session.Session().client("s3", **kwargs)
    install_request_guard(client, endpoint)
    return client


class SnapshotSource:
    def __init__(self, location: S3Location, *, s3_client: Any | None = None):
        if bool(location.access_key) != bool(location.secret_key):
            raise SnapshotSourceError("access key and secret key must be provided together")
        if not location.bucket or not isinstance(location.bucket, str):
            raise SnapshotSourceError("a bucket name is required")
        try:
            validate_endpoint(location.endpoint_url)
        except EndpointPolicyError as exc:
            raise SnapshotSourceError(str(exc)) from exc
        self._location = location
        self._prefix = location.prefix.strip("/")
        self._client = s3_client if s3_client is not None else _build_client(location)
        self._details: dict[tuple[int, str], SnapshotDetail] = {}
        self._shards: dict[tuple[int, str], dict[str, list[ShardSnapshotManifest | None]]] = {}
        self._decoded: dict[str, Any] = {}

    # ------------------------------------------------------------------ S3 plumbing

    def _full_key(self, rel_key: str) -> str:
        return f"{self._prefix}/{rel_key}" if self._prefix else rel_key

    async def _call(self, what: str, fn: Callable[..., T], /, **kwargs: Any) -> T:
        try:
            return await asyncio.to_thread(fn, **kwargs)
        except SnapshotSourceError:
            raise
        except EndpointPolicyError as exc:  # raised by the request-time guard; text is user-safe
            raise SnapshotSourceError(str(exc)) from None
        except Exception as exc:  # botocore errors; never echo exc (may contain request ids/keys)
            if hasattr(exc, "response") or type(exc).__module__.startswith("botocore"):
                raise SnapshotSourceError(_client_error_message(exc, what)) from None
            raise

    async def _list(self, rel_prefix: str, *, delimiter: str | None = None) -> dict[str, int]:
        """Map of relative key -> size for objects under ``rel_prefix``."""
        base = f"{self._prefix}/" if self._prefix else ""
        prefix = base + rel_prefix
        sizes: dict[str, int] = {}
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self._location.bucket, "Prefix": prefix}
            if delimiter:
                kwargs["Delimiter"] = delimiter
            if token:
                kwargs["ContinuationToken"] = token
            page = await self._call("the repository", self._client.list_objects_v2, **kwargs)
            for item in page.get("Contents") or []:
                key = item["Key"]
                if key.startswith(base):
                    sizes[key[len(base) :]] = int(item["Size"])
            if not page.get("IsTruncated"):
                return sizes
            token = page.get("NextContinuationToken")
            if not token:
                return sizes

    # ------------------------------------------------------------------ public API

    async def test_connection(self) -> None:
        await self._call(
            "the repository",
            self._client.list_objects_v2,
            Bucket=self._location.bucket,
            Prefix=(f"{self._prefix}/" if self._prefix else ""),
            MaxKeys=1,
        )
        await self.repository_generation()

    async def read_bytes(self, rel_key: str, max_bytes: int) -> bytes:
        validate_repo_key(rel_key)

        def read() -> bytes:
            resp = self._client.get_object(
                Bucket=self._location.bucket, Key=self._full_key(rel_key)
            )
            body = resp["Body"]
            try:
                length = resp.get("ContentLength")
                if length is not None and int(length) > max_bytes:
                    raise SnapshotSourceError("repository object is larger than expected")
                data = body.read(max_bytes + 1)
            finally:
                close = getattr(body, "close", None)
                if close:
                    close()
            if len(data) > max_bytes:
                raise SnapshotSourceError("repository object is larger than expected")
            return data

        return await self._call("a repository object", read)

    async def repository_generation(self) -> int:
        try:
            raw = await self.read_bytes("index.latest", 16)
        except SnapshotSourceError as exc:
            if "not found" in str(exc):
                raise SnapshotSourceError(
                    "no OpenSearch snapshot repository was found at this location"
                ) from None
            raise
        try:
            return parse_index_latest(raw)
        except MetadataFormatError as exc:
            raise SnapshotSourceError("the repository pointer is unreadable") from exc

    async def _repository_data(self, generation: int) -> RepositoryData:
        raw = await self.read_bytes(f"index-{generation}", MAX_REPOSITORY_DATA_BYTES)
        try:
            return parse_repository_data(raw)
        except MetadataFormatError as exc:
            raise SnapshotSourceError("the repository data is unreadable or unsupported") from exc

    @staticmethod
    def _state_name(snapshot: RepoSnapshot) -> str:
        return (
            _STATE_NAMES.get(snapshot.state, "UNKNOWN") if snapshot.state is not None else "UNKNOWN"
        )

    @staticmethod
    def _snapshot_indices(data: RepositoryData, snapshot: RepoSnapshot) -> list[RepoIndex]:
        return sorted(
            (idx for idx in data.indices.values() if snapshot.uuid in idx.snapshots),
            key=lambda idx: idx.name,
        )

    def _info(
        self,
        data: RepositoryData,
        snapshot: RepoSnapshot,
        generation: int,
        sizes: dict[str, int] | None = None,
    ) -> SnapshotInfo:
        indices = []
        for idx in self._snapshot_indices(data, snapshot):
            try:
                identifier = data.meta_identifier(snapshot, idx)
            except MetadataFormatError:
                identifier = ""
            indices.append(IndexInfo(idx.name, idx.id, identifier, (sizes or {}).get(idx.name, 0)))
        return SnapshotInfo(
            name=snapshot.name,
            uuid=snapshot.uuid,
            state=self._state_name(snapshot),
            version=snapshot.version,
            repository_generation=generation,
            indices=tuple(indices),
        )

    async def list_snapshots(self) -> list[SnapshotInfo]:
        """SUCCESS and PARTIAL snapshots with per-index sizes.

        Sizes are exact: the sum of the data blobs named by each shard's
        ``snap-<uuid>.dat`` manifest (an index whose shard manifest cannot be read
        counts only its readable shards). At most ``_LIST_SIZE_SHARD_BUDGET``
        shard manifests are fetched per call; indices beyond that budget, in a
        legacy layout, or with unreadable manifests report 0 (unknown).
        """
        generation = await self.repository_generation()
        data = await self._repository_data(generation)
        snapshots = [snap for snap in data.snapshots if self._state_name(snap) in _LISTABLE_STATES]
        sizes = await self._list_sizes(data, snapshots)
        infos = [self._info(data, snap, generation, sizes.get(snap.uuid)) for snap in snapshots]
        return sorted(infos, key=lambda info: info.name)

    async def _list_sizes(
        self, data: RepositoryData, snapshots: Sequence[RepoSnapshot]
    ) -> dict[str, dict[str, int]]:
        """``{snapshot uuid: {index name: bytes}}`` from shard manifests, within the fetch budget."""
        budget = _LIST_SIZE_SHARD_BUDGET
        jobs: list[tuple[str, str, str]] = []  # (snapshot uuid, index name, manifest key)
        for snap in snapshots:
            for idx in self._snapshot_indices(data, snap):
                if (
                    idx.shard_path_type != 0
                    or idx.shard_generations is None
                    or not _valid_segment(idx.id)
                ):
                    continue
                shards = len(idx.shard_generations)
                if shards > budget:
                    continue
                budget -= shards
                jobs.extend(
                    (snap.uuid, idx.name, f"indices/{idx.id}/{shard}/snap-{snap.uuid}.dat")
                    for shard in range(shards)
                )
        results = await self._gather(
            [
                self._decode_blob(key, MAX_METADATA_BLOB_BYTES, decode_shard_snapshot)
                for _u, _n, key in jobs
            ]
        )
        sizes: dict[str, dict[str, int]] = {}
        for (uuid, name, _key), manifest in zip(jobs, results, strict=True):
            per_snapshot = sizes.setdefault(uuid, {})
            per_snapshot[name] = per_snapshot.get(name, 0) + (
                0 if isinstance(manifest, str) else _manifest_bytes([manifest])
            )
        return sizes

    async def _gather(self, coros: Sequence[Any]) -> list[Any]:
        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def run(coro: Any) -> Any:
            async with sem:
                return await coro

        return await asyncio.gather(*(run(c) for c in coros))

    async def _decode_blob(
        self, key: str, max_bytes: int, decoder: Callable[[bytes], T]
    ) -> T | str:
        """Decoded value, or a short reason string when the blob is unreadable.

        Repository blobs are immutable per key (they embed uuids/identifiers), so
        successful decodes are memoised for this source instance.
        """
        cached = self._decoded.get(key)
        if cached is not None:
            return cached
        try:
            raw = await self.read_bytes(key, max_bytes)
            value = decoder(raw)
        except MetadataFormatError:
            return "metadata could not be decoded"
        except SnapshotSourceError as exc:
            return str(exc)
        self._decoded[key] = value
        return value

    async def describe_snapshot(self, name: str) -> SnapshotDetail:
        generation = await self.repository_generation()
        cached = self._details.get((generation, name))
        if cached is not None:
            return cached
        data = await self._repository_data(generation)
        snapshot = data.find_snapshot(name)
        if snapshot is None:
            raise SnapshotSourceError("the snapshot was not found in the repository")

        state = self._state_name(snapshot)
        metadata: dict[str, IndexMetadataInfo] = {}
        unreadable: dict[str, str] = {}
        shard_manifests: dict[str, list[ShardSnapshotManifest | None]] = {}
        sizes: dict[str, int] = {}

        if state in _LISTABLE_STATES:
            repo_indices = self._snapshot_indices(data, snapshot)

            async def load_meta(idx: RepoIndex) -> tuple[RepoIndex, IndexMetadataInfo | str]:
                if idx.shard_path_type != 0:
                    return idx, "unsupported repository shard layout"
                try:
                    identifier = data.meta_identifier(snapshot, idx)
                except MetadataFormatError:
                    return idx, "metadata could not be decoded"
                result = await self._decode_blob(
                    f"indices/{idx.id}/meta-{identifier}.dat"
                    if _valid_segment(idx.id) and _valid_segment(identifier)
                    else "invalid",
                    MAX_METADATA_BLOB_BYTES,
                    decode_index_metadata,
                )
                return idx, result

            loaded = await self._gather([load_meta(idx) for idx in repo_indices])
            for idx, result in loaded:
                if isinstance(result, str):
                    unreadable[idx.name] = result
                else:
                    metadata[idx.name] = result

            async def load_shards(
                idx: RepoIndex,
            ) -> tuple[RepoIndex, list[ShardSnapshotManifest | None]]:
                shards = metadata[idx.name].number_of_shards
                if shards > _MAX_SHARDS or not _valid_segment(idx.id):
                    return idx, [None] * min(shards, 1)
                results = await self._gather(
                    [
                        self._decode_blob(
                            f"indices/{idx.id}/{shard}/snap-{snapshot.uuid}.dat",
                            MAX_METADATA_BLOB_BYTES,
                            decode_shard_snapshot,
                        )
                        for shard in range(shards)
                    ]
                )
                return idx, [None if isinstance(r, str) else r for r in results]

            for idx, manifests in await self._gather(
                [load_shards(idx) for idx in repo_indices if idx.name in metadata]
            ):
                shard_manifests[idx.name] = manifests
                sizes[idx.name] = _manifest_bytes(
                    manifests
                )  # decodable shards only when some are missing

        info = self._info(data, snapshot, generation, sizes)
        detail = SnapshotDetail(
            name=info.name,
            uuid=info.uuid,
            state=info.state,
            version=info.version,
            repository_generation=generation,
            indices=info.indices,
            index_metadata=metadata,
            unreadable=unreadable,
        )
        self._details[(generation, name)] = detail
        self._shards[(generation, name)] = shard_manifests
        return detail

    async def build_manifest(self, snapshot_name: str, indices: Sequence[str]) -> StagingManifest:
        """Exact copy manifest for ``indices`` of one snapshot at the pinned generation.

        Falls back to copying ``indices/<id>/**`` for an index whose shard
        manifests cannot be decoded; the resulting manifest has ``kind="folder"``.
        """
        detail = await self.describe_snapshot(snapshot_name)
        generation = detail.repository_generation
        data = await self._repository_data(generation)
        snapshot = data.find_snapshot(snapshot_name)
        if snapshot is None or detail.state not in _LISTABLE_STATES:
            raise SnapshotSourceError("the snapshot is not restorable")
        by_name = {idx.name: idx for idx in self._snapshot_indices(data, snapshot)}
        picked = sorted(set(indices))
        for name in picked:
            if name not in by_name:
                raise SnapshotSourceError("a selected index is not part of the snapshot")
            if name in detail.unreadable:
                raise SnapshotSourceError("a selected index has unreadable metadata")

        root_sizes = await self._list("", delimiter="/")
        files: dict[str, ManifestFile] = {}

        def add(key: str, size: int, crc: int | None = None) -> None:
            validate_repo_key(key)
            files[key] = ManifestFile(key, size, crc)

        def need_root(key: str) -> None:
            if key not in root_sizes:
                raise SnapshotSourceError(
                    "the repository is incomplete: a required file is missing"
                )
            add(key, root_sizes[key])

        need_root("index.latest")
        need_root(f"index-{generation}")
        need_root(f"snap-{snapshot.uuid}.dat")
        need_root(f"meta-{snapshot.uuid}.dat")

        kind: Literal["exact", "folder"] = "exact"
        index_bytes: list[tuple[str, int]] = []
        shard_cache = self._shards.get((generation, snapshot_name), {})
        for name in picked:
            repo_idx = by_name[name]
            if not _valid_segment(repo_idx.id):
                raise SnapshotSourceError("repository contains an unsupported index id")
            listing = await self._list(f"indices/{repo_idx.id}/")
            manifests = shard_cache.get(name) or []
            exact = (
                repo_idx.shard_generations is not None
                and len(repo_idx.shard_generations) == detail.index_metadata[name].number_of_shards
                and len(manifests) == len(repo_idx.shard_generations)
                and all(m is not None for m in manifests)
            )
            if not exact:
                kind = "folder"
                for key, size in listing.items():
                    add(key, size)
                index_bytes.append((name, _folder_restore_estimate(listing, manifests)))
                continue

            idx_bytes = 0
            identifier = data.meta_identifier(snapshot, repo_idx)
            meta_key = f"indices/{repo_idx.id}/meta-{identifier}.dat"
            if meta_key not in listing:
                raise SnapshotSourceError("the repository is incomplete: index metadata is missing")
            add(meta_key, listing[meta_key])
            assert repo_idx.shard_generations is not None
            for shard, (gen, manifest) in enumerate(
                zip(repo_idx.shard_generations, manifests, strict=True)
            ):
                assert manifest is not None
                base = f"indices/{repo_idx.id}/{shard}/"
                for key in (f"{base}snap-{snapshot.uuid}.dat", f"{base}index-{gen}"):
                    if key not in listing:
                        raise SnapshotSourceError(
                            "the repository is incomplete: shard metadata is missing"
                        )
                    add(key, listing[key])
                for shard_file in manifest.files:
                    for blob, size in shard_file.blobs():
                        key = f"{base}{blob}"
                        if key not in listing:
                            raise SnapshotSourceError(
                                "the repository is incomplete: a data file is missing"
                            )
                        if listing[key] != size:
                            raise SnapshotSourceError("a data file does not match its manifest")
                        crc = shard_file.lucene_crc32 if len(shard_file.blobs()) == 1 else None
                        add(key, size, crc)
                        idx_bytes += size
            index_bytes.append((name, idx_bytes))

        return StagingManifest(
            snapshot_name=snapshot.name,
            snapshot_uuid=snapshot.uuid,
            repository_generation=generation,
            indices=tuple(picked),
            files=tuple(sorted(files.values(), key=lambda f: f.key)),
            kind=kind,
            index_bytes=tuple(index_bytes),
        )

    async def stream(self, rel_key: str, expected_size: int) -> AsyncIterator[bytes]:
        """Yield the object in chunks, enforcing ``expected_size`` exactly."""
        validate_repo_key(rel_key)

        def open_body() -> Any:
            resp = self._client.get_object(
                Bucket=self._location.bucket, Key=self._full_key(rel_key)
            )
            length = resp.get("ContentLength")
            if length is not None and int(length) != expected_size:
                resp["Body"].close()
                raise SnapshotSourceError("a repository object changed size")
            return resp["Body"]

        body = await self._call("a repository object", open_body)
        total = 0
        try:
            while True:
                chunk = await self._call("a repository object", body.read, amt=_STREAM_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size:
                    raise SnapshotSourceError("a repository object changed size")
                yield chunk
        finally:
            close = getattr(body, "close", None)
            if close:
                await asyncio.to_thread(close)
        if total != expected_size:
            raise SnapshotSourceError("a repository object was truncated")

    async def download_to(self, rel_key: str, dest_path: Path, expected_size: int) -> None:
        """Download one object to a new file; refuses to overwrite or follow symlinks."""
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(dest_path, flags, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                async for chunk in self.stream(rel_key, expected_size):
                    await asyncio.to_thread(handle.write, chunk)
        except BaseException:
            try:
                os.unlink(dest_path)
            except OSError:
                pass
            raise


def _valid_segment(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value, re.ASCII) is not None
