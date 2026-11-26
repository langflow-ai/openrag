from openrag_sdk import SearchFilters


def test_search_filters_include_owner_and_connector_filters():
    filters = SearchFilters(
        data_sources=["api-docs.pdf"],
        document_types=["application/pdf"],
        owners=["user@example.com"],
        connector_types=["google_drive"],
    )

    assert filters.model_dump(exclude_none=True) == {
        "data_sources": ["api-docs.pdf"],
        "document_types": ["application/pdf"],
        "owners": ["user@example.com"],
        "connector_types": ["google_drive"],
    }
