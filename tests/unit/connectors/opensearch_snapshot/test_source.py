from __future__ import annotations

import socket

import pytest

from connectors.opensearch_snapshot.source import (
    S3Location,
    SnapshotSource,
    SnapshotSourceError,
    validate_repo_key,
)

from ._fakes import (
    BUCKET,
    DISCOVERIES_ID,
    PREFIX,
    SCIENTISTS_ID,
    SNAP_V1,
    SNAP_V1_UUID,
    FakeS3,
    load_repo,
)

LOCATION = S3Location(bucket=BUCKET, prefix=PREFIX)


@pytest.fixture
def repo():
    return load_repo()


@pytest.fixture
def fake(repo):
    return FakeS3(repo)


@pytest.fixture
def source(fake):
    return SnapshotSource(LOCATION, s3_client=fake)


# ------------------------------------------------------------------ construction


def test_keys_must_be_paired():
    with pytest.raises(SnapshotSourceError, match="together"):
        SnapshotSource(S3Location(bucket="b", access_key="a"), s3_client=object())
    with pytest.raises(SnapshotSourceError, match="together"):
        SnapshotSource(S3Location(bucket="b", secret_key="s"), s3_client=object())


def test_endpoint_policy_is_applied_even_with_injected_client(monkeypatch):
    monkeypatch.delenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", raising=False)
    with pytest.raises(SnapshotSourceError, match="private or local"):
        SnapshotSource(
            S3Location(bucket="b", endpoint_url="http://127.0.0.1:9000"), s3_client=object()
        )
    with pytest.raises(SnapshotSourceError, match="blocked"):
        SnapshotSource(
            S3Location(bucket="b", endpoint_url="http://169.254.169.254"), s3_client=object()
        )
    monkeypatch.setenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", "127.0.0.1:9000")
    SnapshotSource(S3Location(bucket="b", endpoint_url="http://127.0.0.1:9000"), s3_client=object())


def test_unsigned_client_without_keys_ignores_ambient_credentials(monkeypatch):
    from botocore import UNSIGNED

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENTKEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "AMBIENTSECRET")
    client = SnapshotSource(S3Location(bucket="b"))._client
    assert client.meta.config.signature_version is UNSIGNED
    assert client._request_signer._credentials is None


