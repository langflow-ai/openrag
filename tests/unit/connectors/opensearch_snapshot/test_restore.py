from __future__ import annotations

import pytest

from connectors.opensearch_snapshot import restore as rs
from connectors.opensearch_snapshot.preflight import AnalyserFileRef
from connectors.opensearch_snapshot.restore import AnalyserFileError, RestoreError

from ._fakes import ApiError, FakeOpenSearch

SYN_PATH = "index.analysis.filter.field_synonyms.synonyms_path"
SYN_INLINE = "index.analysis.filter.field_synonyms.synonyms"
REF = AnalyserFileRef("scientific_discoveries", SYN_PATH, "analysis/field_synonyms.txt", SYN_INLINE)
CONCRETE = "ds_abcdefghij_1_g1"


@pytest.fixture(autouse=True)
def _replicas(monkeypatch):
    monkeypatch.setattr(rs.app_settings, "OPENSEARCH_NUMBER_OF_REPLICAS", 1)


# ------------------------------------------------------------------ analyser files


def test_parse_analyser_file_strips_comments_and_blanks():
    content = (
        "# header\n\n  dna, deoxyribonucleic acid  \n#another\r\nrna => ribonucleic acid\n   \n"
    )
    assert rs.parse_analyser_file(content, 1000) == [
        "dna, deoxyribonucleic acid",
        "rna => ribonucleic acid",
    ]
    assert rs.parse_analyser_file(content.encode(), 1000)[0] == "dna, deoxyribonucleic acid"
    assert rs.parse_analyser_file("", 10) == []


@pytest.mark.parametrize(
    "content",
    ["x" * 11, b"\xff\xfe\x00bad", "a\x00b"],
)
def test_parse_analyser_file_rejects(content):
    with pytest.raises(AnalyserFileError):
        rs.parse_analyser_file(content, 10)


def test_parse_analyser_file_line_bound():
    ok = "\n".join(f"w{i}" for i in range(rs.MAX_ANALYSER_LINES))
    assert len(rs.parse_analyser_file(ok, 10_000_000)) == rs.MAX_ANALYSER_LINES
    with pytest.raises(AnalyserFileError, match="too many lines"):
        rs.parse_analyser_file(ok + "\nextra", 10_000_000)


def test_build_analyser_inlines_requires_exact_match():
    good = [{"index": "scientific_discoveries", "setting": SYN_PATH, "content": "a, b\n# c"}]
    assert rs.build_analyser_inlines([REF], good, 100) == {
        "scientific_discoveries": {SYN_INLINE: ["a, b"]}
    }
    assert rs.build_analyser_inlines([], [], 100) == {}
    with pytest.raises(AnalyserFileError, match="required analyser file was not provided"):
        rs.build_analyser_inlines([REF], [], 100)
    with pytest.raises(AnalyserFileError, match="does not match"):  # forged index
        rs.build_analyser_inlines([REF], [{**good[0], "index": "documents"}], 100)
    with pytest.raises(AnalyserFileError, match="does not match"):  # forged setting
        rs.build_analyser_inlines([REF], [{**good[0], "setting": "index.blocks.read_only"}], 100)
    with pytest.raises(AnalyserFileError, match="more than once"):
        rs.build_analyser_inlines([REF], good + good, 100)
    with pytest.raises(AnalyserFileError, match="does not match"):  # extra
        rs.build_analyser_inlines([], good, 100)
    with pytest.raises(AnalyserFileError, match="need index"):
        rs.build_analyser_inlines([REF], [{"index": "x"}], 100)
    with pytest.raises(AnalyserFileError, match="too large"):
        rs.build_analyser_inlines([REF], [{**good[0], "content": "x" * 500}], 100)


# ------------------------------------------------------------------ restore body


def test_restore_body_fixed_fields_and_replicas():
    body = rs.restore_body(source_index="famous_scientists", concrete_index=CONCRETE)
    assert body == {
        "indices": ["famous_scientists"],
        "ignore_unavailable": False,
        "include_global_state": False,
        "include_aliases": False,
        "rename_pattern": "^(.+)$",
        "rename_replacement": CONCRETE,
        "index_settings": {"index.number_of_replicas": 1, "index.blocks.write": True},
        "ignore_index_settings": ["index.blocks.*"],
    }


