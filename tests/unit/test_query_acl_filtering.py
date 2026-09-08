from pathlib import Path

from src.services.file_service import FileService


def test_file_service_query_omits_application_acl_filter():
    query = FileService()._build_filter_query(
        user_id="user-123",
        connector_type="google_drive",
        mimetype="application/pdf",
        owner="owner@example.com",
        search="roadmap",
    )

    filters = query["bool"]["filter"]

    assert filters == [
        {"term": {"connector_type": "google_drive"}},
        {"term": {"mimetype": "application/pdf"}},
        {"term": {"owner": "owner@example.com"}},
    ]
    assert query["bool"]["must"] == [
        {
            "bool": {
                "should": [
                    {
                        "wildcard": {
                            "filename": {
                                "value": "*roadmap*",
                                "case_insensitive": True,
                            }
                        }
                    },
                    {
                        "prefix": {
                            "filename": {
                                "value": "roadmap",
                                "case_insensitive": True,
                            }
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        }
    ]


def test_file_service_v2_data_sources_single_emits_term():
    from src.services.file_service_v2 import FileServiceV2

    query = FileServiceV2()._build_filter_query(
        user_id="user-123",
        data_sources=["report.pdf"],
    )
    assert {"term": {"filename": "report.pdf"}} in query["bool"]["filter"]


def test_file_service_v2_data_sources_multi_emits_terms():
    from src.services.file_service_v2 import FileServiceV2

    query = FileServiceV2()._build_filter_query(
        user_id="user-123",
        data_sources=["report.pdf", "roadmap.docx"],
    )
    assert {"terms": {"filename": ["report.pdf", "roadmap.docx"]}} in query["bool"]["filter"]


def test_file_service_v2_multi_connector_and_data_sources():
    from src.services.file_service_v2 import FileServiceV2

    query = FileServiceV2()._build_filter_query(
        user_id="user-123",
        connector_type=["google_drive", "confluence"],
        data_sources=["doc1.pdf", "doc2.pdf"],
    )
    filters = query["bool"]["filter"]
    assert {"terms": {"connector_type": ["google_drive", "confluence"]}} in filters
    assert {"terms": {"filename": ["doc1.pdf", "doc2.pdf"]}} in filters


def test_file_service_v2_data_sources_wildcard_sentinel_produces_no_filter():
    from src.services.file_service_v2 import FileServiceV2

    # ["*"] means "all files" — must not emit a filename term
    query = FileServiceV2()._build_filter_query(
        user_id="user-123",
        data_sources=["*"],
    )
    filters = query["bool"]["filter"]
    assert not any(
        "filename" in list(c.get("term", {})) or "filename" in list(c.get("terms", {}))
        for c in filters
    )


def test_file_service_v2_data_sources_mixed_wildcard_strips_sentinel():
    from src.services.file_service_v2 import FileServiceV2

    # ["*", "report.pdf"] — strip "*", keep "report.pdf"
    query = FileServiceV2()._build_filter_query(
        user_id="user-123",
        data_sources=["*", "report.pdf"],
    )
    assert {"term": {"filename": "report.pdf"}} in query["bool"]["filter"]


def test_service_query_paths_do_not_apply_document_visibility_filters():
    repo_root = Path(__file__).resolve().parents[2]
    helper_name = "build" + "_acl_filter"
    query_path_files = [
        repo_root / "src/services/file_service.py",
        repo_root / "src/services/search_service.py",
    ]

    for source_file in query_path_files:
        source = source_file.read_text()
        assert helper_name not in source
