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
                    {"wildcard": {"filename": {"value": "*roadmap*"}}},
                    {"prefix": {"filename": "roadmap"}},
                ],
                "minimum_should_match": 1,
            }
        }
    ]


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
