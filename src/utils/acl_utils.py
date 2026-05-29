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
    """Compute SHA256 hash of ACL fields that are refreshed after ingest."""
    acl_data = {
        "allowed_users": sorted(acl.allowed_users),
        "allowed_groups": sorted(acl.allowed_groups),
        "allowed_principals": sorted(acl.allowed_principals),
        "allowed_principal_labels": _sorted_principal_labels(acl.allowed_principal_labels),
    }
    return hashlib.sha256(json.dumps(acl_data, sort_keys=True).encode()).hexdigest()


def _build_id_query(document_id: str, id_fields: tuple[str, ...]) -> dict:
    """Build an OpenSearch query matching ``document_id`` against one or more fields.

    Non-Langflow connector chunks store the connector source id in
    ``connector_file_id`` while ``document_id`` holds the content hash, whereas
    Langflow chunks and local uploads store the id in ``document_id``. Matching
    multiple fields lets a single id reliably target chunks from either pipeline.
    """
    if len(id_fields) == 1:
        return {"term": {id_fields[0]: document_id}}
    return {
        "bool": {
            "should": [{"term": {field: document_id}} for field in id_fields],
            "minimum_should_match": 1,
        }
    }


async def should_update_acl(
    document_id: str,
    new_acl: DocumentACL,
    opensearch_client,
    id_fields: tuple[str, ...] = ("document_id",),
) -> bool:
    """Return whether indexed ACL lists differ from ``new_acl``.

    The owner field is intentionally not compared here: ownership is set at
    ingest to the authenticated uploading/syncing user and ACL refresh must not
    reassign it to the upstream file author.
    """
    try:
        response = await opensearch_client.search(
            index="documents",
            body={
                "query": _build_id_query(document_id, id_fields),
                "size": 1,
                "_source": [
                    "allowed_users",
                    "allowed_groups",
                    "allowed_principals",
                    "allowed_principal_labels",
                ],
            },
        )

        if not response["hits"]["hits"]:
            return True

        existing_chunk = response["hits"]["hits"][0]["_source"]
        existing_acl = DocumentACL(
            allowed_users=existing_chunk.get("allowed_users", []),
            allowed_groups=existing_chunk.get("allowed_groups", []),
            allowed_principals=existing_chunk.get("allowed_principals", []),
            allowed_principal_labels=existing_chunk.get("allowed_principal_labels", []),
        )

        return compute_acl_hash(existing_acl) != compute_acl_hash(new_acl)

    except Exception as e:
        logger.error("[OPENSEARCH] ACL check failed", document_id=document_id, error=str(e))
        return True


async def update_document_acl(
    document_id: str,
    acl: DocumentACL,
    opensearch_client,
    write_opensearch_client=None,
    id_fields: tuple[str, ...] = ("document_id",),
) -> dict[str, Any]:
    """Update ACL lists for all chunks of a document.

    The user-scoped ``opensearch_client`` is used for visibility/change checks;
    ``write_opensearch_client`` performs the mutation. Only access-list fields
    are updated. ``owner`` is intentionally left untouched.
    """
    should_update = await should_update_acl(
        document_id,
        acl,
        opensearch_client,
        id_fields=id_fields,
    )

    if not should_update:
        return {"status": "unchanged", "chunks_updated": 0}

    write_client = write_opensearch_client
    if write_client is None:
        raise RuntimeError("Backend OpenSearch write client is unavailable")

    try:
        response = await write_client.update_by_query(
            index="documents",
            body={
                "query": _build_id_query(document_id, id_fields),
                "script": {
                    "source": """
                        ctx._source.allowed_users = params.allowed_users;
                        ctx._source.allowed_groups = params.allowed_groups;
                        ctx._source.allowed_principals = params.allowed_principals;
                        ctx._source.allowed_principal_labels = params.allowed_principal_labels;
                    """,
                    "params": {
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
    id_fields: tuple[str, ...] = ("document_id",),
) -> dict[str, Any]:
    """Batch update ACL lists for multiple documents."""
    if not acl_updates:
        return {"status": "no_updates", "documents_updated": 0, "chunks_updated": 0}

    check_tasks = [
        should_update_acl(doc_id, acl, opensearch_client, id_fields=id_fields)
        for doc_id, acl in acl_updates
    ]
    should_update_flags = await asyncio.gather(*check_tasks)

    changed = [
        (doc_id, acl)
        for (doc_id, acl), should_update in zip(acl_updates, should_update_flags, strict=True)
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

    update_tasks = [
        write_client.update_by_query(
            index="documents",
            body={
                "query": _build_id_query(doc_id, id_fields),
                "script": {
                    "source": """
                        ctx._source.allowed_users = params.allowed_users;
                        ctx._source.allowed_groups = params.allowed_groups;
                        ctx._source.allowed_principals = params.allowed_principals;
                        ctx._source.allowed_principal_labels = params.allowed_principal_labels;
                    """,
                    "params": {
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
