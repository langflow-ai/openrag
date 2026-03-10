"""
ACL utilities for managing document access control lists.

This module provides hash-based ACL change detection and bulk update operations
to minimize write amplification when ACLs change.
"""

import hashlib
import json
import asyncio
from typing import Dict, List, Tuple, Optional
from src.connectors.base import DocumentACL


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
    }
    return hashlib.sha256(
        json.dumps(acl_data, sort_keys=True).encode()
    ).hexdigest()


async def should_update_acl(
    document_id: str,
    new_acl: DocumentACL,
    opensearch_client
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
                "query": {"term": {"document_id": document_id}},
                "size": 1,
                "_source": [
                    "owner",
                    "allowed_users",
                    "allowed_groups",
                ]
            }
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
        )

        existing_hash = compute_acl_hash(existing_acl)
        new_hash = compute_acl_hash(new_acl)

        return existing_hash != new_hash

    except Exception as e:
        # On error, assume update needed to be safe
        print(f"Error checking ACL for {document_id}: {e}")
        return True


async def update_document_acl(
    document_id: str,
    acl: DocumentACL,
    opensearch_client
) -> Dict[str, any]:
    """
    Update ACL for all chunks of a document.

    Uses hash-based skip optimization: queries one chunk to check if ACL changed,
    only updates if changed. When updating, uses bulk update_by_query for efficiency.

    Args:
        document_id: Document identifier
        acl: New ACL to apply
        opensearch_client: OpenSearch client instance

    Returns:
        Dict with status ("unchanged" or "updated") and chunks_updated count
    """
    # Check if ACL changed (queries one chunk)
    should_update = await should_update_acl(document_id, acl, opensearch_client)

    if not should_update:
        return {"status": "unchanged", "chunks_updated": 0}

    # Bulk update all chunks for this document
    try:
        response = await opensearch_client.update_by_query(
            index="documents",
            body={
                "query": {"term": {"document_id": document_id}},
                "script": {
                    "source": """
                        ctx._source.owner = params.owner;
                        ctx._source.allowed_users = params.allowed_users;
                        ctx._source.allowed_groups = params.allowed_groups;
                    """,
                    "params": {
                        "owner": acl.owner,
                        "allowed_users": acl.allowed_users,
                        "allowed_groups": acl.allowed_groups,
                    }
                }
            }
        )

        return {
            "status": "updated",
            "chunks_updated": response.get("updated", 0)
        }

    except Exception as e:
        print(f"Error updating ACL for {document_id}: {e}")
        return {"status": "error", "chunks_updated": 0, "error": str(e)}


async def batch_update_acls(
    acl_updates: List[Tuple[str, DocumentACL]],
    opensearch_client
) -> Dict[str, any]:
    """
    Batch update ACLs for multiple documents.

    Optimizations:
    - Parallel ACL change detection (query one chunk per document)
    - Skip unchanged ACLs (95%+ of webhook notifications)
    - Parallel bulk updates for changed ACLs

    Args:
        acl_updates: List of (document_id, acl) tuples
        opensearch_client: OpenSearch client instance

    Returns:
        Dict with status, documents_updated count, and chunks_updated count
    """
    if not acl_updates:
        return {"status": "no_updates", "documents_updated": 0, "chunks_updated": 0}

    # Filter to only changed ACLs (parallel chunk queries)
    check_tasks = [
        should_update_acl(doc_id, acl, opensearch_client)
        for doc_id, acl in acl_updates
    ]
    should_update_flags = await asyncio.gather(*check_tasks)

    # Filter to documents with changed ACLs
    changed = [
        (doc_id, acl)
        for (doc_id, acl), should_update in zip(acl_updates, should_update_flags)
        if should_update
    ]

    if not changed:
        return {
            "status": "no_changes",
            "documents_updated": 0,
            "chunks_updated": 0,
            "skipped": len(acl_updates)
        }

    # Bulk update chunks for each document (parallelized)
    update_tasks = [
        opensearch_client.update_by_query(
            index="documents",
            body={
                "query": {"term": {"document_id": doc_id}},
                "script": {
                    "source": """
                        ctx._source.owner = params.owner;
                        ctx._source.allowed_users = params.allowed_users;
                        ctx._source.allowed_groups = params.allowed_groups;
                    """,
                    "params": {
                        "owner": acl.owner,
                        "allowed_users": acl.allowed_users,
                        "allowed_groups": acl.allowed_groups,
                    }
                }
            }
        )
        for doc_id, acl in changed
    ]

    try:
        results = await asyncio.gather(*update_tasks, return_exceptions=True)

        # Count successful updates
        total_chunks_updated = 0
        errors = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append(str(result))
            else:
                total_chunks_updated += result.get("updated", 0)

        return {
            "status": "updated" if not errors else "partial",
            "documents_updated": len(changed) - len(errors),
            "chunks_updated": total_chunks_updated,
            "skipped": len(acl_updates) - len(changed),
            "errors": errors if errors else None
        }

    except Exception as e:
        return {
            "status": "error",
            "documents_updated": 0,
            "chunks_updated": 0,
            "error": str(e)
        }
