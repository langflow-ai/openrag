"""Pre-import checks: everything that can be decided before bytes are copied."""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from config import settings as app_settings

from .metadata import IndexMetadataInfo, Version, parse_version_string
from .source import SnapshotDetail, SnapshotSource, SnapshotSourceError, StagingManifest
from .staging import StagingStore

# Supported file-backed analyser settings: path setting -> inline setting.
ANALYSER_INLINE_SETTINGS = {
    "synonyms_path": "synonyms",
    "stopwords_path": "stopwords",
    "keywords_path": "keywords",
    "articles_path": "articles",
    "word_list_path": "word_list",
}
INLINE_TO_PATH_SETTING = {v: k for k, v in ANALYSER_INLINE_SETTINGS.items()}

_DEFAULT_HIGH_WATERMARK = "90%"
_UNITS = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4, "pb": 1024**5}


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    index: str | None = None


@dataclass(frozen=True)
class AnalyserFileRef:
    index: str
    setting: str  # full dotted key, e.g. index.analysis.filter.x.synonyms_path
    path: str  # value of that setting (display only; never used as a local path)
    inline_setting: str  # full dotted key to restore with, e.g. index.analysis.filter.x.synonyms


@dataclass(frozen=True)
class IndexPreflight:
    name: str
    created_version: str | None
    size_bytes: int
    doc_count: int | None = None


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    blockers: tuple[Issue, ...]
    warnings: tuple[Issue, ...]
    analyser_files: tuple[AnalyserFileRef, ...]
    staged_bytes: int
    restored_bytes: int
    indices: tuple[IndexPreflight, ...]
    manifest: StagingManifest | None
    written_by_version: str | None
    snapshot_uuid: str | None


def analyser_refs(
    index: str, settings: dict[str, Any]
) -> tuple[list[AnalyserFileRef], list[Issue]]:
    """File references derived from decoded settings only (never from user input)."""
    refs: list[AnalyserFileRef] = []
    issues: list[Issue] = []
    for key in sorted(settings):
        if not key.startswith("index.analysis.") or not key.rsplit(".", 1)[-1].endswith("_path"):
            continue
        head, _, leaf = key.rpartition(".")
        value = settings[key]
        inline = ANALYSER_INLINE_SETTINGS.get(leaf)
        if inline is None or not isinstance(value, str):
            issues.append(
                Issue(
                    "unsupported_analyser_file",
                    f"Setting {key} references a file that cannot be imported",
                    index,
                )
            )
            continue
        refs.append(AnalyserFileRef(index, key, value, f"{head}.{inline}"))
    return refs, issues


def _version_compatible(created: Version, cluster: Version) -> bool:
    if created.distribution == "opensearch":
        return created.major in (cluster.major, cluster.major - 1) and created.major >= 1
    # Elasticsearch-created indices are only restorable by OpenSearch 1.x (ES <= 7.10.2).
    return cluster.major == 1 and created.triple <= (7, 10, 2)


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def _parse_bytes(value: str) -> int | None:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]*)\s*", value)
    if not match:
        return None
    unit = match.group(2).lower() or "b"
    if unit not in _UNITS:
        return None
    return int(float(match.group(1)) * _UNITS[unit])


def _setting(settings_doc: dict[str, Any], key: str) -> Any:
    for scope in ("transient", "persistent", "defaults"):
        values = settings_doc.get(scope) or {}
        if key in values:
            return values[key]
    return None