def test_signed_client_uses_explicit_keys_and_path_style(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENTKEY")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "AMBIENTSECRET")
    client = SnapshotSource(
        S3Location(bucket="b", access_key="AKEXPLICIT", secret_key="sk-explicit")
    )._client
    assert client._request_signer._credentials.access_key == "AKEXPLICIT"
    assert client.meta.config.s3["addressing_style"] == "path"
    assert client.meta.config.connect_timeout == 5 and client.meta.config.read_timeout == 60
    virtual = SnapshotSource(S3Location(bucket="b", path_style=False))._client
    assert virtual.meta.config.s3["addressing_style"] == "virtual"


# ------------------------------------------------------------------ listing


@pytest.mark.asyncio
async def test_test_connection_and_generation(source):
    await source.test_connection()
    assert await source.repository_generation() == 1


@pytest.mark.asyncio
async def test_missing_repository_is_user_friendly(repo):
    del repo["index.latest"]
    src = SnapshotSource(LOCATION, s3_client=FakeS3(repo))
    with pytest.raises(SnapshotSourceError, match="no OpenSearch snapshot repository"):
        await src.test_connection()


@pytest.mark.asyncio
async def test_missing_bucket_message_has_no_secrets(repo):
    src = SnapshotSource(
        S3Location(
            bucket="other", prefix=PREFIX, access_key="AKSECRET1", secret_key="topsecretvalue"
        ),
        s3_client=FakeS3(repo),
    )
    with pytest.raises(SnapshotSourceError) as err:
        await src.test_connection()
    assert "bucket" in str(err.value)
    assert "AKSECRET1" not in str(err.value) and "topsecretvalue" not in str(err.value)


@pytest.mark.asyncio
async def test_list_snapshots(source):
    snaps = await source.list_snapshots()
    assert [s.name for s in snaps] == ["scientists-v1", "scientists-v2"]
    v1 = snaps[0]
    assert (v1.uuid, v1.state, v1.version, v1.repository_generation) == (
        SNAP_V1_UUID,
        "SUCCESS",
        "3.8.0",
        1,
    )
    assert [i.name for i in v1.indices] == ["famous_scientists", "scientific_discoveries"]
    assert {i.repo_index_id for i in v1.indices} == {SCIENTISTS_ID, DISCOVERIES_ID}
    assert {i.name: i.size_bytes for i in v1.indices} == {
        "famous_scientists": 29033,
        "scientific_discoveries": 14140,
    }


@pytest.mark.asyncio
async def test_list_hides_non_successful_snapshots(repo):
    import json

    data = json.loads(repo["index-1"])
    data["snapshots"][1]["state"] = 2  # FAILED
    repo["index-1"] = json.dumps(data).encode()
    src = SnapshotSource(LOCATION, s3_client=FakeS3(repo))
    assert [s.name for s in await src.list_snapshots()] == ["scientists-v1"]
    failed = await src.describe_snapshot("scientists-v2")
    assert failed.state == "FAILED" and failed.index_metadata == {}


@pytest.mark.asyncio
async def test_describe_snapshot_decodes_metadata_and_sizes(source):
    detail = await source.describe_snapshot(SNAP_V1)
    meta = detail.index_metadata["scientific_discoveries"]
    assert (
        meta.settings["index.analysis.filter.field_synonyms.synonyms_path"]
        == "analysis/field_synonyms.txt"
    )
    assert detail.unreadable == {}
    sizes = {i.name: i.size_bytes for i in detail.indices}
    assert sizes == {"famous_scientists": 29033, "scientific_discoveries": 14140}


@pytest.mark.asyncio
async def test_describe_unknown_snapshot(source):
    with pytest.raises(SnapshotSourceError, match="not found"):
        await source.describe_snapshot("nope")


@pytest.mark.asyncio
async def test_unreadable_index_metadata_is_reported_not_raised(repo):
    key = f"indices/{DISCOVERIES_ID}/meta-6ga29KEBtovP9BVW74q8.dat"
    blob = bytearray(repo[key])
    blob[40] ^= 0xFF
    repo[key] = bytes(blob)
    detail = await SnapshotSource(LOCATION, s3_client=FakeS3(repo)).describe_snapshot(SNAP_V1)
    assert "scientific_discoveries" in detail.unreadable
    assert "famous_scientists" in detail.index_metadata
    with pytest.raises(SnapshotSourceError, match="unreadable"):
        await SnapshotSource(LOCATION, s3_client=FakeS3(repo)).build_manifest(
            SNAP_V1, ["scientific_discoveries"]
        )


@pytest.mark.asyncio
async def test_non_default_shard_layout_is_unreadable(repo):
    import json

    data = json.loads(repo["index-1"])
    data["indices"]["famous_scientists"]["shard_path_type"] = 1
    repo["index-1"] = json.dumps(data).encode()
    detail = await SnapshotSource(LOCATION, s3_client=FakeS3(repo)).describe_snapshot(SNAP_V1)
    assert detail.unreadable["famous_scientists"] == "unsupported repository shard layout"


# ------------------------------------------------------------------ manifest


@pytest.mark.asyncio
async def test_exact_manifest_for_one_index_excludes_the_other(source):
    manifest = await source.build_manifest(SNAP_V1, ["scientific_discoveries"])
    keys = [f.key for f in manifest.files]
    assert manifest.kind == "exact"
    assert manifest.repository_generation == 1
    assert manifest.snapshot_uuid == SNAP_V1_UUID
    assert not [k for k in keys if SCIENTISTS_ID in k]
    assert {
        "index.latest",
        "index-1",
        f"snap-{SNAP_V1_UUID}.dat",
        f"meta-{SNAP_V1_UUID}.dat",
        f"indices/{DISCOVERIES_ID}/meta-6ga29KEBtovP9BVW74q8.dat",
        f"indices/{DISCOVERIES_ID}/0/snap-{SNAP_V1_UUID}.dat",
        f"indices/{DISCOVERIES_ID}/0/index-DMXL46G9RZO5XRj8TDhwQg",
        f"indices/{DISCOVERIES_ID}/0/__gxVB6jhEQ96a0mi6_iF3Mw",
        f"indices/{DISCOVERIES_ID}/0/__sj_gSyrKQvuEq4lxHx6QHA",
    } == set(keys)
    # Other snapshot's files and the other meta blob are not needed.
    assert not any("lgP_s0XZTyuYVKz8W6II-Q" in k for k in keys)
    assert manifest.total_bytes == 19534
    by_key = {f.key: f for f in manifest.files}
    assert by_key[f"indices/{DISCOVERIES_ID}/0/__gxVB6jhEQ96a0mi6_iF3Mw"].crc32 == 2400043472
    assert by_key["index-1"].crc32 is None
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_manifest_for_both_indices_and_is_cached(source, fake):
    manifest = await source.build_manifest(
        SNAP_V1, ["famous_scientists", "scientific_discoveries", "famous_scientists"]
    )
    assert manifest.indices == ("famous_scientists", "scientific_discoveries")
    assert any(SCIENTISTS_ID in f.key for f in manifest.files)
    before = len([c for c in fake.calls if c[0] == "get"])
    await source.build_manifest(SNAP_V1, ["famous_scientists"])
    shard_snap_gets = [k for k in fake.get_keys()[before:] if "/snap-" in k]
    assert shard_snap_gets == []  # shard manifests reused from describe_snapshot


@pytest.mark.asyncio
async def test_manifest_rejects_unknown_index(source):
    with pytest.raises(SnapshotSourceError, match="not part of the snapshot"):
        await source.build_manifest(SNAP_V1, ["missing"])


@pytest.mark.asyncio
async def test_manifest_folder_fallback_when_shard_manifest_undecodable(repo):
    key = f"indices/{DISCOVERIES_ID}/0/snap-{SNAP_V1_UUID}.dat"
    repo[key] = repo[key][:50]
    src = SnapshotSource(LOCATION, s3_client=FakeS3(repo))
    manifest = await src.build_manifest(SNAP_V1, ["scientific_discoveries"])
    assert manifest.kind == "folder"
    keys = {f.key for f in manifest.files}
    # Everything under the index folder, including the second snapshot's files.
    assert f"indices/{DISCOVERIES_ID}/0/snap-lgP_s0XZTyuYVKz8W6II-Q.dat" in keys
    assert f"indices/{DISCOVERIES_ID}/meta-7QbF9KEBtovP9BVWEop_.dat" in keys
    assert not [k for k in keys if SCIENTISTS_ID in k]


@pytest.mark.asyncio
async def test_manifest_detects_missing_blob(repo):
    del repo[f"indices/{DISCOVERIES_ID}/0/__gxVB6jhEQ96a0mi6_iF3Mw"]
    src = SnapshotSource(LOCATION, s3_client=FakeS3(repo))
    with pytest.raises(SnapshotSourceError, match="incomplete"):
        await src.build_manifest(SNAP_V1, ["scientific_discoveries"])


@pytest.mark.asyncio
async def test_manifest_detects_size_mismatch(repo):
    repo[f"indices/{DISCOVERIES_ID}/0/__gxVB6jhEQ96a0mi6_iF3Mw"] += b"x"
    src = SnapshotSource(LOCATION, s3_client=FakeS3(repo))
    with pytest.raises(SnapshotSourceError, match="does not match"):
        await src.build_manifest(SNAP_V1, ["scientific_discoveries"])


@pytest.mark.asyncio
async def test_manifest_requires_root_files(repo):
    del repo[f"meta-{SNAP_V1_UUID}.dat"]
    src = SnapshotSource(LOCATION, s3_client=FakeS3(repo))
    with pytest.raises(SnapshotSourceError, match="incomplete"):
        await src.build_manifest(SNAP_V1, ["scientific_discoveries"])


@pytest.mark.asyncio
async def test_prefix_handling_variants(repo):
    fake = FakeS3(repo, prefix="a/b")
    src = SnapshotSource(S3Location(bucket=BUCKET, prefix="/a/b/"), s3_client=fake)
    assert await src.repository_generation() == 1
    root = FakeS3(repo, prefix="")
    assert (
        await SnapshotSource(S3Location(bucket=BUCKET), s3_client=root).repository_generation() == 1
    )


# ------------------------------------------------------------------ reading


@pytest.mark.asyncio
async def test_read_bytes_bounds_and_key_validation(source, repo):
    assert await source.read_bytes("index.latest", 16) == repo["index.latest"]
    with pytest.raises(SnapshotSourceError, match="larger"):
        await source.read_bytes("index-1", 10)
    for bad in ("../x", "indices/../../x", "/index.latest", "index.latest/", "other"):
        with pytest.raises(SnapshotSourceError, match="unsupported"):
            await source.read_bytes(bad, 100)
    with pytest.raises(SnapshotSourceError, match="not found"):
        await source.read_bytes("index-99", 100)


@pytest.mark.asyncio
async def test_stream_enforces_exact_size(source, fake, repo):
    key = f"indices/{DISCOVERIES_ID}/0/__sj_gSyrKQvuEq4lxHx6QHA"
    data = b"".join([c async for c in source.stream(key, 549)])
    assert data == repo[key]
    with pytest.raises(SnapshotSourceError, match="changed size"):
        _ = [c async for c in source.stream(key, 100)]
    fake.on_get = lambda k, d: d[:-5]  # truncated body but honest content length
    with pytest.raises(SnapshotSourceError):
        _ = [c async for c in source.stream(key, 549)]


@pytest.mark.asyncio
async def test_download_to_writes_new_file_only(source, tmp_path, repo):
    key = f"indices/{DISCOVERIES_ID}/0/__sj_gSyrKQvuEq4lxHx6QHA"
    dest = tmp_path / "blob"
    await source.download_to(key, dest, 549)
    assert dest.read_bytes() == repo[key]
    with pytest.raises(FileExistsError):
        await source.download_to(key, dest, 549)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "elsewhere")
    with pytest.raises((FileExistsError, OSError)):
        await source.download_to(key, link, 549)
    assert not (tmp_path / "elsewhere").exists()
    bad = tmp_path / "bad"
    with pytest.raises(SnapshotSourceError):
        await source.download_to(key, bad, 10)
    assert not bad.exists()


