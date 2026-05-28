"""
ACL utilities for managing document access control lists.

This module provides hash-based ACL change detection and bulk update operations
to minimize write amplification when ACLs change.
"""

import asyncio
import hashlib
import json
from typing import Any

from src.connectors.base import DocumentACL
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _sorted_principal_labels(labels: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return sorted(
        [label for label in labels or [] if isinstance(label, dict)],
        key=lambda label: json.dumps(label, sort_keys=True),
    )


def compute_acl_hash(acl: DocumentACL) -> str:
    """
    Compute SHA256 hash of ACL for change detection.

    Args:
        acl: DocumentACL instance

    Returns:
        Hexadecimal hash string
    """
    acl_data = {
        "owner": acl.owner,
        "allowed_users": sorted(acl.allowed_users),
        "allowed_groups": sorted(acl.allowed_groups),
        "allowed_principals": sorted(acl.allowed_principals),
        "allowed_principal_labels": _sorted_principal_labels(acl.allowed_principal_labels),
    }
    return hashlib.sha256(json.dumps(acl_data, sort_keys=True).encode()).hexdigest()


async def should_update_acl(
    document_id: str,
    new_acl: DocumentACL,
    opensearch_client,
    field: str = "document_id",
) -> bool:
    """
    Check if ACL has changed by querying one chunk and comparing hashes.

    This optimization queries only a single chunk instead of updating all chunks,
    enabling efficient skip when ACLs haven't changed (most common case).

    Args:
        document_id: Document identifier
        new_acl: New ACL to compare against
        opensearch_client: OpenSearch client instance

    Returns:
        True if ACL has changed and update is needed, False otherwise
    """
    try:
        # Query one chunk for this document
        response = await opensearch_client.search(
            index="documents",
            body={
                "query": {"term": {field: document_id}},
                "size": 1,
                "_source": [
                    "owner",
                    "allowed_users",
                    "allowed_groups",
                    "allowed_principals",
                    "allowed_principal_labels",
                ],
            },
        )

        if not response["hits"]["hits"]:
            # New document, need to index
            return True

        existing_chunk = response["hits"]["hits"][0]["_source"]

        # Reconstruct existing ACL and compute hash
        existing_acl = DocumentACL(
            owner=existing_chunk.get("owner"),
            allowed_users=existing_chunk.get("allowed_users", []),
            allowed_groups=existing_chunk.get("allowed_groups", []),
            allowed_principals=existing_chunk.get("allowed_principals", []),
            allowed_principal_labels=existing_chunk.get("allowed_principal_labels", []),
        )

        existing_hash = compute_acl_hash(existing_acl)
        new_hash = compute_acl_hash(new_acl)

        return existing_hash != new_hash

    except Exception as e:
        # On error, assume update needed to be safe
        logger.error("[OPENSEARCH] ACL check failed", document_id=document_id, error=str(e))
        return True


async def update_document_acl(
    document_id: str,
    acl: DocumentACL,
    opensearch_client,
    write_opensearch_client=None,
    field: str = "document_id",
) -> dict[str, Any]:
    """
    Update ACL for all chunks of a document.

    Uses hash-based skip optimization: queries one chunk to check if ACL changed,
    only updates if changed. When updating, uses bulk update_by_query for efficiency.

    Args:
        document_id: Document identifier
        acl: New ACL to apply
        opensearch_client: user-scoped OpenSearch client for visibility checks
        write_opensearch_client: trusted OpenSearch client for mutations

    Returns:
        Dict with status ("unchanged" or "updated") and chunks_updated count
    """
    # Check if ACL changed (queries one chunk)
    should_update = await should_update_acl(document_id, acl, opensearch_client, field=field)

    if not should_update:
        return {"status": "unchanged", "chunks_updated": 0}

    write_client = write_opensearch_client
    if write_client is None:
        raise RuntimeError("Backend OpenSearch write client is unavailable")

    # Bulk update all chunks for this document
    try:
        response = await write_client.update_by_query(
            index="documents",
            body={
                "query": {"term": {field: document_id}},
                "script": {
                    "source": """
                        ctx._source.owner = params.owner;
                        ctx._source.allowed_users = params.allowed_users;
                        ctx._source.allowed_groups = params.allowed_groups;
                        ctx._source.allowed_principals = params.allowed_principals;
                        ctx._source.allowed_principal_labels = params.allowed_principal_labels;
                    """,
                    "params": {
                        "owner": acl.owner,
                        "allowed_users": acl.allowed_users,
                        "allowed_groups": acl.allowed_groups,
                        "allowed_principals": acl.allowed_principals,
                        "allowed_principal_labels": acl.allowed_principal_labels,
                    },
                },
            },
        )

        return {"status": "updated", "chunks_updated": response.get("updated", 0)}

    except Exception as e:
        logger.error("[OPENSEARCH] ACL update failed", document_id=document_id, error=str(e))
        return {"status": "error", "chunks_updated": 0, "error": str(e)}


async def batch_update_acls(
    acl_updates: list[tuple[str, DocumentACL]],
    opensearch_client,
    write_opensearch_client=None,
) -> dict[str, Any]:
    """
    Batch update ACLs for multiple documents.

    Optimizations:
    - Parallel ACL change detection (query one chunk per document)
    - Skip unchanged ACLs (95%+ of webhook notifications)
    - Parallel bulk updates for changed ACLs

    Args:
        acl_updates: List of (document_id, acl) tuples
        opensearch_client: user-scoped OpenSearch client for visibility checks
        write_opensearch_client: trusted OpenSearch client for mutations

    Returns:
        Dict with status, documents_updated count, and chunks_updated count
    """
    if not acl_updates:
        return {"status": "no_updates", "documents_updated": 0, "chunks_updated": 0}

    # Filter to only changed ACLs (parallel chunk queries)
    check_tasks = [should_update_acl(doc_id, acl, opensearch_client) for doc_id, acl in acl_updates]
    should_update_flags = await asyncio.gather(*check_tasks)

    # Filter to documents with changed ACLs
    changed = [
        (doc_id, acl)
        for (doc_id, acl), should_update in zip(acl_updates, should_update_flags, strict=False)
        if should_update
    ]

    if not changed:
        return {
            "status": "no_changes",
            "documents_updated": 0,
            "chunks_updated": 0,
            "skipped": len(acl_updates),
        }

    write_client = write_opensearch_client
    if write_client is None:
        raise RuntimeError("Backend OpenSearch write client is unavailable")

    # Bulk update chunks for each document (parallelized)
    update_tasks = [
        write_client.update_by_query(
            index="documents",
            body={
                "query": {"term": {"document_id": doc_id}},
                "script": {
                    "source": """
                        ctx._source.owner = params.owner;
                        ctx._source.allowed_users = params.allowed_users;
                        ctx._source.allowed_groups = params.allowed_groups;
                        ctx._source.allowed_principals = params.allowed_principals;
                        ctx._source.allowed_principal_labels = params.allowed_principal_labels;
                    """,
                    "params": {
                        "owner": acl.owner,
                        "allowed_users": acl.allowed_users,
                        "allowed_groups": acl.allowed_groups,
                        "allowed_principals": acl.allowed_principals,
                        "allowed_principal_labels": acl.allowed_principal_labels,
                    },
                },
            },
        )
        for doc_id, acl in changed
    ]

    try:
        results = await asyncio.gather(*update_tasks, return_exceptions=True)

        # Count successful updates
        total_chunks_updated = 0
        errors = []
        for result in results:
            if isinstance(result, BaseException):
                errors.append(str(result))
            else:
                total_chunks_updated += result.get("updated", 0)

        return {
            "status": "updated" if not errors else "partial",
            "documents_updated": len(changed) - len(errors),
            "chunks_updated": total_chunks_updated,
            "skipped": len(acl_updates) - len(changed),
            "errors": errors if errors else None,
        }

    except Exception as e:
        return {"status": "error", "documents_updated": 0, "chunks_updated": 0, "error": str(e)}
