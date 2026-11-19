from __future__ import annotations

import asyncio
import os
import stat
import threading
import zlib

import pytest

from connectors.opensearch_snapshot import staging
from connectors.opensearch_snapshot.source import (
    ManifestFile,
    S3Location,
    SnapshotSource,
    StagingManifest,
)
from connectors.opensearch_snapshot.staging import FsStagingStore, S3StagingStore, StagingError

from ._fakes import (
    BUCKET,
    DISCOVERIES_ID,
    PREFIX,
    SNAP_V1,
    SNAP_V1_UUID,
    FakeS3,
    StubSource,
    load_repo,
)

SLUG = "abcdefghij"


@pytest.fixture(autouse=True)
def _resolve_public(monkeypatch):
    from connectors.opensearch_snapshot import endpoint_policy

    monkeypatch.delenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", raising=False)
    monkeypatch.setattr(endpoint_policy, "_resolve", lambda host, port: ["93.184.216.34"])


def lucene_blob(payload: bytes) -> bytes:
    """Bytes ending in a Lucene-style 8 byte CRC32 of everything before it."""
    return payload + zlib.crc32(payload).to_bytes(8, "big")


def make_manifest(
    files: dict[str, bytes], *, crc: set[str] = frozenset(), generation: int = 1
) -> StagingManifest:
    entries = tuple(
        ManifestFile(k, len(v), zlib.crc32(v[:-8]) if k in crc else None)
        for k, v in sorted(files.items())
    )
    return StagingManifest("snap", "uuid", generation, ("idx",), entries, "exact")


FILES = {
    "index.latest": (1).to_bytes(8, "big"),
    "index-1": b'{"snapshots": []}',
    f"indices/{DISCOVERIES_ID}/0/__blob": lucene_blob(b"A" * 5000),
    f"indices/{DISCOVERIES_ID}/0/index-gen": lucene_blob(b"G" * 10),
}
CRC = {f"indices/{DISCOVERIES_ID}/0/__blob"}


@pytest.fixture
def store(tmp_path):
    return FsStagingStore(tmp_path / "stage", "/usr/share/opensearch/snapshots")


def gen_dir(store, gen=1):
    return store._root / SLUG / f"g{gen}"


# ------------------------------------------------------------------ fs


def test_fs_repository_body_and_name(store):
    assert store.kind == "fs"
    assert store.repository_name(SLUG, 2) == f"openrag_stage_{SLUG}_g2"
    assert store.repository_body(SLUG, 2) == {
        "type": "fs",
        "settings": {"location": f"/usr/share/opensearch/snapshots/{SLUG}/g2", "readonly": True},
    }
    with pytest.raises(StagingError):
        store.repository_body("../evil", 1)


@pytest.mark.asyncio
async def test_fs_stage_copies_files_with_modes(store):
    src = StubSource(FILES)
    progress = []
    total = await store.stage(
        SLUG, 1, src, make_manifest(FILES, crc=CRC), lambda d, t: progress.append((d, t))
    )
    assert total == sum(len(v) for v in FILES.values())
    for key, data in FILES.items():
        path = gen_dir(store) / key
        assert path.read_bytes() == data
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert stat.S_IMODE(gen_dir(store).stat().st_mode) == 0o755
    assert stat.S_IMODE((gen_dir(store) / "indices").stat().st_mode) == 0o755
    assert not list(gen_dir(store).rglob("*.part"))
    assert progress[-1] == (total, total)


@pytest.mark.asyncio
async def test_fs_stage_async_progress_callback(store):
    seen = []

    async def cb(done, total):
        seen.append(done)

    await store.stage(SLUG, 1, StubSource(FILES), make_manifest(FILES), cb)
    assert seen and seen[-1] == sum(map(len, FILES.values()))