@pytest.mark.parametrize(
    "key",
    [
        "index.latest",
        "index-12",
        "snap-abc_DEF-1.dat",
        "meta-abc.dat",
        "indices/abc_1-2/meta-xyz.dat",
        "indices/abc/0/index-gen_1",
        "indices/abc/12/snap-u.dat",
        "indices/abc/0/__blob_1-2",
        "indices/abc/0/__blob.part3",
    ],
)
def test_valid_repo_keys(key):
    assert validate_repo_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../index.latest",
        "indices/../x",
        "indices/a/../../b",
        "indices/a/0/../../../x",
        "indices//meta-x.dat",
        "indices/a/0/__x/../y",
        "indices/a\\b/meta-x.dat",
        "/abs",
        "index.latest\n",
        "index-1\n",
        "indices/a/000000/index-x",
        "indices/a/0/__x.part",
        "indices/a/0/other",
        "indices/a/0/__" + "x" * 129,
        "indices/" + "a" * 65 + "/meta-x.dat",
        "indices/a/\u0660/index-x",
        "snap-x.dat.part",
        "meta-.dat",
        "indices/a/0/index-x/y",
        "index-1.part",
        "indices/a/0/__\u00e9",
    ],
)
def test_invalid_repo_keys(key):
    with pytest.raises(SnapshotSourceError):
        validate_repo_key(key)


