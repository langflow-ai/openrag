from unittest.mock import AsyncMock

import pytest

from connectors.base import DocumentACL
from utils.acl_utils import batch_update_acls, update_document_acl


@pytest.mark.asyncio
async def test_update_document_acl_passes_refresh_true():
    opensearch_client = AsyncMock()
    # Return different ACL hash to trigger update
    opensearch_client.search = AsyncMock(
        return_value={
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "allowed_users": ["old_user"],
                            "allowed_groups": [],
                            "allowed_principals": [],
                            "allowed_principal_labels": [],
                        }
                    }
                ]
            }
        }
    )
    write_client = AsyncMock()
    write_client.update_by_query = AsyncMock(return_value={"updated": 2})

    acl = DocumentACL(allowed_users=["new_user"])
    result = await update_document_acl(
        document_id="doc-123",
        acl=acl,
        opensearch_client=opensearch_client,
        write_opensearch_client=write_client,
    )

    assert result["status"] == "updated"
    assert result["chunks_updated"] == 2
    write_client.update_by_query.assert_awaited_once()
    assert write_client.update_by_query.await_args.kwargs.get("refresh") is True


@pytest.mark.asyncio
async def test_batch_update_acls_passes_refresh_true():
    opensearch_client = AsyncMock()
    # Return different ACL hash to trigger update
    opensearch_client.search = AsyncMock(
        return_value={
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "allowed_users": ["old_user"],
                            "allowed_groups": [],
                            "allowed_principals": [],
                            "allowed_principal_labels": [],
                        }
                    }
                ]
            }
        }
    )
    write_client = AsyncMock()
    write_client.update_by_query = AsyncMock(return_value={"updated": 1})

    acl_updates = [
        ("doc-1", DocumentACL(allowed_users=["user-1"])),
        ("doc-2", DocumentACL(allowed_users=["user-2"])),
    ]
    result = await batch_update_acls(
        acl_updates=acl_updates,
        opensearch_client=opensearch_client,
        write_opensearch_client=write_client,
    )

    assert result["status"] == "updated"
    assert result["documents_updated"] == 2
    assert write_client.update_by_query.await_count == 2
    for call in write_client.update_by_query.await_args_list:
        assert call.kwargs.get("refresh") is True
