"""Decoders for the OpenSearch/Elasticsearch snapshot-repository wire formats.

Supported, fail-closed: Lucene codec framing (header magic, codec name, CRC32
footer), SMILE (jackson smile format, version 0), ``DFL\\0`` raw-deflate payloads,
RepositoryData JSON, per-index ``IndexMetadata`` and per-shard snapshot
manifests. Anything not understood raises :class:`MetadataFormatError`.

Supported-version matrix: index metadata written by OpenSearch 1.x-3.x and
Elasticsearch 7.x repositories using the SMILE ``ChecksumBlobStoreFormat``.
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any, Literal

CODEC_MAGIC = 0x3FD76C17
FOOTER_MAGIC = 0xC02893E8
_FOOTER_LEN = 16
_OPENSEARCH_ID_BIT = 0x08000000
_MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_DEPTH = 64
_MAX_SHARED = 1024
_LONG_MAX = 2**63 - 1


class MetadataFormatError(Exception):
    """A repository blob is truncated, corrupt or in an unsupported format."""


# --------------------------------------------------------------------------
# Lucene codec framing
# --------------------------------------------------------------------------


def _read_vint(data: bytes, pos: int) -> tuple[int, int]:
    """Lucene/Java little-endian 7-bit vInt."""
    value = 0
    shift = 0
    for _ in range(5):
        if pos >= len(data):
            raise MetadataFormatError("truncated vint")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
    raise MetadataFormatError("vint too long")


def unwrap_codec(blob: bytes, expected_codec: str | None = None) -> tuple[str, int, bytes]:
    """Verify header magic and CRC32 footer, return ``(codec, version, body)``."""
    if len(blob) < 4 + 1 + 4 + _FOOTER_LEN:
        raise MetadataFormatError("blob too short for a codec frame")
    if struct.unpack_from(">I", blob, 0)[0] != CODEC_MAGIC:
        raise MetadataFormatError("bad codec header magic")
    name_len, pos = _read_vint(blob, 4)
    if name_len == 0 or name_len > 128 or pos + name_len + 4 > len(blob) - _FOOTER_LEN:
        raise MetadataFormatError("bad codec name")
    try:
        codec = blob[pos : pos + name_len].decode("ascii")
    except UnicodeDecodeError as exc:
        raise MetadataFormatError("bad codec name") from exc
    pos += name_len
    version = struct.unpack_from(">i", blob, pos)[0]
    pos += 4
    if expected_codec is not None and codec != expected_codec:
        raise MetadataFormatError(f"unexpected codec {codec!r}")

    footer_start = len(blob) - _FOOTER_LEN
    magic, algorithm, checksum = struct.unpack_from(">IiQ", blob, footer_start)
    if magic != FOOTER_MAGIC or algorithm != 0:
        raise MetadataFormatError("bad codec footer")
    if checksum >> 32 or checksum != zlib.crc32(blob[: len(blob) - 8]):
        raise MetadataFormatError("codec checksum mismatch")
    return codec, version, blob[pos:footer_start]


def verify_codec_footer(blob: bytes) -> None:
    """CRC-check a codec-framed blob without interpreting its body."""
    unwrap_codec(blob)


# --------------------------------------------------------------------------
# SMILE
# --------------------------------------------------------------------------


class _Smile:
    """Minimal, strict SMILE reader (no encoding of floats beyond float/double)."""

    def __init__(self, data: bytes):
        if len(data) < 5 or data[:3] != b":)\n":
            raise MetadataFormatError("missing SMILE header")
        flags = data[3]
        if flags >> 4:
            raise MetadataFormatError("unsupported SMILE version")
        self.shared_keys = bool(flags & 0x01)
        self.shared_values = bool(flags & 0x02)
        self.raw_binary = bool(flags & 0x04)
        self.data = data
        self.pos = 4
        self.keys: list[str] = []
        self.values: list[str] = []

    # -- primitives
    def _byte(self) -> int:
        if self.pos >= len(self.data):
            raise MetadataFormatError("truncated SMILE document")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def _take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise MetadataFormatError("truncated SMILE document")
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def _vint(self) -> int:
        """SMILE VInt: 7 data bits per byte, the last byte has bit 7 set and 6 data bits."""
        value = 0
        for _ in range(11):
            byte = self._byte()
            if byte & 0x80:
                return (value << 6) | (byte & 0x3F)
            value = (value << 7) | byte
        raise MetadataFormatError("SMILE vint too long")

    @staticmethod
    def _zigzag(value: int) -> int:
        return (value >> 1) ^ -(value & 1)

    def _text(self, n: int) -> str:
        try:
            return self._take(n).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MetadataFormatError("invalid UTF-8 in SMILE string") from exc

    def _until_marker(self) -> str:
        end = self.data.find(b"\xfc", self.pos)
        if end == -1:
            raise MetadataFormatError("unterminated SMILE long string")
        raw = self.data[self.pos : end]
        self.pos = end + 1
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MetadataFormatError("invalid UTF-8 in SMILE string") from exc

    @staticmethod
    def _remember(
        table: list[str], value: str, enabled: bool, *, max_bytes: int | None = 64
    ) -> None:
        """Add to a shared-string table (keys: any length; values: at most 64 bytes, per the spec).

        A full table (1024 entries) restarts from empty, like Jackson's name/value buffers.
        """
        if (
            not enabled
            or not value
            or (max_bytes is not None and len(value.encode("utf-8")) > max_bytes)
        ):
            return
        if len(table) >= _MAX_SHARED:
            table.clear()
        table.append(value)

    def _binary7(self) -> bytes:
        length = self._vint()
        encoded_len = (length * 8 + 6) // 7
        encoded = self._take(encoded_len)
        acc = 0
        bits = 0
        out = bytearray()
        for idx, byte in enumerate(encoded):
            if idx == encoded_len - 1 and length * 8 % 7:
                take = length * 8 - (encoded_len - 1) * 7
                acc = (acc << take) | (byte & ((1 << take) - 1))
                bits += take
            else:
                acc = (acc << 7) | (byte & 0x7F)
                bits += 7
            while bits >= 8:
                bits -= 8
                out.append((acc >> bits) & 0xFF)
                acc &= (1 << bits) - 1
        if len(out) != length:
            raise MetadataFormatError("corrupt SMILE 7-bit binary")
        return bytes(out)

    def _shared(self, table: list[str], index: int) -> str:
        if index >= len(table):
            raise MetadataFormatError("dangling SMILE shared reference")
        return table[index]

    # -- keys
    def _key(self) -> str | None:
        token = self._byte()
        if token == 0xFB:
            return None
        if token == 0x20:
            return ""
        if 0x30 <= token <= 0x33:
            if not self.shared_keys:
                raise MetadataFormatError("unexpected shared key reference")
            return self._shared(self.keys, ((token & 0x03) << 8) | self._byte())
        if token == 0x34:
            # Jackson registers long (> 64 byte) names in the shared-name table too
            # (SmileParser._handleLongFieldName), so later back-references count them.
            name = self._until_marker()
            self._remember(self.keys, name, self.shared_keys, max_bytes=None)
            return name
        if 0x40 <= token <= 0x7F:
            if not self.shared_keys:
                raise MetadataFormatError("unexpected shared key reference")
            return self._shared(self.keys, token & 0x3F)
        if 0x80 <= token <= 0xBF:
            name = self._text((token & 0x3F) + 1)
        elif 0xC0 <= token <= 0xF7:
            name = self._text((token - 0xC0) + 2)
        else:
            raise MetadataFormatError(f"unsupported SMILE key token 0x{token:02x}")
        self._remember(self.keys, name, self.shared_keys, max_bytes=None)
        return name

    # -- values
    def value(self, depth: int = 0) -> Any:
        if depth > _MAX_DEPTH:
            raise MetadataFormatError("SMILE document nested too deeply")
        token = self._byte()
        high = token >> 5
        if high == 0:
            if token == 0 or not self.shared_values:
                raise MetadataFormatError("invalid SMILE shared value reference")
            return self._shared(self.values, token - 1)
        if high == 1:
            low = token & 0x1F
            if low == 0:
                return ""
            if low == 1:
                return None
            if low == 2:
                return False
            if low == 3:
                return True
            if low in (4, 5):
                return self._zigzag(self._vint())
            if low == 6:
                length = self._vint()
                return int.from_bytes(self._take(length), "big", signed=True)
            if low == 8:
                return struct.unpack(">f", self._decode_fixed(4))[0]
            if low == 9:
                return struct.unpack(">d", self._decode_fixed(8))[0]
            if low == 10:
                scale = self._zigzag(self._vint())
                length = self._vint()
                unscaled = int.from_bytes(self._take(length), "big", signed=True)
                return str(unscaled) if scale == 0 else f"{unscaled}e{-scale}"
            raise MetadataFormatError(f"unsupported SMILE token 0x{token:02x}")
        if high in (2, 3, 4, 5):
            if high == 2:
                text = self._text((token & 0x1F) + 1)
            elif high == 3:
                text = self._text((token & 0x1F) + 33)
            elif high == 4:
                text = self._text((token & 0x1F) + 2)
            else:
                text = self._text((token & 0x1F) + 34)
            self._remember(self.values, text, self.shared_values)
            return text
        if high == 6:
            return self._zigzag(token & 0x1F)
        # high == 7
        if token in (0xE0, 0xE4):
            return self._until_marker()
        if token == 0xE8:
            return self._binary7()
        if token == 0xFD:
            return self._take(self._vint())
        if 0xEC <= token <= 0xEF:
            if not self.shared_values:
                raise MetadataFormatError("unexpected shared value reference")
            return self._shared(self.values, ((token & 0x03) << 8) | self._byte())
        if token == 0xF8:
            items = []
            while True:
                if self.pos < len(self.data) and self.data[self.pos] == 0xF9:
                    self.pos += 1
                    return items
                items.append(self.value(depth + 1))
        if token == 0xFA:
            obj: dict[str, Any] = {}
            while True:
                key = self._key()
                if key is None:
                    return obj
                obj[key] = self.value(depth + 1)
        raise MetadataFormatError(f"unsupported SMILE token 0x{token:02x}")

    def _decode_fixed(self, size: int) -> bytes:
        """Float/double: 5 or 10 bytes of 7 bit groups, big-endian bit stream."""
        groups = 5 if size == 4 else 10
        acc = 0
        for _ in range(groups):
            acc = (acc << 7) | (self._byte() & 0x7F)
        return (acc & ((1 << (size * 8)) - 1)).to_bytes(size, "big")


def smile_loads(data: bytes) -> Any:
    """Decode a SMILE document, requiring that it consumes the whole input."""
    reader = _Smile(data)
    try:
        result = reader.value()
    except (IndexError, struct.error, RecursionError, OverflowError) as exc:
        raise MetadataFormatError("corrupt SMILE document") from exc
    if reader.pos != len(data):
        # Optional end-of-content marker.
        if not (reader.pos == len(data) - 1 and data[reader.pos] == 0xFF):
            raise MetadataFormatError("trailing bytes after SMILE document")
    return result


def decompress_dfl(blob: bytes) -> bytes:
    """Inflate a ``DFL\\0`` compressed payload (raw deflate), bounded in size."""
    if blob[:4] != b"DFL\x00":
        raise MetadataFormatError("not a DFL payload")
    inflater = zlib.decompressobj(-15)
    try:
        out = inflater.decompress(blob[4:], _MAX_DECOMPRESSED_BYTES + 1)
        if inflater.unconsumed_tail or not inflater.eof:
            if len(out) > _MAX_DECOMPRESSED_BYTES:
                raise MetadataFormatError("decompressed payload too large")
            out += inflater.flush()
    except zlib.error as exc:
        raise MetadataFormatError("corrupt compressed payload") from exc
    if len(out) > _MAX_DECOMPRESSED_BYTES or not inflater.eof:
        raise MetadataFormatError("corrupt or oversized compressed payload")
    return out


def _decode_document(blob: bytes) -> Any:
    """Decode a (possibly DFL-compressed) JSON or SMILE document."""
    if blob[:4] == b"DFL\x00":
        blob = decompress_dfl(blob)
    if blob[:3] == b":)\n":
        return smile_loads(blob)
    try:
        return json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise MetadataFormatError("unrecognised document encoding") from exc


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------


@dataclass(frozen=True, order=False)
class Version:
    distribution: Literal["opensearch", "elasticsearch"]
    major: int
    minor: int
    patch: int

    @property
    def triple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def from_id(cls, version_id: int) -> Version:
        if version_id <= 0:
            raise MetadataFormatError("invalid version id")
        distribution: Literal["opensearch", "elasticsearch"] = "elasticsearch"
        if version_id & _OPENSEARCH_ID_BIT:
            distribution = "opensearch"
            version_id &= ~_OPENSEARCH_ID_BIT
        return cls(
            distribution,
            version_id // 1_000_000,
            (version_id // 10_000) % 100,
            (version_id // 100) % 100,
        )


def parse_version_string(value: Any) -> Version | None:
    """Best effort ``major.minor.patch`` or numeric id; distribution is unknown."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit() and len(value) >= 7):
        try:
            return Version.from_id(int(value))
        except MetadataFormatError:
            return None
    if isinstance(value, str):
        pieces = value.split("-", 1)[0].split(".")
        if len(pieces) >= 2 and all(p.isdigit() for p in pieces[:3]):
            nums = [int(p) for p in pieces[:3]] + [0] * (3 - len(pieces[:3]))
            return Version("opensearch", nums[0], nums[1], nums[2])
    return None


