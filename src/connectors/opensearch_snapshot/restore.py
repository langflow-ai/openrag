"""Restore, publish and cleanup operations against the OpenRAG OpenSearch cluster.

Request bodies are always built from server-derived values; nothing a user
submits is ever placed into a restore request except analyser file *lines*,
inserted as string-array values under server-derived setting keys.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from config import settings as app_settings

from .naming import is_valid_slug, slug_pattern
from .preflight import INLINE_TO_PATH_SETTING, AnalyserFileRef

MAX_ANALYSER_LINES = 50_000
_ERROR_TEXT_LIMIT = 500
_INDEX_NAME_RE = re.compile(r"[^\s,*?\"<>|#/\\]+")
_BLOCKS_PATTERN = "index.blocks.*"  # ignore_index_settings wildcard: every source-cluster block


class RestoreError(Exception):
    """Restore or publish failed. ``str()`` is user-safe and bounded."""


class AnalyserFileError(ValueError):
    """An uploaded analyser file is invalid or does not match the discovered references."""


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


def _reason(exc: Exception) -> str:
    """Short reason text from an OpenSearch client exception."""
    info = getattr(exc, "info", None)
    if isinstance(info, dict):
        error = info.get("error")
        if isinstance(error, dict):
            text = error.get("reason") or error.get("type")
            if text:
                return str(text)[:_ERROR_TEXT_LIMIT]
        elif isinstance(error, str):
            return error[:_ERROR_TEXT_LIMIT]
    return f"OpenSearch returned an error (status {_status_code(exc) or 'unknown'})"


def parse_analyser_file(content: str | bytes, max_bytes: int) -> list[str]:
    """Lines of an analyser file: ``#`` comment and blank lines removed."""
    raw = content.encode("utf-8") if isinstance(content, str) else content
    if len(raw) > max_bytes:
        raise AnalyserFileError("analyser file is too large")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AnalyserFileError("analyser file must be UTF-8 text") from exc
    if "\x00" in text:
        raise AnalyserFileError("analyser file must be text")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
        if len(lines) > MAX_ANALYSER_LINES:
            raise AnalyserFileError("analyser file has too many lines")
    return lines


def build_analyser_inlines(
    refs: Sequence[AnalyserFileRef], files: Sequence[Mapping[str, Any]], max_bytes: int
) -> dict[str, dict[str, list[str]]]:
    """``{index: {inline_setting: lines}}`` from uploads that match ``refs`` exactly."""
    expected = {(ref.index, ref.setting): ref for ref in refs}
    seen: set[tuple[str, str]] = set()
    out: dict[str, dict[str, list[str]]] = {}
    for item in files:
        index, setting, content = item.get("index"), item.get("setting"), item.get("content")
        if (
            not isinstance(index, str)
            or not isinstance(setting, str)
            or not isinstance(content, (str, bytes))
        ):
            raise AnalyserFileError("analyser file entries need index, setting and content")
        key = (index, setting)
        ref = expected.get(key)
        if ref is None:
            raise AnalyserFileError("analyser file does not match a required file")
        if key in seen:
            raise AnalyserFileError("analyser file was provided more than once")
        seen.add(key)
        out.setdefault(index, {})[ref.inline_setting] = parse_analyser_file(content, max_bytes)
    if seen != set(expected):
        raise AnalyserFileError("a required analyser file was not provided")
    return out


def _ignore_key_for(inline_setting: str) -> str:
    head, _, leaf = inline_setting.rpartition(".")
    path_leaf = INLINE_TO_PATH_SETTING.get(leaf)
    if not head.startswith("index.analysis.") or path_leaf is None:
        raise ValueError("unsupported analyser setting")
    return f"{head}.{path_leaf}"


def _replicas() -> int:
    return max(int(getattr(app_settings, "OPENSEARCH_NUMBER_OF_REPLICAS", 0)), 0)


async def _data_node_count(os_admin: Any) -> int | None:
    """Number of data nodes, or ``None`` when it cannot be determined."""
    try:
        rows = await os_admin.cat.nodes(format="json", h="node.role")
    except Exception:  # noqa: BLE001 - capacity hint only; the configured replicas apply
        return None
    count = sum(
        1
        for row in rows or []
        if isinstance(row, Mapping) and "d" in str(row.get("node.role", "")).lower()
    )
    return count or None


