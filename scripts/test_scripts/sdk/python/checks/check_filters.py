"""Checks for client.knowledge_filters — CRUD and filter_id scoping in search/chat.

The scoping checks verify the filter actually constrains retrieval to the
filenames in its data_sources (pattern from tests/integration/sdk/test_filters.py),
not just that the parameter is accepted.
"""

import uuid

from harness import Check, Context

from checks.common import make_doc, register_doc_cleanup


async def crud(ctx: Context) -> None:
    name = f"SDK Smoke Filter {uuid.uuid4().hex[:8]}"
    created = await ctx.client.knowledge_filters.create(
        {
            "name": name,
            "description": "Filter created by SDK smoke tests",
            "queryData": {"query": "test documents", "limit": 10, "scoreThreshold": 0.5},
        }
    )
    assert created.success is True, f"create failed: {created.error}"
    assert created.id, "create returned no id"
    filter_id = created.id
    # Registered even though the happy path deletes it below — guards against
    # a failure between create and delete leaving the filter behind.
    ctx.add_cleanup(
        f"delete filter {filter_id}",
        lambda: ctx.client.knowledge_filters.delete(filter_id),
    )

    found = await ctx.client.knowledge_filters.search(name)
    assert any(f.name == name for f in found), "created filter not found via search"

    fetched = await ctx.client.knowledge_filters.get(filter_id)
    assert fetched is not None and fetched.id == filter_id
    assert fetched.name == name

    updated_desc = "Updated description from SDK smoke tests"
    ok = await ctx.client.knowledge_filters.update(filter_id, {"description": updated_desc})
    assert ok is True, "update returned False"
    refetched = await ctx.client.knowledge_filters.get(filter_id)
    assert refetched.description == updated_desc, "updated description not persisted"

    deleted = await ctx.client.knowledge_filters.delete(filter_id)
    assert deleted is True, "delete returned False"
    assert await ctx.client.knowledge_filters.get(filter_id) is None, (
        "filter still retrievable after delete"
    )


async def scope_setup(ctx: Context) -> None:
    """Ingest an alpha/beta document pair and a filter scoped to alpha only."""
    alpha, _ = make_doc(ctx, "scope_alpha", "This document discusses purple elephants.")
    beta, _ = make_doc(ctx, "scope_beta", "This document discusses yellow tigers.")
    register_doc_cleanup(ctx, alpha.name)
    register_doc_cleanup(ctx, beta.name)
    await ctx.client.documents.ingest(file_path=str(alpha))
    await ctx.client.documents.ingest(file_path=str(beta))

    created = await ctx.client.knowledge_filters.create(
        {
            "name": f"SDK smoke scope filter {uuid.uuid4().hex[:6]}",
            "description": "Auto-created by SDK smoke tests",
            "queryData": {
                "query": "",
                "filters": {
                    "data_sources": [alpha.name],
                    "document_types": ["*"],
                    "owners": ["*"],
                    "connector_types": ["*"],
                },
                "limit": 10,
                "scoreThreshold": 0,
            },
        }
    )
    assert created.success is True, f"scope filter creation failed: {created.error}"
    assert created.id, "scope filter creation returned no id"
    ctx.add_cleanup(
        f"delete filter {created.id}",
        lambda: ctx.client.knowledge_filters.delete(created.id),
    )
    ctx.shared["scope"] = {
        "filter_id": created.id,
        "alpha": alpha.name,
        "beta": beta.name,
    }


async def filter_id_in_search(ctx: Context) -> None:
    scope = ctx.shared["scope"]
    results = await ctx.client.search.query("animals", filter_id=scope["filter_id"])
    assert results.results is not None
    leaked = [r.filename for r in results.results if r.filename == scope["beta"]]
    assert not leaked, f"filter leaked: search returned out-of-scope file {leaked}"


async def filter_id_in_chat(ctx: Context) -> None:
    scope = ctx.shared["scope"]
    response = await ctx.client.chat.create(
        message="What animals appear in these documents?",
        filter_id=scope["filter_id"],
    )
    if response.chat_id:
        ctx.add_cleanup(
            f"delete conversation {response.chat_id}",
            lambda: ctx.client.chat.delete(response.chat_id),
        )
    assert response.sources is not None
    source_names = [s.filename for s in response.sources]
    assert scope["beta"] not in source_names, (
        f"filter leaked: chat cited out-of-scope file in {source_names}"
    )


CHECKS = [
    Check("filters.crud", crud),
    Check("filters.scope_setup", scope_setup),
    Check(
        "filters.filter_id_in_search",
        filter_id_in_search,
        requires=["filters.scope_setup"],
    ),
    Check(
        "filters.filter_id_in_chat",
        filter_id_in_chat,
        requires=["filters.scope_setup"],
    ),
]