def test_restore_body_drops_every_source_block_and_keeps_the_dataset_write_blocked():
    """A flood-stage ``read_only_allow_delete`` captured in the snapshot must not survive the restore;
    only ``index.blocks.write`` (immutable dataset) is set. Verified against OpenSearch 3.8: the
    wildcard ignore removes inherited blocks, the override survives, and alias updates, search,
    settings updates and index deletion still work with the write block."""
    body = rs.restore_body(source_index="a", concrete_index=CONCRETE)
    assert "index.blocks.*" in body["ignore_index_settings"]
    blocks = {k: v for k, v in body["index_settings"].items() if k.startswith("index.blocks.")}
    assert blocks == {"index.blocks.write": True}
    assert (
        "partial" not in body
        and rs.restore_body(source_index="a", concrete_index=CONCRETE, partial=True)["partial"]
        is True
    )


@pytest.mark.parametrize(
    ("configured", "data_nodes", "expected"),
    [(2, 1, 0), (2, 2, 1), (2, 3, 2), (2, 9, 2), (0, 5, 0), (2, None, 2), (1, 0, 0)],
)
def test_restore_body_caps_replicas_at_data_nodes_minus_one(
    monkeypatch, configured, data_nodes, expected
):
    monkeypatch.setattr(rs.app_settings, "OPENSEARCH_NUMBER_OF_REPLICAS", configured)
    body = rs.restore_body(source_index="a", concrete_index=CONCRETE, data_nodes=data_nodes)
    assert body["index_settings"]["index.number_of_replicas"] == expected


def test_restore_body_inlines_analyser_lines_and_derives_ignore_settings():
    body = rs.restore_body(
        source_index="scientific_discoveries",
        concrete_index=CONCRETE,
        analyser_inlines={SYN_INLINE: ["dna, deoxyribonucleic acid"]},
    )
    assert body["index_settings"][SYN_INLINE] == ["dna, deoxyribonucleic acid"]
    assert body["ignore_index_settings"] == [SYN_PATH, rs._BLOCKS_PATTERN]
    assert body["include_global_state"] is False and body["include_aliases"] is False


@pytest.mark.parametrize(
    "inline",
    [
        "index.blocks.read_only",
        "index.analysis.filter.x.type",
        "cluster.synonyms",
        "index.analysis.filter.x.hyphenation_patterns_path",
        "synonyms",
    ],
)
def test_restore_body_rejects_unsupported_inline_keys(inline):
    with pytest.raises(ValueError):
        rs.restore_body(source_index="i", concrete_index=CONCRETE, analyser_inlines={inline: ["x"]})


@pytest.mark.parametrize("name", ["a,b", "*", "a*", "-x", "_all", "a b", "a/b", "", "a#b", "a?"])
def test_restore_body_rejects_unsafe_source_names(name):
    with pytest.raises(ValueError):
        rs.restore_body(source_index=name, concrete_index=CONCRETE)


@pytest.mark.parametrize(
    "name",
    [
        "documents",
        "ds_abc_1_g1",
        "ds_abcdefghij_1",
        "ds_abcdefghij_1_g1,documents",
        "ds_abcdefghij_x_g1",
    ],
)
def test_restore_body_rejects_foreign_target_names(name):
    with pytest.raises(ValueError):
        rs.restore_body(source_index="i", concrete_index=name)


# ------------------------------------------------------------------ restore_index


async def restore(os_admin, **kw):
    return await rs.restore_index(
        os_admin,
        repository="openrag_stage_abcdefghij_g1",
        snapshot="scientists-v1",
        source_index="famous_scientists",
        concrete_index=CONCRETE,
        poll_s=0,
        **kw,
    )