def _effective_replicas(data_nodes: int | None) -> int:
    """Configured replicas capped so every copy has a node: ``max(0, data_nodes - 1)``."""
    configured = _replicas()
    return configured if data_nodes is None else min(configured, max(data_nodes - 1, 0))


def restore_body(
    *,
    source_index: str,
    concrete_index: str,
    analyser_inlines: Mapping[str, list[str]] | None = None,
    partial: bool = False,
    data_nodes: int | None = None,
) -> dict:
    """Restore request body. ``analyser_inlines`` maps inline setting key -> lines.

    ``data_nodes`` (when known) caps the replica count at ``max(0, data_nodes - 1)``.
    """
    if not _INDEX_NAME_RE.fullmatch(source_index) or source_index.startswith(("-", "+", "_")):
        raise ValueError("invalid source index name")
    if not re.fullmatch(r"ds_[a-z][a-z0-9]{9}_[0-9]+_g[0-9]+", concrete_index):
        raise ValueError("invalid target index name")
    index_settings: dict[str, Any] = {
        "index.number_of_replicas": _effective_replicas(data_nodes),
        # Datasets are immutable: block document writes. Alias updates, reads, settings
        # updates and index deletion are unaffected by ``index.blocks.write``.
        "index.blocks.write": True,
    }
    # Never carry source-cluster blocks (e.g. a flood-stage ``read_only_allow_delete``
    # captured from a full disk): they would stop the alias publish on this cluster.
    ignore: list[str] = [_BLOCKS_PATTERN]
    for inline_key, lines in (analyser_inlines or {}).items():
        ignore.append(_ignore_key_for(inline_key))
        index_settings[inline_key] = [str(line) for line in lines]
    body: dict[str, Any] = {
        "indices": [source_index],
        "ignore_unavailable": False,
        "include_global_state": False,
        "include_aliases": False,
        "rename_pattern": "^(.+)$",
        "rename_replacement": concrete_index,
        "index_settings": index_settings,
        "ignore_index_settings": sorted(ignore),
    }
    if partial:
        body["partial"] = True
    return body


@dataclass(frozen=True)
class RestoreResult:
    concrete_index: str
    doc_count: int
    health: str


async def _allocation_reason(os_admin: Any, index: str) -> str:
    try:
        info = await os_admin.cluster.allocation_explain(
            body={"index": index, "shard": 0, "primary": True}
        )
    except Exception as exc:
        return f"index is red and the reason could not be determined ({_reason(exc)})"
    unassigned = (info or {}).get("unassigned_info") or {}
    text = (
        unassigned.get("details")
        or (info or {}).get("allocate_explanation")
        or unassigned.get("reason")
    )
    return str(text or "index is red")[:_ERROR_TEXT_LIMIT]


async def restore_index(
    os_admin: Any,
    *,
    repository: str,
    snapshot: str,
    source_index: str,
    concrete_index: str,
    analyser_inlines: Mapping[str, list[str]] | None = None,
    timeout_s: float = 3600.0,
    poll_s: float = 1.0,
    partial: bool = False,
) -> RestoreResult:
    """Restore one index and wait until it is usable; red/timeout raises :class:`RestoreError`."""
    data_nodes = await _data_node_count(os_admin)
    body = restore_body(
        source_index=source_index,
        concrete_index=concrete_index,
        analyser_inlines=analyser_inlines,
        partial=partial,
        data_nodes=data_nodes,
    )
    replicas = body["index_settings"]["index.number_of_replicas"]
    deadline = time.monotonic() + timeout_s
    try:
        await os_admin.snapshot.restore(
            repository=repository, snapshot=snapshot, body=body, wait_for_completion=False
        )
    except Exception as exc:
        raise RestoreError(_reason(exc)) from exc

    stable_polls = 0
    missing_polls = 0
    health: dict[str, Any] = {}
    while True:
        try:
            health = await os_admin.cluster.health(index=concrete_index)
            missing_polls = 0
        except Exception as exc:
            if _status_code(exc) == 404 or _status_code(exc) == 408:
                missing_polls += 1
                if missing_polls > 60:
                    raise RestoreError("the restored index did not appear") from exc
                health = {}
            else:
                raise RestoreError(_reason(exc)) from exc

        status = health.get("status")
        busy = int(health.get("initializing_shards", 0)) + int(health.get("relocating_shards", 0))
        unassigned = int(health.get("unassigned_shards", 0))
        if status == "green":
            break
        if status == "yellow" and busy == 0:
            stable_polls += 1
            if replicas > 0 and stable_polls >= 2:
                break  # only replicas are unassignable (e.g. fewer nodes than copies)
        elif status == "red" and busy == 0 and unassigned > 0:
            stable_polls += 1
            if stable_polls >= 2:
                raise RestoreError(await _allocation_reason(os_admin, concrete_index))
        else:
            stable_polls = 0
        if time.monotonic() >= deadline:
            raise RestoreError("timed out waiting for the restored index to become available")
        await asyncio.sleep(poll_s)

    try:
        counted = await os_admin.count(index=concrete_index)
    except Exception as exc:
        raise RestoreError(_reason(exc)) from exc
    return RestoreResult(concrete_index, int((counted or {}).get("count", 0)), str(status))