# --------------------------------------------------------------------------
# RepositoryData
# --------------------------------------------------------------------------

SNAPSHOT_STATE_SUCCESS = 1
SNAPSHOT_STATE_PARTIAL = 3


@dataclass(frozen=True)
class RepoSnapshot:
    name: str
    uuid: str
    state: int | None
    version: str | None
    index_metadata_lookup: dict[str, str]


@dataclass(frozen=True)
class RepoIndex:
    name: str
    id: str
    shard_path_type: int
    snapshots: tuple[str, ...]
    shard_generations: tuple[str, ...] | None


@dataclass(frozen=True)
class RepositoryData:
    snapshots: tuple[RepoSnapshot, ...]
    indices: dict[str, RepoIndex]
    index_metadata_identifiers: dict[str, str] = field(default_factory=dict)

    def find_snapshot(self, name: str) -> RepoSnapshot | None:
        for snap in self.snapshots:
            if snap.name == name:
                return snap
        return None

    def meta_identifier(self, snapshot: RepoSnapshot, index: RepoIndex) -> str:
        """Identifier in ``indices/<id>/meta-<identifier>.dat`` for this snapshot."""
        lookup = snapshot.index_metadata_lookup.get(index.id)
        if lookup is None:
            # Legacy layout: the metadata blob is named after the snapshot uuid.
            return snapshot.uuid
        identifier = self.index_metadata_identifiers.get(lookup)
        if identifier is None:
            raise MetadataFormatError("repository data references unknown index metadata")
        return identifier