# ------------------------------------------------------------------ request-time destination guard (B1)


class _Raw:
    def __init__(self, body: bytes):
        self._body = body

    def stream(self, *_args, **_kwargs):
        yield self._body


_LIST_XML = (
    b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
    b"<Name>b</Name><IsTruncated>false</IsTruncated></ListBucketResult>"
)
_ERROR_XML = b"<Error><Code>InternalError</Code><Message>boom</Message></Error>"


def _stub_transport(client, statuses=(200,), after=None):
    """Replace the HTTP send (after the endpoint guard) with canned responses; returns request URLs."""
    from botocore.awsrequest import AWSResponse

    urls: list[str] = []

    def respond(request, **_kwargs):
        urls.append(request.url)
        status = statuses[min(len(urls), len(statuses)) - 1]
        if after is not None:
            after(len(urls))
        return AWSResponse(
            request.url, status, {}, _Raw(_LIST_XML if status == 200 else _ERROR_XML)
        )

    client.meta.events.register("before-send", respond)
    return urls


@pytest.fixture
def dns(monkeypatch):
    """Controllable resolver: public until ``state['private']`` flips."""
    from connectors.opensearch_snapshot import endpoint_policy

    monkeypatch.delenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", raising=False)
    monkeypatch.delenv("OPENRAG_SNAPSHOT_REQUIRE_ENDPOINT_ALLOWLIST", raising=False)
    state = {"calls": 0, "private": False}

    def resolve(host, port):
        state["calls"] += 1
        return ["10.0.0.5"] if state["private"] else ["93.184.216.34"]

    monkeypatch.setattr(endpoint_policy, "_resolve", resolve)
    return state


