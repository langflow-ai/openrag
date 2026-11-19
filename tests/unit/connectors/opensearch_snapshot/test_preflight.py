from __future__ import annotations

import dataclasses
import json

import pytest

from connectors.opensearch_snapshot import preflight as pf
from connectors.opensearch_snapshot.metadata import Version
from connectors.opensearch_snapshot.preflight import AnalyserFileRef, run_preflight
from connectors.opensearch_snapshot.source import S3Location, SnapshotSource

from ._fakes import (
    BUCKET,
    PREFIX,
    SNAP_V1,
    SNAP_V1_UUID,
    ApiError,
    FakeOpenSearch,
    FakeS3,
    load_repo,
)

GB = 1024**3


class FakeStaging:
    kind = "fs"

    def __init__(self, free: int | None = 100 * GB):
        self.free = free

    def free_bytes(self):
        return self.free


def make_source(repo=None):
    return SnapshotSource(
        S3Location(bucket=BUCKET, prefix=PREFIX), s3_client=FakeS3(repo or load_repo())
    )


def healthy_cluster(
    version="3.8.0", total=100 * GB, available=80 * GB, roles=("data", "cluster_manager")
):
    os_admin = FakeOpenSearch()
    os_admin.version_number = version
    os_admin.nodes = {
        "n1": {
            "roles": list(roles),
            "fs": {"total": {"total_in_bytes": total, "available_in_bytes": available}},
        }
    }
    return os_admin


async def run(indices, *, source=None, os_admin=None, staging=None, snapshot=SNAP_V1, **kw):
    return await run_preflight(
        source or make_source(),
        snapshot,
        indices,
        os_admin=os_admin or healthy_cluster(),
        staging=staging or FakeStaging(),
        **kw,
    )


def codes(issues):
    return sorted(i.code for i in issues)


@pytest.mark.asyncio
async def test_happy_path_with_analyser_file_reference():
    result = await run(["famous_scientists", "scientific_discoveries"])
    assert result.ok and result.blockers == ()
    assert codes(result.warnings) == ["analyser_file_required"]
    assert result.analyser_files == (
        AnalyserFileRef(
            index="scientific_discoveries",
            setting="index.analysis.filter.field_synonyms.synonyms_path",
            path="analysis/field_synonyms.txt",
            inline_setting="index.analysis.filter.field_synonyms.synonyms",
        ),
    )
    assert result.written_by_version == "3.8.0" and result.snapshot_uuid == SNAP_V1_UUID
    assert result.restored_bytes == 29033 + 14140
    assert result.staged_bytes == result.manifest.total_bytes > result.restored_bytes
    assert [(i.name, i.created_version) for i in result.indices] == [
        ("famous_scientists", "3.8.0"),
        ("scientific_discoveries", "3.8.0"),
    ]


@pytest.mark.asyncio
async def test_only_selected_index_files_are_in_manifest():
    result = await run(["famous_scientists"])
    assert result.ok and result.analyser_files == () and result.warnings == ()
    assert all("PPA1PiDSRBKgmt_dh6Pgaw" not in f.key for f in result.manifest.files)


@pytest.mark.asyncio
async def test_index_selection_blockers():
    result = await run(["nope", ".kibana", "famous_scientists"])
    assert not result.ok and result.manifest is None
    by_code = {i.code: i.index for i in result.blockers}
    assert by_code == {"index_not_in_snapshot": "nope", "system_index": ".kibana"}
    empty = await run([])
    assert codes(empty.blockers) == ["index_not_in_snapshot"]


@pytest.mark.asyncio
async def test_snapshot_not_successful():
    repo = load_repo()
    data = json.loads(repo["index-1"])
    data["snapshots"][0]["state"] = 2
    repo["index-1"] = json.dumps(data).encode()
    result = await run(["famous_scientists"], source=make_source(repo))
    assert codes(result.blockers) == ["snapshot_not_successful"] and not result.ok


@pytest.mark.asyncio
async def test_partial_and_duplicate_warnings():
    repo = load_repo()
    data = json.loads(repo["index-1"])
    data["snapshots"][0]["state"] = 3
    repo["index-1"] = json.dumps(data).encode()
    result = await run(
        ["famous_scientists"], source=make_source(repo), existing_snapshot_uuids={SNAP_V1_UUID}
    )
    assert result.ok
    assert codes(result.warnings) == ["duplicate_snapshot", "partial_snapshot"]


