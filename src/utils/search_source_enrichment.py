"""
Resolve knowledge filter ``data_sources`` / refs against the live OpenSearch index so
searches still hit documents after rename (label ≠ indexed filename, missing ids, etc.).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from config.settings import get_index_name
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _filename_candidate_strings(value: str) -> List[str]:
    """Try exact name, txt/md aliases, stem, and common extensions for bare stems."""
    from utils.file_utils import get_filename_aliases

    v = (value or "").strip()
    if not v:
        return []
    out: List[str] = []
    seen = set()
    for cand in list(dict.fromkeys(get_filename_aliases(v) + [v])):
        if cand and cand not in seen:
            seen.add(cand)
            out.append(cand)
    if "." not in v:
        for ext in (".pdf", ".md", ".txt", ".docx", ".csv", ".json", ".html"):
            x = v + ext
            if x not in seen:
                seen.add(x)
                out.append(x)
    return out


async def _sample_chunk_for_source_value(
    opensearch_client,
    index_name: str,
    value: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Return (canonical_filename, document_id) for one UI source token (filename,
    bare stem, or stored document_id).
    """
    v = (value or "").strip()
    if not v:
        return None, None

    # 1) Token might already be the indexed document_id
    try:
        resp = await opensearch_client.search(
            index=index_name,
            body={
                "query": {"term": {"document_id": v}},
                "size": 1,
                "_source": ["filename", "document_id"],
            },
        )
        hits = resp.get("hits", {}).get("hits", [])
        if hits:
            src = hits[0].get("_source") or {}
            fn = (src.get("filename") or "").strip() or None
            did = src.get("document_id")
            did_s = str(did).strip() if did is not None else None
            if not did_s:
                did_s = None
            # Do not fall back to the search token v: _source may omit document_id even
            # when the term query matched (alias / legacy mapping); keep parallel with
            # the filename hit path below.
            return fn or None, did_s
    except Exception as e:
        logger.debug("document_id lookup failed", value=v, error=str(e))

    # 2) Filename variants (indexed name may include extension)
    for cand in _filename_candidate_strings(v):
        try:
            resp = await opensearch_client.search(
                index=index_name,
                body={
                    "query": {"term": {"filename": cand}},
                    "size": 1,
                    "_source": ["filename", "document_id"],
                },
            )
            hits = resp.get("hits", {}).get("hits", [])
            if hits:
                src = hits[0].get("_source") or {}
                fn = (src.get("filename") or "").strip() or cand
                did = src.get("document_id")
                did_s = str(did).strip() if did is not None else None
                if not did_s:
                    did_s = None
                return fn, did_s
        except Exception as e:
            logger.debug("filename lookup failed", candidate=cand, error=str(e))

    return None, None


async def enrich_search_filters_source_dimension(
    session_manager,
    user_id: Optional[str],
    jwt_token: Optional[str],
    filters: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Populate ``data_source_refs`` with ``document_id`` + canonical filename by querying
    the corpus. Runs for legacy filters (refs missing) and fills ids on incomplete refs.
    """
    if not filters:
        return filters

    out = dict(filters)
    refs_in = out.get("data_source_refs")
    ds = filters.get("data_sources")

    has_refs = isinstance(refs_in, list) and len(refs_in) > 0
    legacy_specific_sources = (
        isinstance(ds, list)
        and "*" not in ds
        and not has_refs
    )

    if not has_refs and not legacy_specific_sources:
        return out

    try:
        opensearch_client = session_manager.get_user_opensearch_client(
            user_id, jwt_token
        )
        index_name = get_index_name()
    except Exception as e:
        logger.warning("enrich_search_filters: no opensearch client", error=str(e))
        return out

    async def _lookup_token(token: str) -> Tuple[Optional[str], Optional[str]]:
        if not token:
            return None, None
        return await _sample_chunk_for_source_value(opensearch_client, index_name, token)

    if has_refs:
        prepared_refs: List[Any] = []
        lookups = []
        for ref in refs_in:
            if not isinstance(ref, dict):
                prepared_refs.append(ref)
                continue
            r = dict(ref)
            token_raw = r.get("document_id")
            if token_raw is None:
                token_raw = r.get("filename")
            token = str(token_raw).strip() if token_raw is not None else ""
            prepared_refs.append(r)
            lookups.append(_lookup_token(token))
        lookup_results = await asyncio.gather(*lookups)
        new_refs: List[Any] = []
        lookup_idx = 0
        for ref in prepared_refs:
            if not isinstance(ref, dict):
                new_refs.append(ref)
                continue
            r = dict(ref)
            cf, did = lookup_results[lookup_idx]
            lookup_idx += 1
            if did:
                r["document_id"] = did
            if cf:
                r["filename"] = cf
            new_refs.append(r)
        out["data_source_refs"] = new_refs
        return out

    # Legacy: only data_sources tokens — build refs from index lookups
    source_values: List[str] = []
    for val in ds:
        if not isinstance(val, str):
            continue
        vs = val.strip()
        if not vs or vs == "*":
            continue
        source_values.append(vs)
    lookup_results = await asyncio.gather(*[_lookup_token(vs) for vs in source_values])
    new_refs = []
    for vs, (cf, did) in zip(source_values, lookup_results):
        new_refs.append(
            {
                "filename": cf or vs,
                "document_id": did,
            }
        )
    if new_refs:
        out["data_source_refs"] = new_refs
    return out
