"""Ingestion and the dimension probe embed through the LLM gateway.

Both call sites used to reach `clients.patched_embedding_client` — a LiteLLM-
patched `AsyncOpenAI` whose provider credentials come from process-global
environment written once per process. That environment is shared by every
provider, is set but never unset when a provider is deconfigured, and is
populated lazily on first client use.

Ingestion did have a gateway path, but it was gated on
`litellm_provider_key(provider) != provider` — true only for providers that
route under a *different* LiteLLM key (`watsonx_onprem`, `rhoai`). So whether
ingestion resolved credentials from config or from stale process environment
depended on an unrelated routing detail. The dimension probe had no gateway
path at all, which meant the vector width written into the index mapping could
be probed against a different endpoint than the one that later embedded the
documents.

These tests pin the fix: every provider goes through the gateway, and the id it
is given names the provider explicitly.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.llm_gateway import qualified_model_id  # noqa: E402


class TestQualifiedModelId:
    """The id handed to the gateway names the provider the caller resolved."""

    def test_an_untagged_model_gains_its_providers_tag(self) -> None:
        assert qualified_model_id("azure_ai", "my-deployment") == "azure_ai:my-deployment"

    def test_openai_is_tagged_too_unlike_the_public_id(self) -> None:
        """`public_model_id` strips the tag for OpenAI; this must not.

        An untagged id is resolved against the *configured default* provider.
        Ingesting with OpenAI while the default embedding provider is something
        else would then silently call that other provider.
        """
        assert qualified_model_id("openai", "text-embedding-3-small") == (
            "openai:text-embedding-3-small"
        )

    def test_an_explicit_provider_wins_over_a_slash_shaped_name(self) -> None:
        """watsonx serves `openai/gpt-oss-120b`, and the slash is part of the name.

        Left untagged it resolves to OpenAI — with OpenAI's credentials, for a
        model OpenAI does not serve.
        """
        assert qualified_model_id("watsonx", "openai/gpt-oss-120b") == (
            "watsonx:openai/gpt-oss-120b"
        )

    def test_an_already_tagged_id_is_not_tagged_twice(self) -> None:
        assert qualified_model_id("azure_ai", "azure_ai:my-deployment") == (
            "azure_ai:my-deployment"
        )

    @pytest.mark.parametrize(
        "provider, stored, expected",
        [
            ("azure", "azure/prod-embed", "azure:prod-embed"),
            (
                "watsonx_onprem",
                "watsonx_onprem/ibm/slate-125m",
                "watsonx_onprem:ibm/slate-125m",
            ),
            ("azure", "AZURE/prod-embed", "azure:prod-embed"),
        ],
    )
    def test_a_legacy_slash_tag_is_not_re_tagged(self, provider, stored, expected) -> None:
        """Ids stored before the switch to `provider:` are still in config.

        Re-tagging one gives `azure:azure/prod-embed`; `split_model_id` then
        strips the colon tag and leaves `azure/prod-embed` as the model name,
        so LiteLLM is asked for `azure/azure/prod-embed` and the call fails as
        a missing model.
        """
        assert qualified_model_id(provider, stored) == expected

    @pytest.mark.parametrize(
        "provider, model, expected",
        [
            # A slash in the name is part of the name, not a tag.
            ("watsonx", "ibm/slate-125m", "watsonx:ibm/slate-125m"),
            ("watsonx", "openai/gpt-oss-120b", "watsonx:openai/gpt-oss-120b"),
            # Another provider's tag is also just a name here.
            ("azure_ai", "openai/gpt-4o", "azure_ai:openai/gpt-4o"),
        ],
    )
    def test_only_this_providers_own_prefix_is_stripped(self, provider, model, expected) -> None:
        """watsonx genuinely serves `openai/gpt-oss-120b`."""
        assert qualified_model_id(provider, model) == expected

    @pytest.mark.parametrize(
        "provider, stored, expected_route",
        [
            ("azure", "azure/prod-embed", "azure/prod-embed"),
            ("watsonx", "ibm/slate-125m", "watsonx/ibm/slate-125m"),
        ],
    )
    def test_what_litellm_finally_receives(self, provider, stored, expected_route) -> None:
        """The bug is only visible after the round trip, so assert that too."""
        from services.llm_gateway import split_model_id

        resolved, name = split_model_id(qualified_model_id(provider, stored))
        assert f"{resolved}/{name}" == expected_route

    @pytest.mark.parametrize("provider", [None, "", "   "])
    def test_without_a_provider_the_id_is_left_for_the_default(self, provider) -> None:
        """Unchanged, so the gateway falls back to the configured default.

        That is what an untagged call has always done, and the caller has
        nothing better to offer.
        """
        assert qualified_model_id(provider, "text-embedding-3-small") == ("text-embedding-3-small")

    def test_a_blank_model_stays_blank(self) -> None:
        assert qualified_model_id("openai", "") == ""

    def test_the_public_id_shares_these_rules(self) -> None:
        """`public_model_id` delegates, so de-duplication cannot drift apart.

        It had the same double-tagging defect: the two helpers differ only in
        the OpenAI case, and keeping the tagging rules in one place is what
        stops one being fixed and the other not.
        """
        from services.model_catalog import public_model_id

        assert public_model_id("azure", "azure/prod-embed") == "azure:prod-embed"
        assert public_model_id("azure", "azure:prod-embed") == "azure:prod-embed"
        # OpenAI still gets a bare id, which is the one difference.
        assert public_model_id("openai", "text-embedding-3-small") == ("text-embedding-3-small")


def _processor(model: str):
    """A `TaskProcessor` whose every external dependency is a stub.

    `check_document_exists` is stubbed rather than driven through OpenSearch so
    the test exercises the embedding call and nothing else.
    """
    from models.processors import TaskProcessor

    class _Writer:
        async def index_chunks(self, context, chunks, *, final=False):
            return None

    document_service = SimpleNamespace(
        session_manager=SimpleNamespace(
            get_user_opensearch_client=lambda user_id, jwt_token: SimpleNamespace()
        ),
        document_index_writer=_Writer(),
    )
    docling_service = SimpleNamespace(
        convert_file=AsyncMock(
            return_value={
                "origin": {
                    "binary_hash": "doc-hash",
                    "filename": "scan.png",
                    "mimetype": "image/png",
                },
                "texts": [],
                "tables": [],
                "pictures": [{"prov": [{"page_no": 1}], "annotations": []}],
            }
        )
    )
    processor = TaskProcessor(
        document_service,
        SimpleNamespace(get_litellm_model_name=AsyncMock(return_value=model)),
        docling_service,
    )
    processor.check_document_exists = AsyncMock(return_value=False)
    return processor


@pytest.mark.parametrize(
    "provider, model, expected_id",
    [
        # Not aliased, so the old code took the direct-client path.
        ("azure_ai", "my-deployment", "azure_ai:my-deployment"),
        ("openai", "text-embedding-3-small", "openai:text-embedding-3-small"),
        ("azure", "prod-embed", "azure:prod-embed"),
        # Aliased: already used the gateway, and must keep doing so.
        ("watsonx_onprem", "ibm/slate-125m", "watsonx_onprem:ibm/slate-125m"),
    ],
)
@pytest.mark.asyncio
async def test_ingestion_embeds_through_the_gateway_for_every_provider(
    monkeypatch, provider, model, expected_id
) -> None:
    """No provider reaches the direct client, aliased or not."""
    calls: list[dict] = []

    async def fake_embeddings(body, **_kwargs):
        calls.append(body)
        return {"data": [{"embedding": [0.1, 0.2, 0.3]} for _ in body["input"]]}

    monkeypatch.setattr("services.llm_gateway.embeddings", fake_embeddings)

    # `clients`, minus the direct embedding client: reaching for it is exactly
    # the regression this test exists to catch, so it raises rather than
    # quietly succeeding on a MagicMock.
    class _ClientsWithoutDirectEmbedding:
        opensearch = None

        def __getattr__(self, name):
            raise AssertionError(
                f"ingestion reached clients.{name}; embeddings must go through the gateway"
            )

    monkeypatch.setattr("models.processors.clients", _ClientsWithoutDirectEmbedding())
    monkeypatch.setattr(
        "models.processors.get_openrag_config",
        lambda: SimpleNamespace(
            knowledge=SimpleNamespace(
                embedding_model=model,
                embedding_provider=provider,
                chunk_size=None,
                chunk_overlap=None,
            )
        ),
    )
    monkeypatch.setattr(
        "services.document_service.chunk_texts_for_embeddings",
        lambda texts, max_tokens: [texts] if texts else [],
    )

    await _processor(model).process_document_standard(
        file_path="scan.png",
        file_hash="doc-hash",
        owner_user_id="user-1",
        jwt_token="Bearer token",
        ocr=False,
        picture_descriptions=False,
    )

    assert [body["model"] for body in calls] == [expected_id]


@pytest.mark.asyncio
async def test_the_dimension_probe_goes_through_the_gateway(monkeypatch) -> None:
    """The probe sets the index mapping's vector width.

    It has to reach the same endpoint the real embedding call will, or the
    mapping is sized against a different provider than the one that fills it.
    """
    from services import llm_gateway as gateway_mod
    from services.langflow_file_service import LangflowFileService

    calls: list[dict] = []

    async def fake_embeddings(body, **_kwargs):
        calls.append(body)
        return {"data": [{"embedding": [0.0] * 1024}]}

    monkeypatch.setattr(gateway_mod, "embeddings", fake_embeddings)

    service = LangflowFileService(docling_service=AsyncMock())

    assert await service._detect_embedding_dimensions("my-deployment", "azure_ai") == 1024
    assert calls == [{"model": "azure_ai:my-deployment", "input": ["dimension probe"]}]