def _custom_source(**over):
    location = S3Location(bucket="bkt", endpoint_url="http://storage.example.test:9000", **over)
    return SnapshotSource(location)


@pytest.mark.asyncio
async def test_public_endpoint_resolving_private_at_request_time_is_refused(dns):
    src = _custom_source()
    urls = _stub_transport(src._client)
    await src._call("the repository", src._client.list_objects_v2, Bucket="bkt")  # public: allowed
    assert len(urls) == 1
    dns["private"] = True  # DNS rebinding after the constructor-time check
    with pytest.raises(SnapshotSourceError, match="private or local"):
        await src._call("the repository", src._client.list_objects_v2, Bucket="bkt")
    assert len(urls) == 1  # the refused request never reached the transport


@pytest.mark.asyncio
async def test_request_time_blocked_range_is_refused_even_when_allowlisted(dns, monkeypatch):
    monkeypatch.setenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", "storage.example.test:9000")
    src = _custom_source()
    urls = _stub_transport(src._client)
    from connectors.opensearch_snapshot import endpoint_policy

    monkeypatch.setattr(endpoint_policy, "_resolve", lambda host, port: ["169.254.169.254"])
    with pytest.raises(SnapshotSourceError, match="blocked"):
        await src._call("the repository", src._client.list_objects_v2, Bucket="bkt")
    assert urls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path_style", [True, False])
async def test_custom_endpoint_is_always_path_style(dns, path_style):
    src = _custom_source(path_style=path_style)
    assert src._client.meta.config.s3["addressing_style"] == "path"
    urls = _stub_transport(src._client)
    await src._call("the repository", src._client.list_objects_v2, Bucket="bkt")
    # no ``bkt.storage.example.test`` virtual-host rewrite: the host stays the validated one
    assert urls[0].startswith("http://storage.example.test:9000/bkt")


@pytest.mark.asyncio
async def test_every_retry_attempt_is_checked_again(dns, monkeypatch):
    import botocore.endpoint

    monkeypatch.setattr(botocore.endpoint.time, "sleep", lambda _s: None)
    src = _custom_source()
    urls = _stub_transport(src._client, statuses=(500, 200))
    baseline = dns["calls"]
    await src._call("the repository", src._client.list_objects_v2, Bucket="bkt")
    assert len(urls) == 2 and dns["calls"] - baseline == 2  # one policy check per attempt

    # ...and a retry whose host turned private mid-flight is refused.
    src = _custom_source()

    def flip(attempt):
        dns["private"] = True

    urls = _stub_transport(src._client, statuses=(500, 200), after=flip)
    dns["private"] = False
    with pytest.raises(SnapshotSourceError, match="private or local"):
        await src._call("the repository", src._client.list_objects_v2, Bucket="bkt")
    assert len(urls) == 1


def test_guard_rejects_requests_for_any_other_host():
    from connectors.opensearch_snapshot.endpoint_policy import (
        EndpointPolicyError,
        check_request_destination,
    )

    check_request_destination("https://anything.example/x", None)  # AWS default: nothing to enforce
    for other in (
        "http://bkt.storage.example.test:9000/key",  # virtual-host rewrite
        "http://storage.example.test:9001/bkt",
        "https://storage.example.test:9000/bkt",
        "http://evil.example/bkt",
        "ftp://storage.example.test:9000/bkt",
    ):
        with pytest.raises(EndpointPolicyError, match="does not match|malformed"):
            check_request_destination(other, "http://storage.example.test:9000")


# ------------------------------------------------------------------ restored-size estimates (B7) and list sizes (E3)


@pytest.mark.asyncio
async def test_list_snapshots_reports_exact_index_sizes(source, fake):
    snaps = await source.list_snapshots()
    v1, v2 = snaps
    assert {i.name: i.size_bytes for i in v1.indices} == {
        "famous_scientists": 29033,
        "scientific_discoveries": 14140,
    }
    assert all(i.size_bytes > 0 for i in v2.indices)
    # the same numbers as the detailed view, and no second fetch of the shard manifests
    detail = await source.describe_snapshot(SNAP_V1)
    assert {i.name: i.size_bytes for i in detail.indices} == {
        i.name: i.size_bytes for i in v1.indices
    }
    snap_gets = [k for k in fake.get_keys() if "/0/snap-" in k]
    assert len(snap_gets) == len(set(snap_gets))


