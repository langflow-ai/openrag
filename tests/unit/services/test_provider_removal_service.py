from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.provider_removal_service import (
    ProviderRemovalService,
    ProviderRemovalStatus,
)


def _config(legacy_map: dict[str, str] | None = None):
    return SimpleNamespace(
        knowledge=SimpleNamespace(
            legacy_embedding_provider_map=legacy_map or {},
        )
    )


def _aggregation(
    *,
    qualified: list[tuple[str, int]] | None = None,
    legacy: list[tuple[str, int]] | None = None,
    qualified_after: dict[str, str] | None = None,
    legacy_after: dict[str, str] | None = None,
):
    aggregations: dict[str, dict] = {}
    if qualified is not None:
        aggregations["embedding_spaces"] = {
            "buckets": [
                {"key": {"space_id": space_id}, "doc_count": count} for space_id, count in qualified
            ],
            **({"after_key": qualified_after} if qualified_after else {}),
        }
    if legacy is not None:
        aggregations["legacy_embedding_models"] = {
            "buckets": [{"key": {"model": model}, "doc_count": count} for model, count in legacy],
            **({"after_key": legacy_after} if legacy_after else {}),
        }
    return {"aggregations": aggregations}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "space_id", "model"),
    [
        ("azure", "azure:customer-deployment", "customer-deployment"),
        (
            "watsonx",
            "watsonx:ibm/slate-125m-english-rtrvr",
            "ibm/slate-125m-english-rtrvr",
        ),
        (
            "watsonx_onprem",
            "watsonx_onprem:ibm/slate-125m-english-rtrvr",
            "ibm/slate-125m-english-rtrvr",
        ),
    ],
)
async def test_qualified_embedding_space_is_attributed_to_exact_provider(
    monkeypatch, provider, space_id, model
):
    opensearch = SimpleNamespace(
        search=AsyncMock(
            side_effect=[
                _aggregation(qualified=[(space_id, 4)]),
                _aggregation(legacy=[]),
            ]
        )
    )
    monkeypatch.setattr("services.provider_removal_service.get_index_name", lambda: "documents")

    result = await ProviderRemovalService(opensearch).assess(provider, _config())

    assert result.status is ProviderRemovalStatus.IN_USE
    assert result.affected_models == ({"model": model, "doc_count": 4},)
    qualified_query = opensearch.search.await_args_list[0].kwargs["body"]
    assert qualified_query["query"] == {"prefix": {"embedding_space_id": f"{provider}:"}}


@pytest.mark.asyncio
async def test_qualified_aggregation_pages_past_fifty_models(monkeypatch):
    first_page = [(f"azure:deployment-{index}", 1) for index in range(50)]
    opensearch = SimpleNamespace(
        search=AsyncMock(
            side_effect=[
                _aggregation(
                    qualified=first_page,
                    qualified_after={"space_id": "azure:deployment-49"},
                ),
                _aggregation(qualified=[("azure:deployment-50", 3)]),
                _aggregation(legacy=[]),
            ]
        )
    )
    monkeypatch.setattr("services.provider_removal_service.get_index_name", lambda: "documents")

    result = await ProviderRemovalService(opensearch).assess("azure", _config())

    assert result.status is ProviderRemovalStatus.IN_USE
    assert len(result.affected_models) == 51
    second_query = opensearch.search.await_args_list[1].kwargs["body"]
    assert second_query["aggs"]["embedding_spaces"]["composite"]["after"] == {
        "space_id": "azure:deployment-49"
    }


@pytest.mark.asyncio
async def test_legacy_embedding_uses_explicit_operator_mapping(monkeypatch):
    opensearch = SimpleNamespace(
        search=AsyncMock(
            side_effect=[
                _aggregation(qualified=[]),
                _aggregation(legacy=[("shared-model", 7)]),
            ]
        )
    )
    monkeypatch.setattr("services.provider_removal_service.get_index_name", lambda: "documents")
    monkeypatch.setattr(
        "services.provider_removal_service.catalog_owners",
        lambda _model: ("azure", "openai"),
    )

    result = await ProviderRemovalService(opensearch).assess(
        "azure", _config({"shared-model": "azure"})
    )

    assert result.status is ProviderRemovalStatus.IN_USE
    assert result.affected_models == ({"model": "shared-model", "doc_count": 7},)


@pytest.mark.asyncio
async def test_ambiguous_legacy_embedding_fails_closed(monkeypatch):
    opensearch = SimpleNamespace(
        search=AsyncMock(
            side_effect=[
                _aggregation(qualified=[]),
                _aggregation(legacy=[("shared-model", 7)]),
            ]
        )
    )
    monkeypatch.setattr("services.provider_removal_service.get_index_name", lambda: "documents")
    monkeypatch.setattr(
        "services.provider_removal_service.catalog_owners",
        lambda _model: ("azure", "openai"),
    )

    result = await ProviderRemovalService(opensearch).assess("azure", _config())

    assert result.status is ProviderRemovalStatus.UNKNOWN
    assert result.unresolved_legacy_models == ("shared-model",)


@pytest.mark.asyncio
async def test_unambiguous_legacy_embedding_uses_catalog_owner(monkeypatch):
    opensearch = SimpleNamespace(
        search=AsyncMock(
            side_effect=[
                _aggregation(qualified=[]),
                _aggregation(legacy=[("watsonx-only", 2)]),
            ]
        )
    )
    monkeypatch.setattr("services.provider_removal_service.get_index_name", lambda: "documents")
    monkeypatch.setattr(
        "services.provider_removal_service.catalog_owners",
        lambda _model: ("watsonx_onprem",),
    )

    result = await ProviderRemovalService(opensearch).assess("watsonx_onprem", _config())

    assert result.status is ProviderRemovalStatus.IN_USE
    assert result.affected_models == ({"model": "watsonx-only", "doc_count": 2},)


@pytest.mark.asyncio
async def test_legacy_aggregation_pages_past_fifty_models(monkeypatch):
    first_page = [(f"legacy-{index}", 1) for index in range(50)]
    mapping = {model: "azure" for model, _count in first_page}
    mapping["legacy-50"] = "azure"
    opensearch = SimpleNamespace(
        search=AsyncMock(
            side_effect=[
                _aggregation(qualified=[]),
                _aggregation(
                    legacy=first_page,
                    legacy_after={"model": "legacy-49"},
                ),
                _aggregation(legacy=[("legacy-50", 3)]),
            ]
        )
    )
    monkeypatch.setattr("services.provider_removal_service.get_index_name", lambda: "documents")

    result = await ProviderRemovalService(opensearch).assess("azure", _config(mapping))

    assert result.status is ProviderRemovalStatus.IN_USE
    assert len(result.affected_models) == 51
    second_legacy_query = opensearch.search.await_args_list[2].kwargs["body"]
    assert second_legacy_query["aggs"]["legacy_embedding_models"]["composite"]["after"] == {
        "model": "legacy-49"
    }


@pytest.mark.asyncio
async def test_opensearch_failure_fails_closed(monkeypatch):
    opensearch = SimpleNamespace(search=AsyncMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr("services.provider_removal_service.get_index_name", lambda: "documents")

    result = await ProviderRemovalService(opensearch).assess("azure", _config())

    assert result.status is ProviderRemovalStatus.UNKNOWN
    assert result.affected_models == ()