@pytest.mark.asyncio
async def test_partial_snapshot_with_missing_shard_manifest_still_budgets_restored_bytes():
    """A PARTIAL snapshot whose shard manifest is gone is copied folder-wise; the cluster
    capacity check must see the folder's data, not 0 bytes (B7)."""
    repo = load_repo()
    data = json.loads(repo["index-1"])
    data["snapshots"][0]["state"] = 3
    repo["index-1"] = json.dumps(data).encode()
    del repo[f"indices/PPA1PiDSRBKgmt_dh6Pgaw/0/snap-{SNAP_V1_UUID}.dat"]
    folder_data = sum(
        len(v) for k, v in repo.items() if k.startswith("indices/PPA1PiDSRBKgmt_dh6Pgaw/0/__")
    )
    assert folder_data > 10_000
    tight = healthy_cluster(total=10_000_000, available=1_010_000)  # ~10 KB of headroom
    result = await run(["scientific_discoveries"], source=make_source(repo), os_admin=tight)
    assert result.manifest.kind == "folder"
    assert result.restored_bytes == folder_data == result.indices[0].size_bytes
    assert "insufficient_disk_cluster" in codes(result.blockers)
    roomy = await run(["scientific_discoveries"], source=make_source(repo))
    assert roomy.ok and roomy.restored_bytes == folder_data


@pytest.mark.asyncio
async def test_unreadable_metadata_blocks():
    repo = load_repo()
    key = "indices/PPA1PiDSRBKgmt_dh6Pgaw/meta-6ga29KEBtovP9BVW74q8.dat"
    repo[key] = repo[key][:-3]
    result = await run(["scientific_discoveries", "famous_scientists"], source=make_source(repo))
    assert [(i.code, i.index) for i in result.blockers] == [
        ("metadata_unreadable", "scientific_discoveries")
    ]
    assert result.manifest is None


@pytest.mark.asyncio
async def test_incomplete_repository_blocks_with_metadata_unreadable():
    repo = load_repo()
    del repo["indices/vQoty04XTbCKBAxXf9HqKQ/0/__Y5NdY_BhQ1Wec6_jofxQyg"]
    result = await run(["famous_scientists"], source=make_source(repo))
    assert codes(result.blockers) == ["metadata_unreadable"]


async def run_with_created(created: Version, cluster_version="3.8.0", writer="3.8.0"):
    source = make_source()
    detail = await source.describe_snapshot(SNAP_V1)
    meta = detail.index_metadata["famous_scientists"]
    patched = dataclasses.replace(
        detail,
        version=writer,
        index_metadata={"famous_scientists": dataclasses.replace(meta, created_version=created)},
    )

    class Wrapper:
        def __getattr__(self, name):
            return getattr(source, name)

        async def describe_snapshot(self, name):
            return patched

    return await run(
        ["famous_scientists"], source=Wrapper(), os_admin=healthy_cluster(version=cluster_version)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("created", "cluster", "ok"),
    [
        (Version("opensearch", 3, 8, 0), "3.8.0", True),
        (Version("opensearch", 2, 11, 1), "3.8.0", True),
        (Version("opensearch", 1, 3, 14), "3.8.0", False),  # written by 2.x but created by 1.x
        (Version("elasticsearch", 7, 10, 2), "3.8.0", False),
        (Version("elasticsearch", 8, 0, 0), "3.8.0", False),
        (
            Version("opensearch", 3, 9, 0),
            "3.8.0",
            True,
        ),  # created newer is caught by the writer check, not here
        (Version("opensearch", 1, 3, 0), "2.11.0", True),
        (Version("elasticsearch", 7, 10, 2), "1.3.0", True),
        (Version("elasticsearch", 7, 11, 0), "1.3.0", False),
    ],
)
async def test_created_version_compatibility(created, cluster, ok):
    result = await run_with_created(created, cluster_version=cluster, writer="1.0.0")
    assert ("version_incompatible" not in codes(result.blockers)) == ok