@pytest.mark.asyncio
async def test_list_snapshots_sizes_respect_the_fetch_budget(source, monkeypatch):
    from connectors.opensearch_snapshot import source as source_mod

    monkeypatch.setattr(source_mod, "_LIST_SIZE_SHARD_BUDGET", 2)
    v1, v2 = await source.list_snapshots()
    assert all(i.size_bytes > 0 for i in v1.indices)  # first snapshot fits the budget
    assert all(i.size_bytes == 0 for i in v2.indices)  # beyond it: unknown, never fetched


@pytest.mark.asyncio
async def test_list_snapshots_survives_unreadable_shard_manifest(repo):
    del repo[f"indices/{DISCOVERIES_ID}/0/snap-{SNAP_V1_UUID}.dat"]
    src = SnapshotSource(LOCATION, s3_client=FakeS3(repo))
    v1 = (await src.list_snapshots())[0]
    sizes = {i.name: i.size_bytes for i in v1.indices}
    assert sizes["scientific_discoveries"] == 0 and sizes["famous_scientists"] == 29033


@pytest.mark.asyncio
async def test_folder_fallback_estimates_restored_bytes_from_data_blobs(repo):
    """A shard manifest that is missing forces the folder copy; its data must still be budgeted."""
    del repo[f"indices/{DISCOVERIES_ID}/0/snap-{SNAP_V1_UUID}.dat"]
    src = SnapshotSource(LOCATION, s3_client=FakeS3(repo))
    detail = await src.describe_snapshot(SNAP_V1)
    assert {i.name: i.size_bytes for i in detail.indices}[
        "scientific_discoveries"
    ] == 0  # nothing decodable
    manifest = await src.build_manifest(SNAP_V1, ["famous_scientists", "scientific_discoveries"])
    assert manifest.kind == "folder"
    data_blobs = sum(
        len(v) for k, v in repo.items() if k.startswith(f"indices/{DISCOVERIES_ID}/0/__")
    )
    assert data_blobs > 0
    assert (
        manifest.restored_bytes("scientific_discoveries") == data_blobs
    )  # never 0 when data exists
    assert manifest.restored_bytes("famous_scientists") == 29033  # exact index keeps its exact size
    assert manifest.restored_bytes("unknown") is None


@pytest.mark.asyncio
async def test_exact_manifest_records_restored_bytes(source):
    manifest = await source.build_manifest(SNAP_V1, ["famous_scientists", "scientific_discoveries"])
    assert manifest.kind == "exact"
    assert dict(manifest.index_bytes) == {
        "famous_scientists": 29033,
        "scientific_discoveries": 14140,
    }


# ------------------------------------------------------------------ live fixture


def _minio_up() -> bool:
    try:
        with socket.create_connection(("localhost", 9100), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _minio_up(), reason="MinIO fixture on localhost:9100 is not running")
@pytest.mark.asyncio
async def test_live_minio_exact_manifest(monkeypatch):
    monkeypatch.setenv("OPENRAG_SNAPSHOT_ALLOWED_ENDPOINTS", "localhost:9100")
    src = SnapshotSource(
        S3Location(
            bucket="openrag-snapshots",
            prefix="scientists",
            endpoint_url="http://localhost:9100",
            access_key="snapshotadmin",
            secret_key="snapshotadmin123",
        )
    )
    await src.test_connection()
    manifest = await src.build_manifest("scientists-v1", ["scientific_discoveries"])
    assert manifest.kind == "exact"
    assert manifest.files
    assert all(DISCOVERIES_ID in f.key or "/" not in f.key for f in manifest.files)
    assert not [f for f in manifest.files if SCIENTISTS_ID in f.key]
    detail = await src.describe_snapshot("scientists-v1")
    meta = detail.index_metadata["scientific_discoveries"]
    assert (
        meta.settings["index.analysis.filter.field_synonyms.synonyms_path"]
        == "analysis/field_synonyms.txt"
    )
    assert (meta.created_version.major, meta.created_version.minor) == (3, 8)