def _req_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise MetadataFormatError(f"repository data: invalid {what}")
    return value


def parse_index_latest(raw: bytes) -> int:
    """``index.latest`` holds the generation as an 8 byte big-endian long."""
    if len(raw) != 8:
        raise MetadataFormatError("index.latest has unexpected length")
    value = struct.unpack(">q", raw)[0]
    if value < 0:
        raise MetadataFormatError("index.latest holds an invalid generation")
    return value


def parse_repository_data(raw: bytes) -> RepositoryData:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise MetadataFormatError("repository data is not valid JSON") from exc
    if not isinstance(doc, dict):
        raise MetadataFormatError("repository data is not an object")

    snapshots: list[RepoSnapshot] = []
    for item in doc.get("snapshots") or []:
        if not isinstance(item, dict):
            raise MetadataFormatError("repository data: invalid snapshot entry")
        state = item.get("state")
        lookup = item.get("index_metadata_lookup") or {}
        if not isinstance(lookup, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in lookup.items()
        ):
            raise MetadataFormatError("repository data: invalid index_metadata_lookup")
        version = item.get("version")
        snapshots.append(
            RepoSnapshot(
                name=_req_str(item.get("name"), "snapshot name"),
                uuid=_req_str(item.get("uuid"), "snapshot uuid"),
                state=state if isinstance(state, int) and not isinstance(state, bool) else None,
                version=str(version) if version is not None else None,
                index_metadata_lookup=dict(lookup),
            )
        )

    indices: dict[str, RepoIndex] = {}
    raw_indices = doc.get("indices") or {}
    if not isinstance(raw_indices, dict):
        raise MetadataFormatError("repository data: invalid indices")
    for name, entry in raw_indices.items():
        if not isinstance(entry, dict):
            raise MetadataFormatError("repository data: invalid index entry")
        gens = entry.get("shard_generations")
        shard_generations: tuple[str, ...] | None = None
        if isinstance(gens, list) and all(isinstance(g, str) and g for g in gens):
            shard_generations = tuple(gens)
        snaps = entry.get("snapshots") or []
        if not isinstance(snaps, list) or not all(isinstance(s, str) for s in snaps):
            raise MetadataFormatError("repository data: invalid index snapshots")
        path_type = entry.get("shard_path_type", 0)
        if not isinstance(path_type, int) or isinstance(path_type, bool):
            raise MetadataFormatError("repository data: invalid shard_path_type")
        indices[str(name)] = RepoIndex(
            name=str(name),
            id=_req_str(entry.get("id"), "index id"),
            shard_path_type=path_type,
            snapshots=tuple(snaps),
            shard_generations=shard_generations,
        )

    identifiers = doc.get("index_metadata_identifiers") or {}
    if not isinstance(identifiers, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in identifiers.items()
    ):
        raise MetadataFormatError("repository data: invalid index_metadata_identifiers")
    return RepositoryData(tuple(snapshots), indices, dict(identifiers))