async def publish_aliases(os_admin: Any, swaps: Sequence[tuple[str, str, str | None]]) -> None:
    """Point every alias at its new index in one atomic ``_aliases`` request."""
    actions: list[dict[str, Any]] = []
    for alias, new_index, old_index in swaps:
        for name in (alias, new_index, *([old_index] if old_index else [])):
            if not name.startswith("ds_"):
                raise ValueError("refusing to alter a non-dataset index")
        if old_index:
            actions.append({"remove": {"index": old_index, "alias": alias}})
        actions.append({"add": {"index": new_index, "alias": alias}})
    if not actions:
        return
    try:
        await os_admin.indices.update_aliases(body={"actions": actions})
    except Exception as exc:
        raise RestoreError(_reason(exc)) from exc


async def delete_indices(os_admin: Any, names: Sequence[str]) -> None:
    """Delete exact ``ds_*`` index names; missing indices are ignored."""
    exact = [n for n in dict.fromkeys(names) if n]
    for name in exact:
        if not name.startswith("ds_") or any(c in name for c in "*?,"):
            raise ValueError("refusing to delete a non-dataset index")
    if not exact:
        return
    try:
        await os_admin.indices.delete(index=",".join(exact), ignore_unavailable=True)
    except Exception as exc:
        if _status_code(exc) != 404:
            raise RestoreError(_reason(exc)) from exc


async def delete_indices_for_slug(
    os_admin: Any, slug: str, *, keep: Collection[str] = ()
) -> list[str]:
    """Delete every concrete ``ds_{slug}_*`` index except ``keep``; returns the deleted names."""
    if not is_valid_slug(slug):
        raise ValueError("invalid import slug")
    try:
        rows = await os_admin.cat.indices(
            index=slug_pattern(slug), format="json", h="index", expand_wildcards="all"
        )
    except Exception as exc:
        if _status_code(exc) == 404:
            return []
        raise RestoreError(_reason(exc)) from exc
    keep_set = set(keep)
    names = sorted(row["index"] for row in rows or [] if row.get("index") not in keep_set)
    await delete_indices(os_admin, names)
    return names


async def register_repository(os_admin: Any, name: str, body: dict) -> None:
    try:
        await os_admin.snapshot.create_repository(repository=name, body=body)
    except Exception as exc:
        raise RestoreError(_reason(exc)) from exc


async def delete_repository(os_admin: Any, name: str) -> None:
    try:
        await os_admin.snapshot.delete_repository(repository=name)
    except Exception as exc:
        if _status_code(exc) != 404:
            raise RestoreError(_reason(exc)) from exc


async def index_mapping_and_samples(
    os_admin: Any, index: str, n: int = 50
) -> tuple[dict, list[dict]]:
    """``(mappings, sample _source documents)`` for an index or alias."""
    try:
        mapping_response = await os_admin.indices.get_mapping(index=index)
        search_response = await os_admin.search(
            index=index, body={"size": n, "query": {"match_all": {}}}
        )
    except Exception as exc:
        raise RestoreError(_reason(exc)) from exc
    mappings: dict = {}
    for entry in (mapping_response or {}).values():
        mappings = entry.get("mappings") or {}
        break
    samples = [
        hit["_source"]
        for hit in ((search_response or {}).get("hits") or {}).get("hits") or []
        if isinstance(hit.get("_source"), dict)
    ]
    return mappings, samples