async def _cluster_disk_issue(
    os_admin: Any, restored_bytes: int, replaced_bytes: int = 0
) -> tuple[Issue | None, Issue | None]:
    """``(blocker, warning)`` for cluster disk headroom after restoring ``restored_bytes``.

    The check is for the *peak*: during a re-import the generation being replaced
    (``replaced_bytes``) is still on disk while the new one restores, so it earns
    no credit; it only changes the blocker message.
    """
    unavailable = Issue(
        "disk_stats_unavailable",
        "Cluster disk usage could not be determined; capacity was not checked",
    )
    try:
        cluster_settings = await os_admin.cluster.get_settings(
            include_defaults=True, flat_settings=True
        )
        stats = await os_admin.nodes.stats(metric="fs")
    except Exception:
        return None, unavailable

    enabled = _setting(cluster_settings, "cluster.routing.allocation.disk.threshold_enabled")
    if isinstance(enabled, str) and enabled.lower() == "false":
        return None, None
    high = (
        _setting(cluster_settings, "cluster.routing.allocation.disk.watermark.high")
        or _DEFAULT_HIGH_WATERMARK
    )
    high = str(high).strip()

    nodes = []
    for node in (stats.get("nodes") or {}).values():
        roles = node.get("roles")
        if roles is not None and not any(str(r).startswith("data") for r in roles):
            continue
        total_fs = ((node.get("fs") or {}).get("total")) or {}
        total = total_fs.get("total_in_bytes")
        available = total_fs.get("available_in_bytes")
        if not isinstance(total, int) or not isinstance(available, int) or total <= 0:
            return None, unavailable
        nodes.append((total, available))
    if not nodes:
        return None, unavailable

    headrooms: list[int] = []
    for total, available in nodes:
        if high.endswith("%"):
            try:
                max_used = total * float(high[:-1]) / 100.0
            except ValueError:
                return None, unavailable
            headrooms.append(int(max_used - (total - available)))
        elif re.fullmatch(r"0?\.[0-9]+|1(?:\.0+)?|0", high):
            headrooms.append(int(total * float(high) - (total - available)))
        else:
            min_free = _parse_bytes(high)
            if min_free is None:
                return None, unavailable
            headrooms.append(available - min_free)

    replicas = max(int(getattr(app_settings, "OPENSEARCH_NUMBER_OF_REPLICAS", 0)), 0)
    copies = min(1 + replicas, len(nodes))
    needed = restored_bytes * copies
    if sum(max(h, 0) for h in headrooms) < needed or max(headrooms) <= 0:
        message = "The cluster does not have enough disk headroom below its high disk watermark to restore this snapshot"
        if replaced_bytes:
            message += " (the previous generation stays on disk until the new one is published)"
        return Issue("insufficient_disk_cluster", message), None
    return None, None