# --------------------------------------------------------------------------
# IndexMetadata
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexMetadataInfo:
    name: str
    settings: dict[str, str | list]
    mappings: dict
    created_version: Version
    number_of_shards: int


def _flatten_settings(value: Any, prefix: str, out: dict[str, str | list]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            _flatten_settings(inner, f"{prefix}.{key}" if prefix else str(key), out)
        return
    if isinstance(value, list):
        out[prefix] = [_scalar_text(v) for v in value]
        return
    out[prefix] = _scalar_text(value)


def _scalar_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, bytes):
        raise MetadataFormatError("binary value in settings")
    if isinstance(value, (dict, list)):
        raise MetadataFormatError("nested value in settings list")
    return str(value)


def _normalize_mapping(entries: Any) -> dict:
    """Return the type-body mapping (``{"properties": ...}``) from stored entries."""
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise MetadataFormatError("unrecognised mappings layout")
    for entry in entries:
        if isinstance(entry, (bytes, bytearray)):
            entry = _decode_document(bytes(entry))
        if not isinstance(entry, dict):
            raise MetadataFormatError("unrecognised mapping entry")
        if len(entry) == 1:
            ((only_key, only_value),) = entry.items()
            if isinstance(only_value, (bytes, bytearray)):
                only_value = _decode_document(bytes(only_value))
            if isinstance(only_value, dict) and only_key not in ("properties", "dynamic"):
                return only_value
        return entry
    return {}


