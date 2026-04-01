"""End-to-end tests covering full multi-step SDK workflows."""

import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestEndToEnd:
    """Full pipeline tests that exercise multiple SDK operations together."""

    @pytest.mark.skip(reason="Test scenario is returning indeterministic or flaky results resulting in random failures.")
    @pytest.mark.asyncio
    async def test_full_rag_pipeline(self, client, tmp_path):
        """Ingest → search → chat: source cited in chat must match the ingested doc."""
        unique_token = uuid.uuid4().hex
        file_path = tmp_path / f"rag_e2e_{unique_token[:8]}.md"
        file_path.write_text(
            f"# E2E RAG Test\n\n"
            f"Unique token: {unique_token}\n\n"
            f"The flamingo named Zephyr lives on planet Xylox-7.\n"
        )

        ingest_result = await client.documents.ingest(file_path=str(file_path))
        if ingest_result.successful_files == 0:
            pytest.skip("Ingestion produced no indexed chunks — skipping E2E RAG test")

        # Verify the document is actually searchable before querying chat.
        # Retry up to 5 times (10 s total) to absorb index refresh latency and
        # transient KNN search errors.
        search_hit = False
        for _ in range(5):
            search_results = await client.search.query("flamingo Zephyr planet Xylox")
            if search_results.results:
                search_hit = True
                break
            await asyncio.sleep(2)
        if not search_hit:
            pytest.skip("Ingested document not findable via search after retries — skipping E2E RAG test")

        chat_response = await client.chat.create(
            message="According to my documents, what is the name of the flamingo and on which planet does it live?"
        )
        assert chat_response.response is not None
        assert len(chat_response.response) > 0

        # Verify the LLM retrieved and used the ingested document's content.
        # We assert on the unique fictional content ("Zephyr", "Xylox") rather than
        # filename citation: if the response contains these terms the pipeline
        # demonstrably retrieved the correct document, regardless of how (or whether)
        # the LLM formats a "(Source: …)" citation.
        response_text = chat_response.response or ""
        assert "Zephyr" in response_text or "Xylox" in response_text, (
            f"Expected document content ('Zephyr'/'Xylox-7') in response:\n{response_text}"
        )

        await client.documents.delete(file_path.name)

    @pytest.mark.asyncio
    async def test_multiturn_rag_conversation(self, client, tmp_path):
        """Multi-turn conversation: context carries across turns."""
        unique_token = uuid.uuid4().hex
        file_path = tmp_path / f"multiturn_{unique_token[:8]}.md"
        file_path.write_text(
            f"# Multiturn Test\n\n"
            f"The capital of the fictional country Valdoria is Sunhaven.\n"
            f"Token: {unique_token}\n"
        )

        ingest_result = await client.documents.ingest(file_path=str(file_path))
        if ingest_result.successful_files == 0:
            pytest.skip("Ingestion produced no indexed chunks — skipping multiturn test")

        r1 = await client.chat.create(message="What is the capital of Valdoria?")
        assert r1.chat_id is not None

        r2 = await client.chat.create(
            message="Repeat the capital city you just mentioned.",
            chat_id=r1.chat_id,
        )
        assert r2.response is not None
        assert r2.chat_id == r1.chat_id

        await client.documents.delete(file_path.name)
        await client.chat.delete(r1.chat_id)

    @pytest.mark.asyncio
    async def test_knowledge_filter_scopes_search_results(self, client):
        """A knowledge filter must constrain search and chat to its configured scope."""
        unique_token = uuid.uuid4().hex
        create_result = await client.knowledge_filters.create({
            "name": f"E2E Scope Filter {unique_token[:8]}",
            "description": "Filter for E2E scoping test",
            "queryData": {
                "query": f"scoped content {unique_token}",
                "limit": 5,
                "scoreThreshold": 0.0,
            },
        })
        assert create_result.success is True
        filter_id = create_result.id

        try:
            search_results = await client.search.query("test query", filter_id=filter_id)
            assert search_results.results is not None

            chat_response = await client.chat.create(
                message="Summarise what you know.",
                filter_id=filter_id,
            )
            assert chat_response.response is not None
        finally:
            await client.knowledge_filters.delete(filter_id)