async def run_preflight(
    source: SnapshotSource,
    snapshot_name: str,
    indices: Sequence[str],
    *,
    os_admin: Any,
    staging: StagingStore,
    existing_snapshot_uuids: Collection[str] = (),
    replaced_bytes: int = 0,
    max_import_bytes: int | None = None,
) -> PreflightResult:
    """Run all import checks for ``indices`` of ``snapshot_name``.

    Content problems become blockers/warnings; only source/cluster transport
    failures raise (:class:`SnapshotSourceError` or the OpenSearch client's
    exception).
    """
    blockers: list[Issue] = []
    warnings: list[Issue] = []
    picked = sorted(set(indices))
    if not picked:
        blockers.append(Issue("index_not_in_snapshot", "Select at least one index"))

    detail: SnapshotDetail = await source.describe_snapshot(snapshot_name)
    result_indices: list[IndexPreflight] = []

    def finish(
        manifest: StagingManifest | None = None,
        refs: Sequence[AnalyserFileRef] = (),
        restored: int = 0,
    ) -> PreflightResult:
        return PreflightResult(
            ok=not blockers,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            analyser_files=tuple(refs),
            staged_bytes=manifest.total_bytes if manifest else 0,
            restored_bytes=restored,
            indices=tuple(result_indices),
            manifest=manifest,
            written_by_version=detail.version,
            snapshot_uuid=detail.uuid,
        )

    if detail.state not in ("SUCCESS", "PARTIAL"):
        blockers.append(Issue("snapshot_not_successful", f"The snapshot state is {detail.state}"))
        return finish()
    if detail.state == "PARTIAL":
        warnings.append(
            Issue("partial_snapshot", "The snapshot is partial; some shards may be missing")
        )
    if detail.uuid in set(existing_snapshot_uuids):
        warnings.append(Issue("duplicate_snapshot", "This snapshot has already been imported"))

    # --- cluster access and version
    cluster_version: Version | None = None
    try:
        info = await os_admin.info()
        number = ((info or {}).get("version") or {}).get("number")
        cluster_version = parse_version_string(number)
        await os_admin.snapshot.get_repository(repository="_all")
    except Exception as exc:
        if _status_code(exc) in (401, 403):
            blockers.append(
                Issue(
                    "missing_privileges",
                    "OpenRAG lacks the OpenSearch privileges needed to restore snapshots",
                )
            )
        else:
            raise

    snapshot_version = parse_version_string(detail.version)
    if cluster_version is not None and snapshot_version is not None:
        if snapshot_version.triple > cluster_version.triple:
            blockers.append(
                Issue(
                    "snapshot_newer_than_cluster",
                    f"The snapshot was written by version {snapshot_version}, newer than the cluster ({cluster_version})",
                )
            )

    # --- per index
    available = {info.name: info for info in detail.indices}
    refs: list[AnalyserFileRef] = []
    restorable: list[str] = []
    restored_bytes = 0
    for name in picked:
        if name.startswith("."):
            blockers.append(Issue("system_index", "System indices cannot be imported", name))
            continue
        index_info = available.get(name)
        if index_info is None:
            blockers.append(
                Issue("index_not_in_snapshot", "The index is not part of this snapshot", name)
            )
            continue
        meta: IndexMetadataInfo | None = detail.index_metadata.get(name)
        if meta is None:
            blockers.append(
                Issue(
                    "metadata_unreadable",
                    detail.unreadable.get(name, "Index metadata could not be read"),
                    name,
                )
            )
            result_indices.append(IndexPreflight(name, None, index_info.size_bytes))
            continue
        result_indices.append(
            IndexPreflight(name, str(meta.created_version), index_info.size_bytes)
        )
        restored_bytes += index_info.size_bytes
        if cluster_version is not None and not _version_compatible(
            meta.created_version, cluster_version
        ):
            blockers.append(
                Issue(
                    "version_incompatible",
                    f"The index was created by {meta.created_version.distribution} {meta.created_version}, "
                    f"which this cluster ({cluster_version}) cannot restore",
                    name,
                )
            )
            continue
        index_refs, issues = analyser_refs(name, meta.settings)
        blockers.extend(issues)
        for ref in index_refs:
            warnings.append(
                Issue(
                    "analyser_file_required",
                    f"Provide the content of {ref.path} (referenced by {ref.setting})",
                    name,
                )
            )
        refs.extend(index_refs)
        restorable.append(name)

    if blockers:
        return finish(None, refs, restored_bytes)

    # --- manifest, size and disk
    try:
        manifest = await source.build_manifest(snapshot_name, restorable)
    except SnapshotSourceError as exc:
        blockers.append(Issue("metadata_unreadable", str(exc)))
        return finish(None, refs, restored_bytes)

    # Folder-fallback indices have no exact shard manifests, so the pre-manifest size
    # undercounts; the manifest carries a conservative estimate from the folder's data blobs.
    estimates = {name: manifest.restored_bytes(name) for name in restorable}
    restored_bytes = 0
    for position, item in enumerate(result_indices):
        estimate = estimates.get(item.name)
        size = max(item.size_bytes, estimate) if estimate is not None else item.size_bytes
        result_indices[position] = IndexPreflight(
            item.name, item.created_version, size, item.doc_count
        )
        restored_bytes += size

    limit = (
        max_import_bytes
        if max_import_bytes is not None
        else app_settings.get_snapshot_max_import_bytes()
    )
    if manifest.total_bytes > limit:
        blockers.append(
            Issue(
                "too_large",
                f"The import needs {manifest.total_bytes} bytes; the limit is {limit} bytes",
            )
        )
    free = staging.free_bytes()
    if free is not None and free < manifest.total_bytes:
        blockers.append(
            Issue("insufficient_disk_staging", "Not enough free space in the staging location")
        )
    blocker, warning = await _cluster_disk_issue(os_admin, restored_bytes, replaced_bytes)
    if blocker:
        blockers.append(blocker)
    if warning:
        warnings.append(warning)
    return finish(manifest, refs, restored_bytes)