def decode_index_metadata(blob: bytes) -> IndexMetadataInfo:
    _codec, _version, body = unwrap_codec(blob, "index-metadata")
    doc = smile_loads(body) if body[:3] == b":)\n" else _decode_document(body)
    if not isinstance(doc, dict) or len(doc) != 1:
        raise MetadataFormatError("index metadata has an unexpected shape")
    ((name, meta),) = doc.items()
    if not isinstance(meta, dict):
        raise MetadataFormatError("index metadata has an unexpected shape")

    settings: dict[str, str | list] = {}
    raw_settings = meta.get("settings")
    if not isinstance(raw_settings, dict):
        raise MetadataFormatError("index metadata has no settings")
    _flatten_settings(raw_settings, "", settings)

    created_raw = settings.get("index.version.created")
    if not isinstance(created_raw, str) or not created_raw.isdigit():
        raise MetadataFormatError("index metadata has no creation version")
    created = Version.from_id(int(created_raw))

    shards_raw = settings.get("index.number_of_shards")
    if not isinstance(shards_raw, str) or not shards_raw.isdigit() or int(shards_raw) < 1:
        raise MetadataFormatError("index metadata has no shard count")

    mappings = _normalize_mapping(meta.get("mappings", []))
    return IndexMetadataInfo(
        name=str(name),
        settings=settings,
        mappings=mappings,
        created_version=created,
        number_of_shards=int(shards_raw),
    )


