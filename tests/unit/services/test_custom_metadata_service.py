import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from services.custom_metadata_service import CustomMetadataService
from services.document_index_writer import (
    DocumentIndexChunk,
    DocumentIndexContext,
    DocumentIndexWriter,
)


@pytest_asyncio.fixture
async def metadata_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_normalize_entries_builds_typed_source_and_index_values():
    service = CustomMetadataService()

    normalized = service.normalize_entries(
        [
            {"key": "supplier", "type": "string", "value": "Dell"},
            {"key": "contract_end", "type": "date", "value": "2026-12-31"},
        ]
    )

    assert normalized.source == {
        "supplier": {"type": "string", "value": "Dell"},
        "contract_end": {"type": "date", "value": "2026-12-31"},
    }
    assert normalized.index_entries == [
        {
            "key": "supplier",
            "type": "string",
            "string_value": "Dell",
            "string_value_text": "Dell",
        },
        {"key": "contract_end", "type": "date", "date_value": "2026-12-31"},
    ]


def test_normalize_entries_rejects_protected_and_duplicate_keys():
    service = CustomMetadataService()

    with pytest.raises(ValueError, match="protected"):
        service.normalize_entries([{"key": "Owner", "type": "string", "value": "other"}])

    with pytest.raises(ValueError, match="duplicate"):
        service.normalize_entries(
            [
                {"key": "supplier", "type": "string", "value": "Dell"},
                {"key": "supplier", "type": "string", "value": "Lenovo"},
            ]
        )


def test_compile_expression_supports_nested_logic_and_type_aware_operators():
    service = CustomMetadataService()

    query = service.compile_expression(
        {
            "op": "and",
            "conditions": [
                {"key": "supplier", "operator": "equals", "value": "Dell"},
                {
                    "op": "or",
                    "conditions": [
                        {
                            "key": "contract_end",
                            "operator": "between",
                            "value": {"gte": "2026-01-01", "lte": "2026-12-31"},
                        },
                        {
                            "key": "contract_type",
                            "operator": "contains",
                            "value": "support",
                        },
                    ],
                },
            ],
        },
        {
            "supplier": "string",
            "contract_end": "date",
            "contract_type": "string",
        },
    )

    assert "must" in query["bool"]
    assert query["bool"]["must"][0]["nested"]["path"] == "metadata_entries"
    nested_or = query["bool"]["must"][1]["bool"]
    assert nested_or["minimum_should_match"] == 1
    assert nested_or["should"][0]["nested"]["query"]["bool"]["must"][1] == {
        "range": {
            "metadata_entries.date_value": {
                "gte": "2026-01-01",
                "lte": "2026-12-31",
            }
        }
    }


def test_compile_expression_requires_scalar_values_except_for_set_operators():
    service = CustomMetadataService()

    with pytest.raises(ValueError, match="requires a scalar value"):
        service.compile_expression(
            {"key": "supplier", "operator": "equals", "value": ["Dell"]},
            {"supplier": "string"},
        )

    compiled = service.compile_expression(
        {"key": "supplier", "operator": "in", "value": ["Dell", "Lenovo"]},
        {"supplier": "string"},
    )
    assert compiled["nested"]["query"]["bool"]["must"][1] == {
        "terms": {"metadata_entries.string_value": ["Dell", "Lenovo"]}
    }


def test_document_writer_persists_document_and_langflow_custom_metadata():
    writer = DocumentIndexWriter()
    context = DocumentIndexContext(
        document_id="doc-1",
        filename="contract.pdf",
        mimetype="application/pdf",
        embedding_model="model",
        metadata=[{"key": "supplier", "type": "string", "value": "Dell"}],
    )
    chunk = DocumentIndexChunk(
        chunk_id="chunk-1",
        text="terms",
        vector=[0.1],
        metadata={"contract_number": 1234},
    )

    document = writer._build_chunk_document(
        context=context,
        chunk=chunk,
        embedding_field="embedding",
        indexed_time="now",
    )

    assert document["custom_metadata"]["supplier"]["value"] == "Dell"
    assert document["custom_metadata"]["contract_number"] == {
        "type": "number",
        "value": 1234,
    }
    assert {entry["key"] for entry in document["metadata_entries"]} == {
        "supplier",
        "contract_number",
    }


@pytest.mark.asyncio
async def test_registry_first_type_wins_and_mismatches_are_rejected(
    metadata_session_factory,
):
    service = CustomMetadataService(session_factory=metadata_session_factory)

    await service.register_entries([{"key": "contract_number", "type": "string", "value": "A-123"}])

    assert await service.get_field_types() == {"contract_number": "string"}
    with pytest.raises(ValueError, match="expected string"):
        await service.register_entries([{"key": "contract_number", "type": "number", "value": 123}])
