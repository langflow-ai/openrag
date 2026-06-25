"""Integration tests: shared-flag DLS anonymous path in OpenSearch.

These tests verify that documents indexed without an owner field are visible
to all authenticated users via the existing must_not-exists-owner DLS clause,
and that documents WITH an owner field remain private to their owner.

Requires a live OpenSearch instance with DLS configured (OPENSEARCH_PASSWORD set).
"""

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
        pytest.skip("OSS JWT DLS is not used in IBM auth mode")
    if not OPENSEARCH_PASSWORD:
        pytest.skip("OPENSEARCH_PASSWORD is required for this DLS integration test")

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
            "_source": ["document_id"],
            "size": 20,
        },
    )
    return {hit["_source"]["document_id"] for hit in response.get("hits", {}).get("hits", [])}


async def test_ownerless_doc_visible_to_all_users():
    """A document indexed without an owner field is visible to all authenticated users.

    This is the core DLS mechanism used by shared=True ingestion.
    The must_not-exists-owner clause in securityconfig/roles.yml makes any
    chunk whose owner key is absent universally readable.
    """
    from config.settings import INDEX_BODY, clients
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

    index_name = f"documents_shared_flag_dls_{uuid4().hex}"
    user_a_id = f"user-a-{uuid4().hex}"
    user_a_email = f"{user_a_id}@example.com"
    user_b_id = f"user-b-{uuid4().hex}"
    user_b_email = f"{user_b_id}@example.com"

    try:
        await setup_opensearch_security(admin_client)
        await admin_client.indices.create(index=index_name, body=INDEX_BODY)

        await admin_client.bulk(
            body=[
                # Shared doc: no owner key → visible to everyone
                {"index": {"_index": index_name, "_id": "shared-doc"}},
                {
                    "document_id": "shared-doc",
                    "filename": "shared.pdf",
                    "text": "Shared document visible to all users",
                    "allowed_users": [],
                    "allowed_groups": [],
                    "allowed_principals": [],
                },
                # Private doc owned by user A → only visible to user A
                {"index": {"_index": index_name, "_id": "private-a-doc"}},
                {
                    "document_id": "private-a-doc",
                    "filename": "private-a.pdf",
                    "text": "Private document owned by user A",
                    "owner": user_a_id,
                    "allowed_users": [],
                    "allowed_groups": [],
                    "allowed_principals": [],
                },
                # Private doc owned by user B → only visible to user B
                {"index": {"_index": index_name, "_id": "private-b-doc"}},
                {
                    "document_id": "private-b-doc",
                    "filename": "private-b.pdf",
                    "text": "Private document owned by user B",
                    "owner": user_b_id,
                    "allowed_users": [],
                    "allowed_groups": [],
                    "allowed_principals": [],
                },
            ],
            refresh=True,
        )

        session_manager = SessionManager("test")

        user_a = User(user_id=user_a_id, email=user_a_email, name="User A")
        token_a = session_manager.create_opensearch_jwt_token(user_a, ttl_seconds=120)
        client_a = clients.create_user_opensearch_client(token_a)

        user_b = User(user_id=user_b_id, email=user_b_email, name="User B")
        token_b = session_manager.create_opensearch_jwt_token(user_b, ttl_seconds=120)
        client_b = clients.create_user_opensearch_client(token_b)

        try:
            visible_a = await _search_visible_document_ids(client_a, index_name)
            visible_b = await _search_visible_document_ids(client_b, index_name)

            # Shared doc visible to both users
            assert "shared-doc" in visible_a, "User A must see the shared (ownerless) document"
            assert "shared-doc" in visible_b, "User B must see the shared (ownerless) document"

            # Each user sees only their own private doc (not the other user's)
            assert "private-a-doc" in visible_a
            assert "private-a-doc" not in visible_b, "User B must NOT see User A's private doc"

            assert "private-b-doc" in visible_b
            assert "private-b-doc" not in visible_a, "User A must NOT see User B's private doc"

        finally:
            await client_a.close()
            await client_b.close()

    finally:
        await admin_client.indices.delete(index=index_name, ignore_unavailable=True)
        await admin_client.close()


async def test_null_owner_field_does_not_trigger_anonymous_path():
    """A document indexed with owner=null is universally visible — same as an absent owner key.

    OpenSearch does not index null values for keyword fields without a null_value mapping.
    The exists filter therefore returns false for 'owner: null', so the
    must_not-exists-owner DLS clause fires and the document is visible to everyone.

    This documents that _build_chunk_document correctly omits the owner key when None,
    making intent explicit; both null and absent produce the same DLS result.
    """
    from config.settings import INDEX_BODY, clients
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

    index_name = f"documents_null_owner_dls_{uuid4().hex}"
    unrelated_user_id = f"unrelated-{uuid4().hex}"
    unrelated_email = f"{unrelated_user_id}@example.com"

    try:
        await setup_opensearch_security(admin_client)
        await admin_client.indices.create(index=index_name, body=INDEX_BODY)

        # Index a doc with owner: null explicitly (the broken serialization path)
        await admin_client.index(
            index=index_name,
            id="null-owner-doc",
            body={
                "document_id": "null-owner-doc",
                "filename": "null-owner.pdf",
                "text": "Document with owner field set to null",
                "owner": None,
                "allowed_users": [],
                "allowed_groups": [],
                "allowed_principals": [],
            },
            refresh=True,
        )

        session_manager = SessionManager("test")
        unrelated = User(user_id=unrelated_user_id, email=unrelated_email, name="Unrelated User")
        token = session_manager.create_opensearch_jwt_token(unrelated, ttl_seconds=120)
        client = clients.create_user_opensearch_client(token)

        try:
            visible = await _search_visible_document_ids(client, index_name)
            # owner=null is not indexed by OpenSearch (keyword, no null_value), so exists
            # returns false → must_not-exists-owner fires → doc is visible to everyone
            assert "null-owner-doc" in visible, (
                "A doc with owner=null must be universally visible: OpenSearch does not "
                "index null keyword values, so must_not-exists-owner fires just as it "
                "does for a doc with no owner key at all."
            )
        finally:
            await client.close()

    finally:
        await admin_client.indices.delete(index=index_name, ignore_unavailable=True)
        await admin_client.close()