@pytest.mark.asyncio
async def test_restore_waits_for_green_and_counts_docs():
    os_admin = FakeOpenSearch()
    os_admin.health_sequence = [
        {"status": "red", "initializing_shards": 1, "unassigned_shards": 0},
        {"status": "yellow", "initializing_shards": 1, "unassigned_shards": 0},
        {"status": "green"},
    ]
    result = await restore(os_admin)
    assert (result.concrete_index, result.doc_count, result.health) == (CONCRETE, 7, "green")
    name, kw = next(c for c in os_admin.calls if c[0] == "restore")
    assert kw["repository"] == "openrag_stage_abcdefghij_g1" and kw["snapshot"] == "scientists-v1"
    assert kw["wait_for_completion"] is False
    assert kw["body"]["rename_replacement"] == CONCRETE
    assert ("count", {"index": CONCRETE}) in os_admin.calls


@pytest.mark.asyncio
async def test_restore_accepts_stable_yellow_when_replicas_configured():
    os_admin = FakeOpenSearch()
    os_admin.health_sequence = [{"status": "yellow", "unassigned_shards": 1}]
    assert (await restore(os_admin)).health == "yellow"


@pytest.mark.asyncio
async def test_restore_caps_replicas_to_the_data_nodes_and_goes_green_on_one_node(monkeypatch):
    monkeypatch.setattr(rs.app_settings, "OPENSEARCH_NUMBER_OF_REPLICAS", 2)
    os_admin = FakeOpenSearch()
    os_admin.cat_nodes_rows = [{"node.role": "dimr"}]
    os_admin.health_sequence = [{"status": "green"}]
    result = await restore(os_admin)
    assert result.health == "green"
    body = next(c for c in os_admin.calls if c[0] == "restore")[1]["body"]
    assert body["index_settings"]["index.number_of_replicas"] == 0
    assert next(c for c in os_admin.calls if c[0] == "cat_nodes")[1]["h"] == "node.role"


@pytest.mark.asyncio
async def test_restore_does_not_accept_yellow_when_no_replica_was_requested(monkeypatch):
    """Yellow is only 'healthy' when replicas exist that cannot be placed; with 0 replicas it is not."""
    monkeypatch.setattr(rs.app_settings, "OPENSEARCH_NUMBER_OF_REPLICAS", 2)
    os_admin = FakeOpenSearch()
    os_admin.cat_nodes_rows = [{"node.role": "dimr"}]
    os_admin.health_sequence = [{"status": "yellow", "unassigned_shards": 1}]
    with pytest.raises(RestoreError, match="timed out"):
        await restore(os_admin, timeout_s=0.05)


@pytest.mark.asyncio
async def test_restore_still_accepts_stable_yellow_when_replicas_remain_unplaceable(monkeypatch):
    monkeypatch.setattr(rs.app_settings, "OPENSEARCH_NUMBER_OF_REPLICAS", 2)
    os_admin = FakeOpenSearch()
    os_admin.cat_nodes_rows = [
        {"node.role": "dimr"},
        {"node.role": "dir"},
        {"node.role": "m"},
    ]  # 2 data nodes
    os_admin.health_sequence = [{"status": "yellow", "unassigned_shards": 1}]
    assert (await restore(os_admin)).health == "yellow"
    body = next(c for c in os_admin.calls if c[0] == "restore")[1]["body"]
    assert body["index_settings"]["index.number_of_replicas"] == 1


@pytest.mark.asyncio
async def test_restore_falls_back_to_configured_replicas_when_nodes_are_unknown():
    os_admin = FakeOpenSearch()
    os_admin.cat_nodes_error = ApiError(403, "forbidden")
    await restore(os_admin)
    body = next(c for c in os_admin.calls if c[0] == "restore")[1]["body"]
    assert body["index_settings"]["index.number_of_replicas"] == 1


@pytest.mark.asyncio
async def test_restore_red_reports_allocation_reason():
    os_admin = FakeOpenSearch()
    os_admin.health_sequence = [{"status": "red", "initializing_shards": 0, "unassigned_shards": 1}]
    os_admin.explain = {
        "unassigned_info": {
            "reason": "ALLOCATION_FAILED",
            "details": "failed shard on node: Failed to build analyzers: [discovery_search]",
        }
    }
    with pytest.raises(RestoreError, match="Failed to build analyzers"):
        await restore(os_admin)
    explain = next(c for c in os_admin.calls if c[0] == "allocation_explain")[1]
    assert explain["body"]["index"] == CONCRETE


