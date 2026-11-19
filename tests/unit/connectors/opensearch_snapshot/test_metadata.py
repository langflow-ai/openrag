from __future__ import annotations

import json
import struct
import zlib

import pytest

from connectors.opensearch_snapshot import metadata as md
from connectors.opensearch_snapshot.metadata import MetadataFormatError

from ._fakes import DISCOVERIES_ID, FIXTURES, REPO_DIR, SNAP_V1_UUID

DISCOVERIES_META = (FIXTURES / "scientific_discoveries_meta.dat").read_bytes()
SCIENTISTS_META = (FIXTURES / "famous_scientists_meta.dat").read_bytes()
SHARD_SNAP = (REPO_DIR / "indices" / DISCOVERIES_ID / "0" / f"snap-{SNAP_V1_UUID}.dat").read_bytes()


# ---------------------------------------------------------------- test-only encoders


def codec_frame(codec: str, body: bytes, version: int = 1) -> bytes:
    head = (
        struct.pack(">I", md.CODEC_MAGIC)
        + bytes([len(codec)])
        + codec.encode()
        + struct.pack(">i", version)
    )
    pre = head + body + struct.pack(">Ii", md.FOOTER_MAGIC, 0)
    return pre + struct.pack(">Q", zlib.crc32(pre))


def _vint(n: int) -> bytes:
    """SMILE vint: 7-bit groups MSB first, last byte has bit 7 set and 6 data bits."""
    out = [0x80 | (n & 0x3F)]
    n >>= 6
    while n:
        out.append(n & 0x7F)
        n >>= 7
    return bytes(reversed(out))


def _zigzag(n: int) -> int:
    return (n << 1) ^ (n >> 63)