@pytest.mark.asyncio
async def test_snapshot_newer_than_cluster_uses_full_triple():
    newer_patch = await run_with_created(
        Version("opensearch", 3, 8, 0), cluster_version="3.8.0", writer="3.8.1"
    )
    assert "snapshot_newer_than_cluster" in codes(newer_patch.blockers)
    same = await run_with_created(
        Version("opensearch", 3, 8, 0), cluster_version="3.8.1", writer="3.8.1"
    )
    assert "snapshot_newer_than_cluster" not in codes(same.blockers)
    older = await run_with_created(
        Version("opensearch", 3, 8, 0), cluster_version="3.9.0", writer="3.8.1"
    )
    assert older.ok


@pytest.mark.asyncio
async def test_missing_privileges_is_a_blocker_and_other_errors_propagate():
    os_admin = healthy_cluster()
    os_admin.repo_error = ApiError(403, "no permissions")
    result = await run(["famous_scientists"], os_admin=os_admin)
    assert "missing_privileges" in codes(result.blockers) and not result.ok
    os_admin.repo_error = ApiError(500, "boom")
    with pytest.raises(ApiError):
        await run(["famous_scientists"], os_admin=os_admin)


@pytest.mark.asyncio
async def test_too_large_uses_configured_limit(monkeypatch):
    monkeypatch.setenv("OPENRAG_SNAPSHOT_MAX_IMPORT_BYTES", "1000")
    result = await run(["famous_scientists"])
    assert "too_large" in codes(result.blockers)
    ok = await run(["famous_scientists"], max_import_bytes=10 * GB)
    assert "too_large" not in codes(ok.blockers)


@pytest.mark.asyncio
async def test_staging_disk_check():
    result = await run(["famous_scientists"], staging=FakeStaging(free=100))
    assert "insufficient_disk_staging" in codes(result.blockers)
    unknown = await run(["famous_scientists"], staging=FakeStaging(free=None))
    assert unknown.ok


@pytest.mark.asyncio
async def test_unsupported_analyser_file_blocks():
    source = make_source()
    detail = await source.describe_snapshot(SNAP_V1)
    meta = detail.index_metadata["famous_scientists"]
    settings = dict(meta.settings)
    settings["index.analysis.filter.h.dictionary_path"] = "analysis/en.dic"
    settings["index.analysis.filter.h.type"] = "hunspell"
    patched = dataclasses.replace(
        detail, index_metadata={"famous_scientists": dataclasses.replace(meta, settings=settings)}
    )

    class Wrapper:
        def __getattr__(self, name):
            return getattr(source, name)

        async def describe_snapshot(self, name):
            return patched

    result = await run(["famous_scientists"], source=Wrapper())
    assert [(i.code, i.index) for i in result.blockers] == [
        ("unsupported_analyser_file", "famous_scientists")
    ]


def test_analyser_refs_cover_every_supported_setting():
    settings = {
        "index.analysis.filter.a.synonyms_path": "s.txt",
        "index.analysis.filter.b.stopwords_path": "stop.txt",
        "index.analysis.filter.c.keywords_path": "k.txt",
        "index.analysis.filter.d.articles_path": "art.txt",
        "index.analysis.filter.e.word_list_path": "wl.txt",
        "index.analysis.analyzer.f.stopwords_path": "stop2.txt",
        "index.refresh_interval": "1s",
        "index.other_path": "ignored",  # not an analysis setting
    }
    refs, issues = pf.analyser_refs("idx", settings)
    assert issues == []
    assert {(r.setting.rsplit(".", 1)[1], r.inline_setting.rsplit(".", 1)[1]) for r in refs} == {
        ("synonyms_path", "synonyms"),
        ("stopwords_path", "stopwords"),
        ("keywords_path", "keywords"),
        ("articles_path", "articles"),
        ("word_list_path", "word_list"),
    }
    assert len(refs) == 6
    refs, issues = pf.analyser_refs(
        "idx", {"index.analysis.filter.g.synonyms_path": ["not", "a", "string"]}
    )
    assert refs == [] and issues[0].code == "unsupported_analyser_file"


# ------------------------------------------------------------------ cluster disk