@pytest.mark.asyncio
async def test_restore_red_while_initializing_is_not_failure():
    os_admin = FakeOpenSearch()
    os_admin.health_sequence = [
        {"status": "red", "initializing_shards": 1, "unassigned_shards": 1}
    ] * 5 + [{"status": "green"}]
    assert (await restore(os_admin)).health == "green"


@pytest.mark.asyncio
async def test_restore_times_out():
    os_admin = FakeOpenSearch()
    os_admin.health_sequence = [{"status": "red", "initializing_shards": 1}]
    with pytest.raises(RestoreError, match="timed out"):
        await restore(os_admin, timeout_s=0.01)


@pytest.mark.asyncio
async def test_restore_api_error_becomes_restore_error():
    os_admin = FakeOpenSearch()
    os_admin.restore_error = ApiError(500, "[repo:snap] index [x] is missing")
    with pytest.raises(RestoreError, match="is missing"):
        await restore(os_admin)
    assert not [c for c in os_admin.calls if c[0] == "health"]


@pytest.mark.asyncio
async def test_restore_waits_for_index_to_appear_then_fails_if_it_never_does(monkeypatch):
    os_admin = FakeOpenSearch()
    os_admin.health_error = ApiError(404, "no such index")
    with pytest.raises(RestoreError, match="did not appear"):
        await restore(os_admin, timeout_s=30)
    os_admin.health_error = ApiError(503, "unavailable")
    with pytest.raises(RestoreError, match="unavailable"):
        await restore(os_admin)


# ------------------------------------------------------------------ publish / delete


@pytest.mark.asyncio
async def test_publish_aliases_is_a_single_atomic_request():
    os_admin = FakeOpenSearch()
    await rs.publish_aliases(
        os_admin,
        [
            ("ds_abcdefghij_0", "ds_abcdefghij_0_g2", "ds_abcdefghij_0_g1"),
            ("ds_abcdefghij_1", "ds_abcdefghij_1_g2", None),
        ],
    )
    calls = [c for c in os_admin.calls if c[0] == "update_aliases"]
    assert len(calls) == 1
    assert calls[0][1]["body"]["actions"] == [
        {"remove": {"index": "ds_abcdefghij_0_g1", "alias": "ds_abcdefghij_0"}},
        {"add": {"index": "ds_abcdefghij_0_g2", "alias": "ds_abcdefghij_0"}},
        {"add": {"index": "ds_abcdefghij_1_g2", "alias": "ds_abcdefghij_1"}},
    ]
    await rs.publish_aliases(os_admin, [])
    assert len([c for c in os_admin.calls if c[0] == "update_aliases"]) == 1


@pytest.mark.asyncio
async def test_publish_aliases_refuses_foreign_indices_and_wraps_errors():
    os_admin = FakeOpenSearch()
    with pytest.raises(ValueError):
        await rs.publish_aliases(os_admin, [("documents", "ds_abcdefghij_0_g1", None)])
    with pytest.raises(ValueError):
        await rs.publish_aliases(os_admin, [("ds_abcdefghij_0", "ds_abcdefghij_0_g1", "documents")])
    assert not os_admin.calls

    async def boom(**kw):
        raise ApiError(400, "alias conflict")

    os_admin.indices.update_aliases = boom
    with pytest.raises(RestoreError, match="alias conflict"):
        await rs.publish_aliases(os_admin, [("ds_abcdefghij_0", "ds_abcdefghij_0_g1", None)])