class SmileEncoder:
    """Test-only SMILE writer with shared key/value tables (flags 0x03 | raw binary 0x04)."""

    def __init__(self, raw_binary: bool = True):
        self.raw = raw_binary
        self.keys: list[str] = []
        self.values: list[str] = []
        self.out = bytearray(b":)\n" + bytes([0x03 | (0x04 if raw_binary else 0)]))

    def key(self, name: str) -> None:
        if name == "":
            self.out.append(0x20)
            return
        if name in self.keys:
            idx = self.keys.index(name)
            if idx < 64:
                self.out.append(0x40 + idx)
            else:
                self.out += bytes([0x30 | (idx >> 8), idx & 0xFF])
            return
        raw = name.encode()
        if len(raw) <= 64:
            if raw.isascii():
                self.out.append(0x80 + len(raw) - 1)
            else:
                self.out.append(0xC0 + len(raw) - 2)
            self.out += raw
        else:
            self.out += b"\x34" + raw + b"\xfc"
        self._remember(
            self.keys, name
        )  # long names are shared too (Jackson SmileGenerator._addSeenName)

    @staticmethod
    def _remember(table: list[str], item: str) -> None:
        if len(table) >= 1024:  # a full table restarts from empty
            table.clear()
        table.append(item)

    def value(self, v) -> None:  # noqa: C901
        o = self.out
        if v is None:
            o.append(0x21)
        elif v is True:
            o.append(0x23)
        elif v is False:
            o.append(0x22)
        elif isinstance(v, int):
            if -16 <= v <= 15:
                o.append(0xC0 + _zigzag(v))
            elif -(2**31) <= v < 2**31:
                o.append(0x24)
                o += _vint(_zigzag(v) & 0xFFFFFFFF)
            elif -(2**63) <= v < 2**63:
                o.append(0x25)
                o += _vint(_zigzag(v) & (2**64 - 1))
            else:
                o.append(0x26)
                raw = v.to_bytes((v.bit_length() + 8) // 8, "big", signed=True)
                o += _vint(len(raw)) + raw
        elif isinstance(v, float):
            o.append(0x29)
            bits = int.from_bytes(struct.pack(">d", v), "big")
            o += bytes(((bits >> (7 * i)) & 0x7F) for i in reversed(range(10)))
        elif isinstance(v, bytes):
            if self.raw:
                o.append(0xFD)
                o += _vint(len(v)) + v
            else:
                o.append(0xE8)
                o += _vint(len(v)) + self._pack7(v)
        elif isinstance(v, str):
            self._string(v)
        elif isinstance(v, list):
            o.append(0xF8)
            for item in v:
                self.value(item)
            o.append(0xF9)
        elif isinstance(v, dict):
            o.append(0xFA)
            for k, item in v.items():
                self.key(k)
                self.value(item)
            o.append(0xFB)
        else:  # pragma: no cover
            raise TypeError(type(v))

    def _string(self, s: str) -> None:
        o = self.out
        if s == "":
            o.append(0x20)
            return
        raw = s.encode()
        if s in self.values:
            idx = self.values.index(s)
            if idx < 31:
                o.append(1 + idx)
            else:
                o += bytes([0xEC | (idx >> 8), idx & 0xFF])
            return
        if len(raw) <= 64:
            self._remember(self.values, s)
            if raw.isascii():
                o.append((0x40 + len(raw) - 1) if len(raw) <= 32 else (0x60 + len(raw) - 33))
            else:
                o.append((0x80 + len(raw) - 2) if len(raw) <= 33 else (0xA0 + len(raw) - 34))
            o += raw
        else:
            o.append(0xE0 if raw.isascii() else 0xE4)
            o += raw + b"\xfc"

    @staticmethod
    def _pack7(data: bytes) -> bytes:
        bits = "".join(f"{b:08b}" for b in data)
        out = bytearray()
        for i in range(0, len(bits), 7):
            chunk = bits[i : i + 7]
            out.append(int(chunk, 2))  # trailing partial group is right-aligned (low bits)
        return bytes(out)

    def dump(self, v) -> bytes:
        self.value(v)
        return bytes(self.out)


def dfl(payload: bytes) -> bytes:
    comp = zlib.compressobj(wbits=-15)
    return b"DFL\x00" + comp.compress(payload) + comp.flush()


# ---------------------------------------------------------------- real fixture blobs


def test_decode_fixture_with_analyser_file_reference():
    info = md.decode_index_metadata(DISCOVERIES_META)
    assert info.name == "scientific_discoveries"
    assert (
        info.settings["index.analysis.filter.field_synonyms.synonyms_path"]
        == "analysis/field_synonyms.txt"
    )
    assert info.settings["index.analysis.analyzer.discovery_search.filter"] == [
        "lowercase",
        "field_synonyms",
    ]
    assert info.number_of_shards == 1
    assert info.created_version.distribution == "opensearch"
    assert (info.created_version.major, info.created_version.minor) == (3, 8)
    props = info.mappings["properties"]
    assert props["description"]["search_analyzer"] == "discovery_search"
    assert props["title"]["fields"]["keyword"]["type"] == "keyword"


def test_decode_second_fixture_has_biography_mapping():
    info = md.decode_index_metadata(SCIENTISTS_META)
    assert info.name == "famous_scientists"
    assert info.mappings["properties"]["biography"] == {"type": "text", "analyzer": "english"}
    assert not [k for k in info.settings if "analysis" in k]


def test_decode_shard_snapshot_manifest():
    manifest = md.decode_shard_snapshot(SHARD_SNAP)
    assert manifest.name == "scientists-v1"
    by_name = {f.name: f for f in manifest.files}
    cfs = by_name["__gxVB6jhEQ96a0mi6_iF3Mw"]
    assert (cfs.physical_name, cfs.length) == ("_0.cfs", 13591)
    assert cfs.lucene_crc32 == 2400043472
    assert cfs.blobs() == [("__gxVB6jhEQ96a0mi6_iF3Mw", 13591)]
    virtual = [f for f in manifest.files if f.virtual]
    assert virtual and all(f.blobs() == [] for f in virtual)  # inline in metadata, no blob


def test_multipart_blob_names():
    f = md.ShardFile("__abc", "_0.cfs", 25, "1", 10)
    assert f.blobs() == [("__abc.part0", 10), ("__abc.part1", 10), ("__abc.part2", 5)]


def test_repository_data_fixture():
    raw = (REPO_DIR / "index-1").read_bytes()
    data = md.parse_repository_data(raw)
    assert [s.name for s in data.snapshots] == ["scientists-v1", "scientists-v2"]
    assert data.indices["scientific_discoveries"].id == DISCOVERIES_ID
    snap = data.find_snapshot("scientists-v1")
    assert (
        data.meta_identifier(snap, data.indices["scientific_discoveries"]) == "6ga29KEBtovP9BVW74q8"
    )
    assert data.indices["famous_scientists"].shard_generations == ("1iuYj6PkQPKCslYkOnugWA",)
    assert snap.version == "3.8.0" and snap.state == 1


def test_index_latest():
    assert md.parse_index_latest((REPO_DIR / "index.latest").read_bytes()) == 1
    with pytest.raises(MetadataFormatError):
        md.parse_index_latest(b"short")
    with pytest.raises(MetadataFormatError):
        md.parse_index_latest(struct.pack(">q", -1))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b'{"snapshots": [{"name": 1}]}',
        b'{"indices": {"a": {"id": ""}}}',
        b"\xff\xfe",
    ],
)
def test_repository_data_rejects_garbage(raw):
    with pytest.raises(MetadataFormatError):
        md.parse_repository_data(raw)