@pytest.mark.asyncio
async def test_fs_resume_skips_verified_files(store):
    manifest = make_manifest(FILES, crc=CRC)
    await store.stage(SLUG, 1, StubSource(FILES), manifest)
    src = StubSource(FILES)
    await store.stage(SLUG, 1, src, manifest)
    assert src.streamed == []  # nothing re-downloaded
    # Truncate one file and corrupt another of the same size: both are re-fetched.
    (gen_dir(store) / "index-1").write_bytes(b"short")
    blob = gen_dir(store) / f"indices/{DISCOVERIES_ID}/0/__blob"
    corrupted = bytearray(blob.read_bytes())
    corrupted[10] ^= 0xFF
    blob.write_bytes(bytes(corrupted))
    src = StubSource(FILES)
    await store.stage(SLUG, 1, src, manifest)
    assert sorted(src.streamed) == sorted(["index-1", f"indices/{DISCOVERIES_ID}/0/__blob"])
    assert blob.read_bytes() == FILES[f"indices/{DISCOVERIES_ID}/0/__blob"]


@pytest.mark.asyncio
async def test_fs_stale_part_file_is_replaced(store):
    manifest = make_manifest(FILES)
    gd = gen_dir(store)
    gd.mkdir(parents=True)
    (gd / "index-1.part").write_bytes(b"stale half file")
    await store.stage(SLUG, 1, StubSource(FILES), manifest)
    assert (gd / "index-1").read_bytes() == FILES["index-1"]
    assert not (gd / "index-1.part").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [
        "../escape",
        "indices/../../escape",
        "/etc/passwd",
        "indices/abc/0/__x/../../../escape",
        "other-file",
        "indices/abc/0/index-x\n",
        "indices/a b/meta-x.dat",
        "index-1\x00",
    ],
)
async def test_fs_rejects_traversal_and_odd_keys(store, key, tmp_path):
    manifest = StagingManifest("s", "u", 1, ("i",), (ManifestFile(key, 3, None),), "exact")
    src = StubSource({key: b"abc"})
    with pytest.raises(StagingError, match="unsupported object key"):
        await store.stage(SLUG, 1, src, manifest)
    assert src.streamed == []
    assert not (tmp_path / "escape").exists()