@pytest.mark.asyncio
async def test_delete_indices_exact_names_only():
    os_admin = FakeOpenSearch()
    await rs.delete_indices(
        os_admin, ["ds_abcdefghij_0_g1", "ds_abcdefghij_1_g1", "ds_abcdefghij_0_g1"]
    )
    assert os_admin.calls == [
        (
            "indices_delete",
            {"index": "ds_abcdefghij_0_g1,ds_abcdefghij_1_g1", "ignore_unavailable": True},
        )
    ]
    for bad in (["documents"], ["ds_*"], ["ds_a,documents"], ["_all"], ["*"]):
        with pytest.raises(ValueError):
            await rs.delete_indices(os_admin, bad)
    before = len(os_admin.calls)
    await rs.delete_indices(os_admin, [])
    assert len(os_admin.calls) == before

    async def gone(**kw):
        raise ApiError(404, "missing")

    os_admin.indices.delete = gone
    await rs.delete_indices(os_admin, ["ds_abcdefghij_0_g1"])  # 404 tolerated

    async def denied(**kw):
        raise ApiError(403, "forbidden")

    os_admin.indices.delete = denied
    with pytest.raises(RestoreError, match="forbidden"):
        await rs.delete_indices(os_admin, ["ds_abcdefghij_0_g1"])


@pytest.mark.asyncio
async def test_delete_indices_for_slug_keeps_requested_generation():
    os_admin = FakeOpenSearch()
    os_admin.cat_rows = [
        {"index": "ds_abcdefghij_0_g1"},
        {"index": "ds_abcdefghij_0_g2"},
        {"index": "ds_abcdefghij_1_g2"},
    ]
    deleted = await rs.delete_indices_for_slug(
        os_admin, "abcdefghij", keep={"ds_abcdefghij_0_g2", "ds_abcdefghij_1_g2"}
    )
    assert deleted == ["ds_abcdefghij_0_g1"]
    cat = next(c for c in os_admin.calls if c[0] == "cat_indices")[1]
    assert cat["index"] == "ds_abcdefghij_*"
    assert os_admin.calls[-1] == (
        "indices_delete",
        {"index": "ds_abcdefghij_0_g1", "ignore_unavailable": True},
    )
    with pytest.raises(ValueError):
        await rs.delete_indices_for_slug(os_admin, "x*")

    async def missing(**kw):
        raise ApiError(404, "none")

    os_admin.cat.indices = missing
    assert await rs.delete_indices_for_slug(os_admin, "abcdefghij") == []


@pytest.mark.asyncio
async def test_repository_register_and_delete_are_404_tolerant():
    os_admin = FakeOpenSearch()
    body = {"type": "fs", "settings": {"location": "/x", "readonly": True}}
    await rs.register_repository(os_admin, "repo1", body)
    assert os_admin.calls[-1] == ("create_repository", {"repository": "repo1", "body": body})
    await rs.delete_repository(os_admin, "repo1")
    os_admin.repo_error = ApiError(404, "repository_missing_exception")
    await rs.delete_repository(os_admin, "repo1")
    os_admin.repo_error = ApiError(500, "kaput")
    with pytest.raises(RestoreError, match="kaput"):
        await rs.delete_repository(os_admin, "repo1")

    async def invalid(**kw):
        raise ApiError(400, "path is not accessible on master node")

    os_admin.snapshot.create_repository = invalid
    with pytest.raises(RestoreError, match="not accessible"):
        await rs.register_repository(os_admin, "repo1", body)


@pytest.mark.asyncio
async def test_index_mapping_and_samples():
    os_admin = FakeOpenSearch()
    os_admin.mapping = {
        "ds_abcdefghij_0_g1": {"mappings": {"properties": {"title": {"type": "text"}}}}
    }
    os_admin.hits = [{"_source": {"title": "a"}}, {"_id": "no-source"}, {"_source": {"title": "b"}}]
    mappings, samples = await rs.index_mapping_and_samples(os_admin, "ds_abcdefghij_0", n=2)
    assert mappings == {"properties": {"title": {"type": "text"}}}
    assert samples == [{"title": "a"}, {"title": "b"}]
    search = next(c for c in os_admin.calls if c[0] == "search")[1]
    assert search["body"]["size"] == 2 and search["index"] == "ds_abcdefghij_0"