# ---------------------------------------------------------------- corruption (fail closed)


@pytest.mark.parametrize(
    "decoder,blob",
    [(md.decode_index_metadata, DISCOVERIES_META), (md.decode_shard_snapshot, SHARD_SNAP)],
)
def test_truncated_blobs_raise(decoder, blob):
    for cut in (0, 3, 10, len(blob) // 2, len(blob) - 17, len(blob) - 1):
        with pytest.raises(MetadataFormatError):
            decoder(blob[:cut])


@pytest.mark.parametrize(
    "decoder,blob",
    [(md.decode_index_metadata, DISCOVERIES_META), (md.decode_shard_snapshot, SHARD_SNAP)],
)
def test_crc_and_magic_corruption_raise(decoder, blob):
    flipped = bytearray(blob)
    flipped[len(blob) // 2] ^= 0x01
    with pytest.raises(MetadataFormatError, match="checksum"):
        decoder(bytes(flipped))
    bad_magic = bytearray(blob)
    bad_magic[0] ^= 0xFF
    with pytest.raises(MetadataFormatError, match="magic"):
        decoder(bytes(bad_magic))
    bad_footer = bytearray(blob)
    bad_footer[-16] ^= 0xFF
    with pytest.raises(MetadataFormatError, match="footer"):
        decoder(bytes(bad_footer))


def test_wrong_codec_name_rejected():
    with pytest.raises(MetadataFormatError, match="codec"):
        md.decode_index_metadata(SHARD_SNAP)
    with pytest.raises(MetadataFormatError, match="codec"):
        md.decode_shard_snapshot(DISCOVERIES_META)


def test_valid_frame_with_garbage_body_rejected():
    with pytest.raises(MetadataFormatError):
        md.decode_index_metadata(codec_frame("index-metadata", b"\x00\x01\x02\x03\x04\x05"))
    with pytest.raises(MetadataFormatError):
        md.decode_index_metadata(
            codec_frame("index-metadata", b":)\n\x01\xfa\x83")
        )  # truncated object


def test_missing_settings_or_version_rejected():
    body = SmileEncoder().dump({"idx": {"settings": {"index.number_of_shards": "1"}}})
    with pytest.raises(MetadataFormatError, match="creation version"):
        md.decode_index_metadata(codec_frame("index-metadata", body))
    body = SmileEncoder().dump({"idx": {"state": "open"}})
    with pytest.raises(MetadataFormatError, match="settings"):
        md.decode_index_metadata(codec_frame("index-metadata", body))


def test_corrupt_dfl_payload_rejected():
    mapping = dfl(json.dumps({"_doc": {"properties": {}}}).encode())
    doc = {
        "idx": {
            "settings": {"index.version.created": "137297827", "index.number_of_shards": "1"},
            "mappings": [mapping[:-4] + b"\x00\x00\x00\x00"],
        }
    }
    with pytest.raises(MetadataFormatError):
        md.decode_index_metadata(codec_frame("index-metadata", SmileEncoder().dump(doc)))
    with pytest.raises(MetadataFormatError):
        md.decompress_dfl(b"XXXX")


def test_decompression_bomb_is_bounded(monkeypatch):
    monkeypatch.setattr(md, "_MAX_DECOMPRESSED_BYTES", 1000)
    with pytest.raises(MetadataFormatError):
        md.decompress_dfl(dfl(b"a" * 100_000))


# ---------------------------------------------------------------- synthetic documents


@pytest.mark.parametrize("raw_binary", [True, False])
def test_synthetic_compressed_smile_with_shared_strings(raw_binary):
    mapping_json = json.dumps(
        {
            "_doc": {
                "properties": {
                    "body": {"type": "text", "analyzer": "english"},
                    "vec": {"type": "knn_vector", "dimension": 8},
                }
            }
        }
    ).encode()
    settings = {
        "index.version.created": "137297827",
        "index.number_of_shards": "3",
        "index.analysis.filter.syn_a.type": "synonym",
        "index.analysis.filter.syn_a.synonyms_path": "analysis/a.txt",
        "index.analysis.filter.syn_b.type": "synonym",  # repeated value -> shared string
        "index.analysis.filter.syn_b.synonyms_path": "analysis/b.txt",
        "index.analysis.analyzer.x.filter": ["lowercase", "syn_a", "syn_b", "synonym"],
        "index.knn": True,
        "index.refresh_interval": "1s",
    }
    doc = {
        "myindex": {
            "version": 12,
            "mapping_version": 2**40,  # long
            "state": "open",
            "settings": settings,
            "mappings": [dfl(mapping_json)],
            "aliases": [],
            "ratio": 1.5,
            "big": 2**70,
            "neg": -123456,
            "unicode": "héllo wörld",
            "long_text": "x" * 200,
            "nested": {"a": {"b": [1, 2, {"c": None}]}, "": "empty-key"},
        }
    }
    encoder = SmileEncoder(raw_binary)
    blob = codec_frame("index-metadata", encoder.dump(doc))
    # The encoder must actually have used shared references for this to prove anything.
    assert encoder.values and b"\x24" in blob

    info = md.decode_index_metadata(blob)
    assert info.name == "myindex"
    assert info.number_of_shards == 3
    assert info.created_version == md.Version("opensearch", 3, 8, 0)
    assert info.settings["index.analysis.filter.syn_b.synonyms_path"] == "analysis/b.txt"
    assert info.settings["index.analysis.filter.syn_b.type"] == "synonym"
    assert info.settings["index.analysis.analyzer.x.filter"] == [
        "lowercase",
        "syn_a",
        "syn_b",
        "synonym",
    ]
    assert info.settings["index.knn"] == "true"
    assert info.mappings["properties"]["vec"] == {"type": "knn_vector", "dimension": 8}


def test_smile_scalar_round_trips():
    values = [
        0,
        15,
        -16,
        16,
        -17,
        2**31 - 1,
        -(2**31),
        2**31,
        -(2**40),
        2**63 - 1,
        2**64,
        -(2**70),
        0.25,
        -3.5e300,
        "",
        "a",
        "é",
        "x" * 33,
        "é" * 20,
        "y" * 70,
        True,
        False,
        None,
        b"\x00\xff" * 9,
    ]
    for raw in (True, False):
        for v in values:
            enc = SmileEncoder(raw)
            assert md.smile_loads(enc.dump([v, v])) == [v, v], v


def test_smile_shared_value_and_key_references_beyond_one_byte():
    keys = {f"key{i}": f"value{i}" for i in range(100)}
    doc = [keys, keys]  # second pass is all shared references, indexes > 63 / > 30
    assert md.smile_loads(SmileEncoder().dump(doc)) == doc


def test_smile_long_key_is_registered_in_the_shared_name_table():
    """Hand-built per the Jackson SMILE spec: ``0x34`` names (> 64 bytes) take a shared-name slot.

    Document: ``[{LONG: 1, "b": 2}, {"b": 3, LONG: 4}]`` with shared names on. The second
    object reaches ``b`` through slot 1 (``0x41``) and LONG through slot 0 (``0x40``); a
    reader that skips long names sees ``b`` at slot 0 and fails.
    """
    long_key = "k" * 65
    doc = (
        b":)\n\x01"  # header, shared key names enabled
        + b"\xf8"  # start array
        + b"\xfa"  # start object
        + b"\x34"
        + long_key.encode()
        + b"\xfc"  # long name (slot 0)
        + b"\xc2"  # small int 1
        + b"\x80b"  # short ASCII name "b" (slot 1)
        + b"\xc4"  # small int 2
        + b"\xfb"  # end object
        + b"\xfa"
        + b"\x41"
        + b"\xc6"
        + b"\x40"
        + b"\xc8"
        + b"\xfb"  # {slot1: 3, slot0: 4}
        + b"\xf9"  # end array
    )
    assert md.smile_loads(doc) == [{long_key: 1, "b": 2}, {"b": 3, long_key: 4}]


def test_smile_long_key_is_not_subject_to_the_value_length_limit_and_table_resets_at_1024():
    def short_key(i: int) -> bytes:
        name = f"k{i:04d}".encode()
        return bytes([0x80 + len(name) - 1]) + name

    long_key = "L" * 70
    first = b"\xfa" + b"".join(short_key(i) + b"\xc0" for i in range(1024))  # fills the table
    first += (
        b"\x34" + long_key.encode() + b"\xfc" + b"\xc2" + b"\xfb"
    )  # 1025th name: table restarts
    header = b":)\n\x01\xf8"

    # After the restart the long name occupies slot 0 ...
    ok = header + first + b"\xfa\x40\xc4\xfb" + b"\xf9"
    decoded = md.smile_loads(ok)
    assert decoded[1] == {long_key: 2} and len(decoded[0]) == 1025
    # ... and the pre-restart names are gone.
    stale = header + first + b"\xfa\x41\xc4\xfb" + b"\xf9"
    with pytest.raises(MetadataFormatError, match="dangling"):
        md.smile_loads(stale)


def test_smile_encoder_round_trip_with_long_names_and_resets():
    names = [("L" * 70 + str(i)) if i % 7 == 0 else f"name{i}" for i in range(1500)]
    first = {n: i for i, n in enumerate(names)}
    doc = [first, dict(reversed(list(first.items())))]  # second pass is shared references
    assert md.smile_loads(SmileEncoder().dump(doc)) == doc


def test_smile_rejects_bad_input():
    for blob in (
        b"",
        b":)\n",
        b"{}",
        b":)\n\x10\x24",
        b":)\n\x00\xf8",
        b":)\n\x00\xfa\x80a",
        b":)\n\x01\x01",
        b":)\n\x00\xc0\xc0",
    ):
        with pytest.raises(MetadataFormatError):
            md.smile_loads(blob)
    # dangling shared reference
    with pytest.raises(MetadataFormatError):
        md.smile_loads(b":)\n\x03\xf8\x05\xf9")
    # deeply nested arrays are bounded
    with pytest.raises(MetadataFormatError):
        md.smile_loads(b":)\n\x00" + b"\xf8" * 500 + b"\xf9" * 500)


def test_version_ids():
    assert md.Version.from_id(137297827) == md.Version("opensearch", 3, 8, 0)
    assert md.Version.from_id(1020099 | 0x08000000) == md.Version("opensearch", 1, 2, 0)
    assert md.Version.from_id(2060299 | 0x08000000) == md.Version("opensearch", 2, 6, 2)
    assert md.Version.from_id(7100299) == md.Version("elasticsearch", 7, 10, 2)
    assert str(md.Version.from_id(7100299)) == "7.10.2"
    with pytest.raises(MetadataFormatError):
        md.Version.from_id(0)


def test_parse_version_string():
    assert md.parse_version_string("3.8.0").triple == (3, 8, 0)
    assert md.parse_version_string("2.11").triple == (2, 11, 0)
    assert md.parse_version_string("3.8.0-SNAPSHOT").triple == (3, 8, 0)
    assert md.parse_version_string(137297827).triple == (3, 8, 0)
    assert md.parse_version_string("garbage") is None
    assert md.parse_version_string(None) is None
    assert md.parse_version_string(True) is None