@pytest.mark.asyncio
async def test_fs_refuses_symlinked_directory(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    gd = gen_dir(store)
    gd.mkdir(parents=True)
    (gd / "indices").symlink_to(outside)
    with pytest.raises(StagingError, match="symbolic link"):
        await store.stage(SLUG, 1, StubSource(FILES), make_manifest(FILES))
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_fs_refuses_symlinked_generation_and_slug_dirs(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (store._root / SLUG).mkdir(parents=True)
    (store._root / SLUG / "g1").symlink_to(outside)
    with pytest.raises(StagingError, match="symbolic link"):
        await store.stage(SLUG, 1, StubSource(FILES), make_manifest(FILES))
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio
async def test_fs_refuses_symlink_at_file_and_part_path(store, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("keep")
    gd = gen_dir(store)
    gd.mkdir(parents=True)
    (gd / "index-1").symlink_to(secret)
    with pytest.raises(StagingError, match="symbolic link"):
        await store.stage(SLUG, 1, StubSource(FILES), make_manifest(FILES))
    assert secret.read_text() == "keep"
    (gd / "index-1").unlink()
    (gd / "index-1.part").symlink_to(secret)
    with pytest.raises(StagingError, match="symbolic link"):
        await store.stage(SLUG, 1, StubSource(FILES), make_manifest(FILES))
    assert secret.read_text() == "keep"


@pytest.mark.asyncio
async def test_fs_detects_source_generation_change(store):
    src = StubSource(FILES, generation=1)
    manifest = make_manifest(FILES)

    def bump(key, data):
        src.generation = 2  # repository advanced while copying

    src.hook = bump
    with pytest.raises(StagingError, match="source repository changed during copy"):
        await store.stage(SLUG, 1, src, manifest)


@pytest.mark.asyncio
async def test_fs_integrity_failure_removes_part_file(store):
    src = StubSource(FILES)
    blob_key = f"indices/{DISCOVERIES_ID}/0/__blob"
    src.hook = lambda key, data: (data[:10] + b"X" + data[11:]) if key == blob_key else None
    with pytest.raises(StagingError, match="integrity"):
        await store.stage(SLUG, 1, src, make_manifest(FILES, crc=CRC))
    assert not list(gen_dir(store).rglob("*.part"))
    assert not (gen_dir(store) / blob_key).exists()


@pytest.mark.asyncio
async def test_fs_codec_blobs_are_footer_checked_without_manifest_crc(store):
    key = f"indices/{DISCOVERIES_ID}/meta-id1.dat"
    good = lucene_blob(b"meta" * 10)
    manifest = StagingManifest("s", "u", 1, ("i",), (ManifestFile(key, len(good), None),), "exact")
    src = StubSource({key: good[:-1] + bytes([good[-1] ^ 1])})
    with pytest.raises(StagingError, match="integrity"):
        await store.stage(SLUG, 1, src, manifest)
    await store.stage(SLUG, 1, StubSource({key: good}), manifest)


@pytest.mark.asyncio
async def test_fs_size_mismatch_from_source_is_staging_error(store):
    src = StubSource(FILES)
    manifest = make_manifest({**FILES, "index-1": FILES["index-1"] + b"x"})  # manifest says larger
    src.hook = None

    class Short(StubSource):
        async def stream(self, key, expected_size):
            async for chunk in super().stream(key, expected_size):
                yield chunk

    with pytest.raises(StagingError, match="unexpected size"):
        await store.stage(SLUG, 1, Short(FILES), manifest)
    assert not list(gen_dir(store).rglob("*.part"))


@pytest.mark.asyncio
async def test_fs_end_to_end_with_real_source(store):
    fake = FakeS3(load_repo())
    source = SnapshotSource(S3Location(bucket=BUCKET, prefix=PREFIX), s3_client=fake)
    manifest = await source.build_manifest(SNAP_V1, ["scientific_discoveries"])
    staged = await store.stage(SLUG, 1, source, manifest)
    assert staged == manifest.total_bytes == 19534
    on_disk = {str(p.relative_to(gen_dir(store))) for p in gen_dir(store).rglob("*") if p.is_file()}
    assert on_disk == {f.key for f in manifest.files}
    assert (gen_dir(store) / f"snap-{SNAP_V1_UUID}.dat").stat().st_size == 339


@pytest.mark.asyncio
async def test_fs_remove_one_generation_then_all(store):
    manifest = make_manifest(FILES)
    await store.stage(SLUG, 1, StubSource(FILES), manifest)
    await store.stage(SLUG, 2, StubSource(FILES, generation=1), manifest)
    await store.remove(SLUG, 1)
    assert not gen_dir(store, 1).exists() and gen_dir(store, 2).exists()
    await store.remove(SLUG, 2)
    assert not (store._root / SLUG).exists()  # empty slug dir pruned
    await store.remove(SLUG, 2)  # idempotent
    await store.stage(SLUG, 1, StubSource(FILES), manifest)
    await store.stage(SLUG, 2, StubSource(FILES), manifest)
    await store.remove(SLUG)
    assert not (store._root / SLUG).exists()


@pytest.mark.asyncio
async def test_fs_remove_never_follows_symlinks(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    await store.stage(SLUG, 1, StubSource(FILES), make_manifest(FILES))
    (gen_dir(store) / "inner-link").symlink_to(
        outside
    )  # link inside the tree is unlinked, not followed
    await store.remove(SLUG, 1)
    assert (outside / "keep.txt").read_text() == "keep"
    assert not gen_dir(store).exists()

    (store._root / SLUG).mkdir(parents=True, exist_ok=True)
    os.rmdir(store._root / SLUG)
    (store._root / SLUG).symlink_to(outside)
    with pytest.raises(StagingError, match="symbolic link"):
        await store.remove(SLUG)
    with pytest.raises(StagingError, match="symbolic link"):
        await store.remove(SLUG, 1)
    assert (outside / "keep.txt").read_text() == "keep"


@pytest.mark.asyncio
async def test_fs_remove_validates_arguments(store):
    with pytest.raises(StagingError):
        await store.remove("../x")
    with pytest.raises(StagingError):
        await store.remove(SLUG, -1)


def test_fs_free_bytes_walks_up_to_existing_parent(store):
    assert store.free_bytes() > 0  # root does not exist yet


# ------------------------------------------------------------------ factory


def test_get_staging_store_selects_by_config(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENRAG_SNAPSHOT_STAGING_TYPE", "fs")
    monkeypatch.setenv("OPENRAG_SNAPSHOT_STAGING_PATH", str(tmp_path))
    monkeypatch.setenv("OPENRAG_SNAPSHOT_STAGING_REPO_LOCATION", "/repo/root/")
    store = staging.get_staging_store()
    assert isinstance(store, FsStagingStore)
    assert store.repository_body(SLUG, 1)["settings"]["location"] == f"/repo/root/{SLUG}/g1"
    monkeypatch.setenv("OPENRAG_SNAPSHOT_STAGING_TYPE", "s3")
    monkeypatch.setenv("OPENRAG_SNAPSHOT_STAGING_S3_BUCKET", "stage-bucket")
    assert isinstance(staging.get_staging_store(), S3StagingStore)
    monkeypatch.delenv("OPENRAG_SNAPSHOT_STAGING_S3_BUCKET")
    with pytest.raises(StagingError, match="bucket"):
        staging.get_staging_store()


# ------------------------------------------------------------------ s3


def s3_settings(**over):
    base = {
        "endpoint": None,
        "region": "eu-west-1",
        "bucket": "stage",
        "prefix": "pre/fix",
        "access_key": "AK",
        "secret_key": "SK",
        "client": "openrag",
        "sse_type": None,
        "sse_kms_key_id": None,
    }
    base.update(over)
    return base


def s3_store(dest=None, **over):
    dest = dest or FakeS3({}, prefix="", bucket="stage")
    return S3StagingStore(s3_settings(**over), s3_client=dest), dest


def test_s3_repository_body():
    store, _ = s3_store()
    assert store.kind == "s3" and store.free_bytes() is None
    body = store.repository_body(SLUG, 3)
    assert body["type"] == "s3"
    assert body["settings"] == {
        "bucket": "stage",
        "base_path": f"pre/fix/{SLUG}/g3",
        "client": "openrag",
        "readonly": True,
        "region": "eu-west-1",
    }
    assert "access_key" not in str(body) and "secret_key" not in str(body)
    custom, _ = s3_store(endpoint="https://s3.example.com", prefix="", client="stagingclient")
    settings = custom.repository_body(SLUG, 1)["settings"]
    assert (
        settings["endpoint"] == "https://s3.example.com" and settings["path_style_access"] is True
    )
    assert settings["base_path"] == f"{SLUG}/g1" and settings["client"] == "stagingclient"


@pytest.mark.asyncio
async def test_s3_staging_client_refuses_a_destination_that_turns_private(monkeypatch):
    from connectors.opensearch_snapshot import endpoint_policy

    store = S3StagingStore(s3_settings(endpoint="http://storage.example.test:9000"))
    assert store._client.meta.config.s3["addressing_style"] == "path"
    # DNS rebinding after the constructor-time check: refused before any connection is made.
    monkeypatch.setattr(endpoint_policy, "_resolve", lambda host, port: ["10.0.0.5"])
    with pytest.raises(StagingError, match="private or local"):
        await store._call(store._client.list_objects_v2, Bucket="stage")
    with pytest.raises(StagingError, match="private or local"):
        await store._existing_size("pre/fix/key")


def test_s3_constructor_validation(monkeypatch):
    with pytest.raises(StagingError, match="together"):
        S3StagingStore(s3_settings(secret_key=None), s3_client=object())
    with pytest.raises(StagingError):
        S3StagingStore(s3_settings(endpoint="http://169.254.169.254"), s3_client=object())
    with pytest.raises(StagingError):
        S3StagingStore(s3_settings(endpoint="http://127.0.0.1:9000"), s3_client=object())
    monkeypatch.setenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", "127.0.0.1:9000")
    S3StagingStore(s3_settings(endpoint="http://127.0.0.1:9000"), s3_client=object())


@pytest.mark.asyncio
async def test_s3_stage_uploads_and_verifies():
    store, dest = s3_store()
    total = await store.stage(SLUG, 1, StubSource(FILES), make_manifest(FILES, crc=CRC))
    assert total == sum(map(len, FILES.values()))
    for key, data in FILES.items():
        assert dest.objects[f"pre/fix/{SLUG}/g1/{key}"] == data
    assert not dest.uploads


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sse", "kms", "expected"),
    [
        (None, None, {}),
        ("", None, {}),
        ("bucket_default", None, {}),
        ("BUCKET_DEFAULT", None, {}),
        ("AES256", None, {"ServerSideEncryption": "AES256"}),
        (
            "aws:kms",
            "arn:aws:kms:key",
            {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "arn:aws:kms:key"},
        ),
    ],
)
async def test_s3_sse_headers(sse, kms, expected):
    store, dest = s3_store(sse_type=sse, sse_kms_key_id=kms)
    await store.stage(SLUG, 1, StubSource({"index-1": b"{}"}), make_manifest({"index-1": b"{}"}))
    kwargs = dest.put_kwargs[f"pre/fix/{SLUG}/g1/index-1"]
    sse_args = {k: v for k, v in kwargs.items() if k.startswith(("ServerSide", "SSE"))}
    assert sse_args == expected
    assert "bucket_default" not in str(kwargs).lower()


def test_s3_sse_validation():
    with pytest.raises(StagingError, match="KMS"):
        s3_store(sse_type="aws:kms")
    with pytest.raises(StagingError, match="unsupported"):
        s3_store(sse_type="DES")


@pytest.mark.asyncio
async def test_s3_multipart_with_sse_on_create(monkeypatch):
    monkeypatch.setattr(staging, "_MULTIPART_PART_BYTES", 1500)
    big = lucene_blob(bytes(range(256)) * 20)  # 5128 bytes -> 4 parts
    key = f"indices/{DISCOVERIES_ID}/0/__big"
    store, dest = s3_store(sse_type="AES256")
    await store.stage(SLUG, 1, StubSource({key: big}), make_manifest({key: big}, crc={key}))
    full = f"pre/fix/{SLUG}/g1/{key}"
    assert dest.objects[full] == big
    assert dest.multipart_kwargs[full]["ServerSideEncryption"] == "AES256"
    parts = [c for c in dest.calls if c[0] == "upload_part"]
    assert len(parts) == 4 and [p[1]["PartNumber"] for p in parts] == [1, 2, 3, 4]
    assert not dest.uploads


@pytest.mark.asyncio
async def test_s3_multipart_aborted_on_integrity_failure(monkeypatch):
    monkeypatch.setattr(staging, "_MULTIPART_PART_BYTES", 1500)
    big = lucene_blob(b"z" * 5000)
    key = f"indices/{DISCOVERIES_ID}/0/__big"
    src = StubSource({key: big})
    src.hook = lambda k, d: d[:100] + b"Q" + d[101:]
    store, dest = s3_store()
    with pytest.raises(StagingError, match="integrity"):
        await store.stage(SLUG, 1, src, make_manifest({key: big}, crc={key}))
    assert not dest.uploads and f"pre/fix/{SLUG}/g1/{key}" not in dest.objects
    assert any(c[0] == "abort" for c in dest.calls)


@pytest.mark.asyncio
async def test_s3_resume_skips_objects_of_exact_size():
    store, dest = s3_store()
    manifest = make_manifest(FILES, crc=CRC)
    await store.stage(SLUG, 1, StubSource(FILES), manifest)
    src = StubSource(FILES)
    dest.calls.clear()
    await store.stage(SLUG, 1, src, manifest)
    assert src.streamed == [] and not [c for c in dest.calls if c[0] in ("put", "create_multipart")]
    dest.objects[f"pre/fix/{SLUG}/g1/index-1"] = b"x"  # wrong size -> re-upload
    await store.stage(SLUG, 1, src, manifest)
    assert src.streamed == ["index-1"]


@pytest.mark.asyncio
async def test_s3_generation_change_detected_and_keys_validated():
    store, _ = s3_store()
    src = StubSource(FILES)
    src.hook = lambda k, d: setattr(src, "generation", 9)
    with pytest.raises(StagingError, match="source repository changed"):
        await store.stage(SLUG, 1, src, make_manifest(FILES))
    bad = StagingManifest("s", "u", 1, ("i",), (ManifestFile("../x", 1, None),), "exact")
    with pytest.raises(StagingError, match="unsupported object key"):
        await store.stage(SLUG, 1, StubSource({"../x": b"a"}), bad)


@pytest.mark.asyncio
async def test_s3_remove_generation_and_all():
    store, dest = s3_store()
    manifest = make_manifest(FILES)
    await store.stage(SLUG, 1, StubSource(FILES), manifest)
    await store.stage(SLUG, 2, StubSource(FILES), manifest)
    dest.objects["pre/fix/otherslug/g1/index-1"] = b"x"
    dest.objects[f"pre/fix/{SLUG}x/g1/index-1"] = b"x"  # prefix confusion must survive
    await store.remove(SLUG, 1)
    assert not [k for k in dest.objects if k.startswith(f"pre/fix/{SLUG}/g1/")]
    assert [k for k in dest.objects if k.startswith(f"pre/fix/{SLUG}/g2/")]
    await store.remove(SLUG)
    assert sorted(dest.objects) == [f"pre/fix/{SLUG}x/g1/index-1", "pre/fix/otherslug/g1/index-1"]
    with pytest.raises(StagingError):
        await store.remove("bad slug")


class BlockingS3(FakeS3):
    """FakeS3 whose ``block_on`` call parks in its worker thread until ``release`` is set."""

    def __init__(self, block_on: str):
        super().__init__({}, prefix="", bucket="stage")
        self.block_on = block_on
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def _gate(self, name, fn, **kw):
        blocking = name == self.block_on
        if blocking:
            self.entered.set()
            assert self.release.wait(10), "test never released the blocked write"
        result = fn(**kw)
        if blocking:
            self.finished.set()
        return result

    def put_object(self, **kw):
        return self._gate("put_object", super().put_object, **kw)

    def create_multipart_upload(self, **kw):
        return self._gate("create_multipart_upload", super().create_multipart_upload, **kw)

    def upload_part(self, **kw):
        return self._gate("upload_part", super().upload_part, **kw)

    def complete_multipart_upload(self, **kw):
        return self._gate("complete_multipart_upload", super().complete_multipart_upload, **kw)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "block_on",
    ["put_object", "create_multipart_upload", "upload_part", "complete_multipart_upload"],
)
async def test_s3_cancellation_drains_the_inflight_write_before_cleanup(monkeypatch, block_on):
    monkeypatch.setattr(staging, "_MULTIPART_PART_BYTES", 1500)
    key = f"indices/{DISCOVERIES_ID}/0/__big"
    data = lucene_blob(b"z" * 5000) if block_on != "put_object" else lucene_blob(b"z" * 100)
    dest = BlockingS3(block_on)
    store, _ = s3_store(dest)
    task = asyncio.create_task(
        store.stage(SLUG, 1, StubSource({key: data}), make_manifest({key: data}, crc={key}))
    )
    assert await asyncio.to_thread(dest.entered.wait, 10)
    task.cancel()
    # The SDK write only finishes after cancellation was requested.
    asyncio.get_running_loop().call_later(0.2, dest.release.set)
    with pytest.raises(asyncio.CancelledError):
        await task
    # Cancellation must not propagate (and cleanup must not start) while the write is running.
    assert dest.finished.is_set()
    await store.remove(SLUG, 1)
    assert not dest.objects, "a staged object survived cleanup"
    assert not dest.uploads, "a multipart upload survived cleanup"


@pytest.mark.asyncio
async def test_s3_remove_waits_for_a_write_that_is_still_running():
    dest = BlockingS3("put_object")
    store, _ = s3_store(dest)
    key = "index-1"
    task = asyncio.create_task(
        store.stage(SLUG, 1, StubSource({key: b"{}"}), make_manifest({key: b"{}"}))
    )
    assert await asyncio.to_thread(dest.entered.wait, 10)
    task.cancel()
    # Cleanup is requested while the worker thread is still blocked inside put_object.
    asyncio.get_running_loop().call_later(0.2, dest.release.set)
    remover = asyncio.create_task(store.remove(SLUG, 1))
    with pytest.raises(asyncio.CancelledError):
        await task
    await remover
    assert dest.finished.is_set() and not dest.objects


# ------------------------------------------------------------------ config getters


def test_snapshot_config_getters(monkeypatch):
    from config import settings as s

    for key in list(os.environ):
        if key.startswith("OPENRAG_SNAPSHOT_"):
            monkeypatch.delenv(key)
    assert s.get_snapshot_staging_type() == "fs"
    assert s.get_snapshot_staging_path() == "opensearch-snapshots"
    assert s.get_snapshot_staging_repo_location() == "/usr/share/opensearch/snapshots"
    assert (
        s.get_snapshot_allowed_endpoints() == []
        and s.snapshot_endpoint_allowlist_required() is False
    )
    assert s.get_snapshot_shared_backend_role() == "openrag_user"
    assert s.get_snapshot_max_import_bytes() == 10737418240
    assert s.get_snapshot_max_imports_per_user() == 10
    assert s.get_snapshot_max_analyser_file_bytes() == 1048576
    assert s.get_snapshot_staging_s3_settings()["client"] == "openrag"
    monkeypatch.setenv("OPENRAG_SNAPSHOT_STAGING_TYPE", "weird")
    monkeypatch.setenv(
        "OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", " A.example.com , *.b.example.com:9000 ,,"
    )
    monkeypatch.setenv("OPENRAG_SNAPSHOT_MAX_IMPORT_BYTES", "oops")
    monkeypatch.setenv("OPENRAG_SNAPSHOT_MAX_IMPORTS_PER_USER", "0")
    assert s.get_snapshot_staging_type() == "fs"
    assert s.get_snapshot_allowed_endpoints() == ["a.example.com", "*.b.example.com:9000"]
    assert (
        s.get_snapshot_max_import_bytes() == 10737418240
        and s.get_snapshot_max_imports_per_user() == 1
    )


@pytest.mark.parametrize(
    ("enabled", "langflow_chat_disabled", "storage", "expected"),
    [
        ("false", True, "db", (False, "disabled")),
        ("", True, "db", (False, "disabled")),
        ("true", False, "db", (False, "langflow_chat")),
        ("true", True, "files", (False, "storage_mode")),
        ("true", True, "db", (True, None)),
        ("1", True, "hybrid", (True, None)),
    ],
)
def test_is_snapshot_import_available(
    monkeypatch, enabled, langflow_chat_disabled, storage, expected
):
    from config import settings as s

    monkeypatch.delenv("OPENRAG_DISABLE_DB_WORKSPACE_CONFIG", raising=False)
    monkeypatch.setenv("OPENRAG_SNAPSHOT_IMPORT_ENABLED", enabled)
    monkeypatch.setenv("OPENRAG_STORAGE_MODE", storage)
    monkeypatch.setattr(s, "DISABLE_CHAT_WITH_LANGFLOW", langflow_chat_disabled)
    assert s.is_snapshot_import_available() == expected
