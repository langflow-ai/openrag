from uuid import uuid4

import pytest
from opensearchpy import AsyncOpenSearch
from opensearchpy._async.http_aiohttp import AIOHttpConnection

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.openrag_skip_app_onboard,
]


def _build_admin_opensearch_client():
    from config.settings import (
        IBM_AUTH_ENABLED,
        OPENSEARCH_HOST,
        OPENSEARCH_PASSWORD,
        OPENSEARCH_PORT,
        OPENSEARCH_USERNAME,
    )

    if IBM_AUTH_ENABLED:
        pytest.skip("OSS JWT DLS group matching is not used in IBM auth mode")
    if not OPENSEARCH_PASSWORD:
        pytest.skip("OPENSEARCH_PASSWORD is required for direct OpenSearch DLS integration test")

    return AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        connection_class=AIOHttpConnection,
        scheme="https",
        use_ssl=True,
        verify_certs=False,
        ssl_assert_fingerprint=None,
        http_auth=(OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD),
        http_compress=True,
    )


async def _search_visible_document_ids(opensearch_client, index_name: str) -> set[str]:
    response = await opensearch_client.search(
        index=index_name,
        body={
            "query": {"match_all": {}},
            "sort": [{"document_id": "asc"}],
            "_source": ["document_id"],
            "size": 10,
        },
    )
    return {hit["_source"]["document_id"] for hit in response.get("hits", {}).get("hits", [])}


async def test_opensearch_dls_filters_group_and_user_acl_documents():
    """Prove user and connector principal ACLs are enforced by OpenSearch DLS.

    This test avoids live connector dependencies. The admin client seeds a
    documents* index with ACL-only docs, then a user-scoped OpenSearch client
    searches with JWT subject/email claims and lookup-table principals that
    should and should not match. Connector groups are not passed through JWT
    roles.
    """
    from config.settings import (
        DLS_PRINCIPAL_INDEX_BODY,
        DLS_PRINCIPAL_INDEX_NAME,
        INDEX_BODY,
        clients,
    )
    from session_manager import SessionManager, User
    from utils.opensearch_utils import setup_opensearch_security

    admin_client = _build_admin_opensearch_client()
    try:
        is_reachable = await admin_client.ping()
    except Exception:
        is_reachable = False
    if not is_reachable:
        await admin_client.close()
        pytest.skip("OpenSearch is not reachable")

    index_name = f"documents_group_acl_dls_{uuid4().hex}"
    user_id = f"group-dls-user-{uuid4().hex}"
    user_email = f"{user_id}@example.com"
    matching_group = "g:test:tenant:engineering"
    other_group = "g:test:tenant:sales"
    user_principal = "u:test:tenant:reader"
    other_principal = "u:test:tenant:other"

    try:
        await setup_opensearch_security(admin_client)

        await admin_client.indices.create(index=index_name, body=INDEX_BODY)
        if not await admin_client.indices.exists(index=DLS_PRINCIPAL_INDEX_NAME):
            await admin_client.indices.create(
                index=DLS_PRINCIPAL_INDEX_NAME,
                body=DLS_PRINCIPAL_INDEX_BODY,
            )
        await admin_client.index(
            index=DLS_PRINCIPAL_INDEX_NAME,
            id=user_id,
            body={
                "user_name": user_id,
                "auth_user_id": user_id,
                "auth_email": user_email,
                "provider": "test",
                "principals": [matching_group, user_principal],
                "updated_at": "2026-05-15T00:00:00+00:00",
            },
            refresh=True,
        )
        await admin_client.bulk(
            body=[
                {"index": {"_index": index_name, "_id": "engineering-doc"}},
                {
                    "document_id": "engineering-doc",
                    "filename": "engineering.md",
                    "text": "Visible only to engineering",
                    "owner": "external-owner",
                    "allowed_users": [],
                    "allowed_groups": [matching_group],
                    "allowed_principals": [matching_group],
                },
                {"index": {"_index": index_name, "_id": "subject-doc"}},
                {
                    "document_id": "subject-doc",
                    "filename": "subject.md",
                    "text": "Visible to the matching JWT subject",
                    "owner": "external-owner",
                    "allowed_users": [user_id],
                    "allowed_groups": [],
                    "allowed_principals": [],
                },
                {"index": {"_index": index_name, "_id": "email-doc"}},
                {
                    "document_id": "email-doc",
                    "filename": "email.md",
                    "text": "Visible to the matching JWT email",
                    "owner": "external-owner",
                    "allowed_users": [user_email],
                    "allowed_groups": [],
                    "allowed_principals": [],
                },
                {"index": {"_index": index_name, "_id": "principal-user-doc"}},
                {
                    "document_id": "principal-user-doc",
                    "filename": "principal-user.md",
                    "text": "Visible to the matching DLS user principal",
                    "owner": "external-owner",
                    "allowed_users": [],
                    "allowed_groups": [],
                    "allowed_principals": [user_principal],
                },
                {"index": {"_index": index_name, "_id": "principal-group-doc"}},
                {
                    "document_id": "principal-group-doc",
                    "filename": "principal-group.md",
                    "text": "Visible to the matching DLS group principal lookup",
                    "owner": "external-owner",
                    "allowed_users": [],
                    "allowed_groups": [],
                    "allowed_principals": [matching_group],
                },
                {"index": {"_index": index_name, "_id": "sales-doc"}},
                {
                    "document_id": "sales-doc",
                    "filename": "sales.md",
                    "text": "Visible only to sales",
                    "owner": "external-owner",
                    "allowed_users": [],
                    "allowed_groups": [other_group],
                    "allowed_principals": [other_principal],
                },
            ],
            refresh=True,
        )

        session_manager = SessionManager("test")
        user = User(
            user_id=user_id,
            email=user_email,
            name="Group DLS User",
        )
        token = session_manager.create_opensearch_jwt_token(user, ttl_seconds=120)

        user_client = clients.create_user_opensearch_client(token)
        try:
            assert await _search_visible_document_ids(user_client, index_name) == {
                "email-doc",
                "engineering-doc",
                "principal-group-doc",
                "principal-user-doc",
                "subject-doc",
            }
        finally:
            await user_client.close()
    finally:
        await admin_client.indices.delete(index=index_name, ignore_unavailable=True)
        await admin_client.delete(
            index=DLS_PRINCIPAL_INDEX_NAME,
            id=user_id,
            ignore=[404],
            refresh=True,
        )
        await admin_client.close()