@pytest.mark.asyncio
async def test_cluster_disk_watermark_headroom():
    # 100 GB node, 85 GB used -> 5 GB of headroom below the default 90 % watermark.
    roomy = healthy_cluster(total=100 * GB, available=15 * GB)
    assert "insufficient_disk_cluster" not in codes(
        (await run(["famous_scientists"], os_admin=roomy)).blockers
    )
    # ~10 KB of headroom, restore needs ~29 KB.
    tight = healthy_cluster(total=10_000_000, available=1_010_000)
    result = await run(["famous_scientists"], os_admin=tight)
    assert "insufficient_disk_cluster" in codes(result.blockers)
    assert "previous generation" not in result.blockers[0].message
    note = await run(["famous_scientists"], os_admin=tight, replaced_bytes=1000)
    assert (
        "previous generation"
        in next(i for i in note.blockers if i.code == "insufficient_disk_cluster").message
    )


@pytest.mark.asyncio
async def test_cluster_disk_honours_custom_watermarks_and_disabled_threshold():
    os_admin = healthy_cluster(total=10_000_000, available=800_000)  # 92 % used
    blocked = lambda: run(["famous_scientists"], os_admin=os_admin)  # noqa: E731
    assert "insufficient_disk_cluster" in codes((await blocked()).blockers)
    os_admin.cluster_settings = {
        "persistent": {"cluster.routing.allocation.disk.watermark.high": "95%"},
        "defaults": {},
    }
    assert "insufficient_disk_cluster" not in codes((await blocked()).blockers)
    os_admin.cluster_settings = {
        "transient": {"cluster.routing.allocation.disk.watermark.high": "10gb"},
        "defaults": {},
    }
    assert "insufficient_disk_cluster" in codes((await blocked()).blockers)  # absolute min-free
    os_admin.cluster_settings = {
        "persistent": {"cluster.routing.allocation.disk.threshold_enabled": "false"},
        "defaults": {},
    }
    assert "insufficient_disk_cluster" not in codes((await blocked()).blockers)
    os_admin.cluster_settings = {
        "defaults": {"cluster.routing.allocation.disk.watermark.high": "0.85"}
    }
    assert "insufficient_disk_cluster" in codes((await blocked()).blockers)
    os_admin.cluster_settings = {
        "defaults": {"cluster.routing.allocation.disk.watermark.high": "banana"}
    }
    assert "disk_stats_unavailable" in codes((await blocked()).warnings)


@pytest.mark.asyncio
async def test_cluster_disk_ignores_non_data_nodes_and_counts_replicas(monkeypatch):
    os_admin = healthy_cluster(total=1_000_000, available=100_000, roles=("cluster_manager",))
    result = await run(["famous_scientists"], os_admin=os_admin)
    assert "disk_stats_unavailable" in codes(result.warnings)  # no data node at all

    monkeypatch.setattr(pf.app_settings, "OPENSEARCH_NUMBER_OF_REPLICAS", 2)
    # One data node with 40 KB of headroom: replicas cannot be placed, one ~29 KB copy fits.
    os_admin = healthy_cluster(total=1_000_000, available=140_000)
    assert "insufficient_disk_cluster" not in codes(
        (await run(["famous_scientists"], os_admin=os_admin)).blockers
    )
    # Two nodes with 20 KB each: two copies (~58 KB) do not fit in the 40 KB aggregate.
    node = {
        "roles": ["data"],
        "fs": {"total": {"total_in_bytes": 1_000_000, "available_in_bytes": 120_000}},
    }
    os_admin.nodes = {"a": node, "b": dict(node)}
    assert "insufficient_disk_cluster" in codes(
        (await run(["famous_scientists"], os_admin=os_admin)).blockers
    )


@pytest.mark.asyncio
async def test_unknown_disk_stats_is_only_a_warning():
    os_admin = healthy_cluster()
    os_admin.stats_error = ApiError(500)
    result = await run(["famous_scientists"], os_admin=os_admin)
    assert result.ok and codes(result.warnings) == ["disk_stats_unavailable"]
    os_admin = healthy_cluster()
    os_admin.nodes = {"n": {"roles": ["data"], "fs": {}}}
    assert codes((await run(["famous_scientists"], os_admin=os_admin)).warnings) == [
        "disk_stats_unavailable"
    ]