# --------------------------------------------------------------------------
# Shard snapshot manifest
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ShardFile:
    name: str  # blob name, e.g. "__abc" (may be virtual: "v__abc")
    physical_name: str
    length: int
    checksum: str
    part_size: int | None

    @property
    def virtual(self) -> bool:
        return self.name.startswith("v__")

    @property
    def lucene_crc32(self) -> int | None:
        try:
            return int(self.checksum, 36)
        except ValueError:
            return None

    def blobs(self) -> list[tuple[str, int]]:
        """``(blob name, size)`` pairs; empty for virtual (inline) files."""
        if self.virtual:
            return []
        if not self.part_size or self.part_size >= self.length:
            return [(self.name, self.length)]
        count = -(-self.length // self.part_size)
        out = []
        for part in range(count):
            size = min(self.part_size, self.length - part * self.part_size)
            out.append((f"{self.name}.part{part}", size))
        return out


@dataclass(frozen=True)
class ShardSnapshotManifest:
    name: str
    total_size: int
    files: tuple[ShardFile, ...]


def _nonneg_int(value: Any, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MetadataFormatError(f"shard manifest: invalid {what}")
    return value


def decode_shard_snapshot(blob: bytes) -> ShardSnapshotManifest:
    """Decode ``indices/<id>/<shard>/snap-<uuid>.dat``."""
    _codec, _version, body = unwrap_codec(blob, "snapshot")
    doc = _decode_document(body)
    if not isinstance(doc, dict):
        raise MetadataFormatError("shard manifest has an unexpected shape")
    files: list[ShardFile] = []
    for item in doc.get("files") or []:
        if not isinstance(item, dict):
            raise MetadataFormatError("shard manifest: invalid file entry")
        name = item.get("name")
        physical = item.get("physical_name")
        checksum = item.get("checksum")
        if not isinstance(name, str) or not name or not isinstance(physical, str):
            raise MetadataFormatError("shard manifest: invalid file name")
        if not isinstance(checksum, str):
            raise MetadataFormatError("shard manifest: invalid checksum")
        part_size = item.get("part_size")
        if part_size is not None:
            part_size = _nonneg_int(part_size, "part_size")
            if part_size == 0:
                raise MetadataFormatError("shard manifest: invalid part_size")
        files.append(
            ShardFile(
                name=name,
                physical_name=physical,
                length=_nonneg_int(item.get("length"), "length"),
                checksum=checksum,
                part_size=part_size,
            )
        )
    return ShardSnapshotManifest(
        name=str(doc.get("name", "")),
        total_size=_nonneg_int(doc.get("total_size", 0), "total_size"),
        files=tuple(files),
    )
