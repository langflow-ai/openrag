from typing import Optional

from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dependencies import get_api_key_user_async
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RawLogRef(BaseModel):
    component: str
    pod: str
    timestamp: str
    trace_id: str


class Correlation(BaseModel):
    docling_task_id: Optional[str] = None
    langflow_run_id: Optional[str] = None
    opensearch_request_id: Optional[str] = None


class IngestionJobDetail(BaseModel):
    ingestion_job_id: str
    file_id: str
    file_name: str
    source_type: str
    status: str
    component: Optional[str] = None
    phase: Optional[str] = None
    error_code: Optional[str] = None
    actionability: Optional[str] = None
    retryable: Optional[bool] = None
    user_title: Optional[str] = None
    user_message: Optional[str] = None
    technical_message: Optional[str] = None
    raw_log_refs: list[RawLogRef] = []
    correlation: Correlation = Correlation()
    created_at: str
    updated_at: str


class IngestionJobSummary(BaseModel):
    ingestion_job_id: str
    file_name: str
    source_type: str
    status: str
    component: Optional[str] = None
    phase: Optional[str] = None
    error_code: Optional[str] = None
    actionability: Optional[str] = None
    retryable: Optional[bool] = None
    user_title: Optional[str] = None
    created_at: str


class IngestionJobListResponse(BaseModel):
    total: int
    jobs: list[IngestionJobSummary]


# ---------------------------------------------------------------------------
# Mock data — 18 jobs covering all 16 MVP error scenarios + running + completed
# ---------------------------------------------------------------------------

MOCK_JOBS: dict[str, IngestionJobDetail] = {
    "job-001": IngestionJobDetail(
        ingestion_job_id="job-001",
        file_id="file-001",
        file_name="annual-report-2025.pdf",
        source_type="local",
        status="completed",
        created_at="2026-05-12T07:00:00Z",
        updated_at="2026-05-12T07:04:32Z",
    ),
    "job-002": IngestionJobDetail(
        ingestion_job_id="job-002",
        file_id="file-002",
        file_name="quarterly-report.pdf",
        source_type="sharepoint",
        status="failed",
        component="openrag",
        phase="source_access",
        error_code="ING_SOURCE_ACCESS_DENIED",
        actionability="USER_ACTIONABLE",
        retryable=False,
        user_title="Source access denied",
        user_message="OpenRAG could not access the selected source. Please reconnect the source or check your permissions.",
        technical_message="SharePoint returned 403 Forbidden for file quarterly-report.pdf. OAuth token may have expired.",
        raw_log_refs=[
            RawLogRef(
                component="openrag",
                pod="openrag-backend-6d8f9b-abc12",
                timestamp="2026-05-12T09:15:03Z",
                trace_id="trace-openrag-002",
            )
        ],
        correlation=Correlation(),
        created_at="2026-05-12T09:15:00Z",
        updated_at="2026-05-12T09:15:04Z",
    ),
    "job-003": IngestionJobDetail(
        ingestion_job_id="job-003",
        file_id="file-003",
        file_name="deleted-document.docx",
        source_type="google_drive",
        status="failed",
        component="openrag",
        phase="source_access",
        error_code="ING_SOURCE_FILE_NOT_FOUND",
        actionability="USER_ACTIONABLE",
        retryable=False,
        user_title="File not found",
        user_message="The selected file could not be found. It may have been moved or deleted.",
        technical_message="Google Drive API returned 404 for file ID 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms.",
        raw_log_refs=[
            RawLogRef(
                component="openrag",
                pod="openrag-backend-6d8f9b-abc12",
                timestamp="2026-05-12T09:20:01Z",
                trace_id="trace-openrag-003",
            )
        ],
        correlation=Correlation(),
        created_at="2026-05-12T09:20:00Z",
        updated_at="2026-05-12T09:20:02Z",
    ),
    "job-004": IngestionJobDetail(
        ingestion_job_id="job-004",
        file_id="file-004",
        file_name="presentation.key",
        source_type="local",
        status="failed",
        component="openrag",
        phase="file_validation",
        error_code="ING_FILE_UNSUPPORTED_TYPE",
        actionability="USER_ACTIONABLE",
        retryable=False,
        user_title="Unsupported file type",
        user_message="This file type is not supported for ingestion.",
        technical_message="File extension .key is not in the allowed MIME types list.",
        raw_log_refs=[
            RawLogRef(
                component="openrag",
                pod="openrag-backend-6d8f9b-abc12",
                timestamp="2026-05-12T09:25:01Z",
                trace_id="trace-openrag-004",
            )
        ],
        correlation=Correlation(),
        created_at="2026-05-12T09:25:00Z",
        updated_at="2026-05-12T09:25:02Z",
    ),
    "job-005": IngestionJobDetail(
        ingestion_job_id="job-005",
        file_id="file-005",
        file_name="contract-signed.pdf",
        source_type="local",
        status="failed",
        component="docling",
        phase="parsing",
        error_code="ING_DOCLING_PASSWORD_PROTECTED",
        actionability="USER_ACTIONABLE",
        retryable=False,
        user_title="File is password-protected",
        user_message="This file is password-protected. Please upload an unlocked version.",
        technical_message="Docling failed while parsing encrypted PDF: PdfEncryptedError.",
        raw_log_refs=[
            RawLogRef(
                component="docling",
                pod="docling-serve-7d9f8b-xkp2r",
                timestamp="2026-05-12T08:22:10Z",
                trace_id="trace-docling-005",
            )
        ],
        correlation=Correlation(docling_task_id="06485758-c10c-4549-9c2e-eb1c91eb6988"),
        created_at="2026-05-12T08:20:00Z",
        updated_at="2026-05-12T08:22:11Z",
    ),
    "job-006": IngestionJobDetail(
        ingestion_job_id="job-006",
        file_id="file-006",
        file_name="research-paper.pdf",
        source_type="s3",
        status="failed",
        component="docling",
        phase="result_polling",
        error_code="ING_DOCLING_TASK_NOT_FOUND",
        actionability="RETRYABLE",
        retryable=True,
        user_title="Document processing result unavailable",
        user_message="The processed document result could not be found. This can happen if the processing task expired or the Docling service restarted. Please retry ingestion.",
        technical_message="Client error '404 Not Found' for url 'http://docling-serve.openrag.svc/v1/result/a1b2c3d4-e5f6-7890-abcd-ef1234567890'.",
        raw_log_refs=[
            RawLogRef(
                component="docling",
                pod="docling-serve-7d9f8b-xkp2r",
                timestamp="2026-05-12T10:05:30Z",
                trace_id="trace-docling-006",
            )
        ],
        correlation=Correlation(docling_task_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
        created_at="2026-05-12T10:00:00Z",
        updated_at="2026-05-12T10:05:31Z",
    ),
    "job-007": IngestionJobDetail(
        ingestion_job_id="job-007",
        file_id="file-007",
        file_name="large-scanned-manual.pdf",
        source_type="local",
        status="failed",
        component="docling",
        phase="parsing",
        error_code="ING_DOCLING_TIMEOUT",
        actionability="RETRYABLE",
        retryable=True,
        user_title="Document processing timed out",
        user_message="Document processing timed out. The document may be very large or complex. Please retry ingestion.",
        technical_message="Docling worker timeout after 300s processing large-scanned-manual.pdf (312 pages, scanned).",
        raw_log_refs=[
            RawLogRef(
                component="docling",
                pod="docling-serve-7d9f8b-xkp2r",
                timestamp="2026-05-12T10:35:00Z",
                trace_id="trace-docling-007",
            )
        ],
        correlation=Correlation(docling_task_id="b2c3d4e5-f6a7-8901-bcde-f12345678901"),
        created_at="2026-05-12T10:30:00Z",
        updated_at="2026-05-12T10:35:01Z",
    ),
    "job-008": IngestionJobDetail(
        ingestion_job_id="job-008",
        file_id="file-008",
        file_name="high-res-architectural-drawings.pdf",
        source_type="sharepoint",
        status="failed",
        component="docling",
        phase="parsing",
        error_code="ING_DOCLING_OUT_OF_MEMORY",
        actionability="ADMIN_ACTIONABLE",
        retryable=False,
        user_title="Processing ran out of memory",
        user_message="The document was too complex for the current processing resources. Contact your administrator.",
        technical_message="Docling pod OOMKilled while processing high-res-architectural-drawings.pdf. Pod memory limit: 4Gi.",
        raw_log_refs=[
            RawLogRef(
                component="docling",
                pod="docling-serve-7d9f8b-xkp2r",
                timestamp="2026-05-12T11:10:45Z",
                trace_id="trace-docling-008",
            )
        ],
        correlation=Correlation(docling_task_id="c3d4e5f6-a7b8-9012-cdef-123456789012"),
        created_at="2026-05-12T11:05:00Z",
        updated_at="2026-05-12T11:10:46Z",
    ),
    "job-009": IngestionJobDetail(
        ingestion_job_id="job-009",
        file_id="file-009",
        file_name="employee-handbook.pdf",
        source_type="local",
        status="failed",
        component="langflow",
        phase="flow_invocation",
        error_code="ING_LANGFLOW_FLOW_NOT_FOUND",
        actionability="ADMIN_ACTIONABLE",
        retryable=False,
        user_title="Ingestion flow not found",
        user_message="OpenRAG could not start the ingestion flow. Contact your administrator.",
        technical_message="Langflow returned 404 for flow ID 9f8e7d6c-5b4a-3210-fedc-ba9876543210. Flow may have been deleted.",
        raw_log_refs=[
            RawLogRef(
                component="langflow",
                pod="langflow-5c6d7e-rst89",
                timestamp="2026-05-12T11:30:05Z",
                trace_id="trace-langflow-009",
            )
        ],
        correlation=Correlation(docling_task_id="d4e5f6a7-b8c9-0123-defa-234567890123"),
        created_at="2026-05-12T11:28:00Z",
        updated_at="2026-05-12T11:30:06Z",
    ),
    "job-010": IngestionJobDetail(
        ingestion_job_id="job-010",
        file_id="file-010",
        file_name="financial-statements.xlsx",
        source_type="s3",
        status="failed",
        component="langflow",
        phase="flow_invocation",
        error_code="ING_LANGFLOW_COMPONENT_CONFIG_INVALID",
        actionability="ADMIN_ACTIONABLE",
        retryable=False,
        user_title="Ingestion flow misconfigured",
        user_message="The ingestion flow is not configured correctly. Contact your administrator.",
        technical_message="Error building Component 'Docling Serve': missing required global variable DOCLING_SERVE_URL.",
        raw_log_refs=[
            RawLogRef(
                component="langflow",
                pod="langflow-5c6d7e-rst89",
                timestamp="2026-05-12T12:00:10Z",
                trace_id="trace-langflow-010",
            )
        ],
        correlation=Correlation(
            docling_task_id="e5f6a7b8-c9d0-1234-efab-345678901234",
            langflow_run_id="run-langflow-010",
        ),
        created_at="2026-05-12T12:00:00Z",
        updated_at="2026-05-12T12:00:11Z",
    ),
    "job-011": IngestionJobDetail(
        ingestion_job_id="job-011",
        file_id="file-011",
        file_name="product-catalog.pdf",
        source_type="local",
        status="failed",
        component="langflow",
        phase="embedding",
        error_code="ING_LANGFLOW_EMBEDDING_RATE_LIMITED",
        actionability="RETRYABLE",
        retryable=True,
        user_title="Embedding model rate-limited",
        user_message="The embedding model is temporarily rate-limited. Please retry later.",
        technical_message="RateLimitError: 429 Too Many Requests from embedding provider. Retry-After: 60s.",
        raw_log_refs=[
            RawLogRef(
                component="langflow",
                pod="langflow-5c6d7e-rst89",
                timestamp="2026-05-12T13:15:22Z",
                trace_id="trace-langflow-011",
            )
        ],
        correlation=Correlation(
            docling_task_id="f6a7b8c9-d0e1-2345-fabc-456789012345",
            langflow_run_id="run-langflow-011",
        ),
        created_at="2026-05-12T13:10:00Z",
        updated_at="2026-05-12T13:15:23Z",
    ),
    "job-012": IngestionJobDetail(
        ingestion_job_id="job-012",
        file_id="file-012",
        file_name="legal-brief.pdf",
        source_type="sharepoint",
        status="failed",
        component="langflow",
        phase="embedding",
        error_code="ING_LANGFLOW_EMBEDDING_MODEL_UNAVAILABLE",
        actionability="ADMIN_ACTIONABLE",
        retryable=False,
        user_title="Embedding model unavailable",
        user_message="The configured embedding model is unavailable. Contact your administrator.",
        technical_message="LiteLLM: DeploymentUnavailableError for model 'ibm/slate-125m-english-rtrvr'. No healthy deployments found.",
        raw_log_refs=[
            RawLogRef(
                component="langflow",
                pod="langflow-5c6d7e-rst89",
                timestamp="2026-05-12T14:05:08Z",
                trace_id="trace-langflow-012",
            )
        ],
        correlation=Correlation(
            docling_task_id="a7b8c9d0-e1f2-3456-abcd-567890123456",
            langflow_run_id="run-langflow-012",
        ),
        created_at="2026-05-12T14:00:00Z",
        updated_at="2026-05-12T14:05:09Z",
    ),
    "job-013": IngestionJobDetail(
        ingestion_job_id="job-013",
        file_id="file-013",
        file_name="meeting-notes.docx",
        source_type="local",
        status="failed",
        component="opensearch",
        phase="indexing",
        error_code="ING_OPENSEARCH_UNAVAILABLE",
        actionability="RETRYABLE",
        retryable=True,
        user_title="Search index temporarily unavailable",
        user_message="The search index is temporarily unavailable. Please retry later.",
        technical_message="ConnectionError: [Errno 111] Connection refused to opensearch:9200 after 3 retries.",
        raw_log_refs=[
            RawLogRef(
                component="opensearch",
                pod="opensearch-cluster-0",
                timestamp="2026-05-12T14:30:15Z",
                trace_id="trace-opensearch-013",
            )
        ],
        correlation=Correlation(
            docling_task_id="b8c9d0e1-f2a3-4567-bcde-678901234567",
            langflow_run_id="run-langflow-013",
        ),
        created_at="2026-05-12T14:28:00Z",
        updated_at="2026-05-12T14:30:16Z",
    ),
    "job-014": IngestionJobDetail(
        ingestion_job_id="job-014",
        file_id="file-014",
        file_name="policy-document.pdf",
        source_type="s3",
        status="failed",
        component="opensearch",
        phase="indexing",
        error_code="ING_OPENSEARCH_BULK_PARTIAL_FAILURE",
        actionability="ADMIN_ACTIONABLE",
        retryable=False,
        user_title="Some document sections could not be saved",
        user_message="Some document chunks could not be saved to the search index. The document may be partially searchable.",
        technical_message="BulkIndexError: 12 of 47 chunks failed. Common cause: mapper_parsing_exception on 'page_image_refs' field.",
        raw_log_refs=[
            RawLogRef(
                component="opensearch",
                pod="opensearch-cluster-0",
                timestamp="2026-05-12T15:10:40Z",
                trace_id="trace-opensearch-014",
            )
        ],
        correlation=Correlation(
            docling_task_id="c9d0e1f2-a3b4-5678-cdef-789012345678",
            langflow_run_id="run-langflow-014",
            opensearch_request_id="os-req-014",
        ),
        created_at="2026-05-12T15:05:00Z",
        updated_at="2026-05-12T15:10:41Z",
    ),
    "job-015": IngestionJobDetail(
        ingestion_job_id="job-015",
        file_id="file-015",
        file_name="invoice-batch.pdf",
        source_type="local",
        status="failed",
        component="opensearch",
        phase="indexing",
        error_code="ING_OPENSEARCH_INDEX_READ_ONLY",
        actionability="ADMIN_ACTIONABLE",
        retryable=False,
        user_title="Search index is read-only",
        user_message="The search index is currently read-only, likely due to storage pressure. Contact your administrator.",
        technical_message="ClusterBlockException: index [openrag-docs] blocked by: [FORBIDDEN/12/index read-only / allow delete (api)].",
        raw_log_refs=[
            RawLogRef(
                component="opensearch",
                pod="opensearch-cluster-0",
                timestamp="2026-05-12T15:45:20Z",
                trace_id="trace-opensearch-015",
            )
        ],
        correlation=Correlation(
            docling_task_id="d0e1f2a3-b4c5-6789-defa-890123456789",
            langflow_run_id="run-langflow-015",
            opensearch_request_id="os-req-015",
        ),
        created_at="2026-05-12T15:40:00Z",
        updated_at="2026-05-12T15:45:21Z",
    ),
    "job-016": IngestionJobDetail(
        ingestion_job_id="job-016",
        file_id="file-016",
        file_name="compliance-report.pdf",
        source_type="sharepoint",
        status="failed",
        component="opensearch",
        phase="indexing",
        error_code="ING_OPENSEARCH_CLUSTER_RED",
        actionability="ADMIN_ACTIONABLE",
        retryable=False,
        user_title="Search index is unhealthy",
        user_message="The search index is currently unhealthy and cannot accept new documents. Contact your administrator.",
        technical_message="OpenSearch cluster health is RED. Primary shard for index 'openrag-docs' is unassigned.",
        raw_log_refs=[
            RawLogRef(
                component="opensearch",
                pod="opensearch-cluster-0",
                timestamp="2026-05-12T16:20:05Z",
                trace_id="trace-opensearch-016",
            )
        ],
        correlation=Correlation(
            docling_task_id="e1f2a3b4-c5d6-7890-efab-901234567890",
            langflow_run_id="run-langflow-016",
        ),
        created_at="2026-05-12T16:15:00Z",
        updated_at="2026-05-12T16:20:06Z",
    ),
    "job-017": IngestionJobDetail(
        ingestion_job_id="job-017",
        file_id="file-017",
        file_name="unknown-error-doc.pdf",
        source_type="local",
        status="failed",
        component="openrag",
        phase="completion_verification",
        error_code="ING_UNKNOWN_FAILURE",
        actionability="DEVELOPER_ACTIONABLE",
        retryable=True,
        user_title="Ingestion failed unexpectedly",
        user_message="Ingestion failed unexpectedly. Please retry. If it fails again, contact your administrator.",
        technical_message="Unhandled exception in ingestion pipeline: AttributeError: 'NoneType' object has no attribute 'chunks'.",
        raw_log_refs=[
            RawLogRef(
                component="openrag",
                pod="openrag-backend-6d8f9b-abc12",
                timestamp="2026-05-12T16:55:33Z",
                trace_id="trace-openrag-017",
            )
        ],
        correlation=Correlation(
            docling_task_id="f2a3b4c5-d6e7-8901-fabc-012345678901",
            langflow_run_id="run-langflow-017",
        ),
        created_at="2026-05-12T16:50:00Z",
        updated_at="2026-05-12T16:55:34Z",
    ),
    "job-018": IngestionJobDetail(
        ingestion_job_id="job-018",
        file_id="file-018",
        file_name="in-progress-report.pdf",
        source_type="s3",
        status="running",
        component="langflow",
        phase="embedding",
        created_at="2026-05-12T17:00:00Z",
        updated_at="2026-05-12T17:01:30Z",
    ),
}


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------


async def list_ingestion_jobs(
    status: Optional[str] = Query(
        None, description="Filter by status: completed, failed, running, pending"
    ),
    component: Optional[str] = Query(
        None, description="Filter by component: openrag, docling, langflow, opensearch"
    ),
    actionability: Optional[str] = Query(
        None,
        description="Filter by actionability: USER_ACTIONABLE, RETRYABLE, ADMIN_ACTIONABLE, DEVELOPER_ACTIONABLE",
    ),
    user: User = Depends(get_api_key_user_async),
):
    """List ingestion jobs with optional filtering."""
    jobs = list(MOCK_JOBS.values())

    if status:
        jobs = [j for j in jobs if j.status == status]
    if component:
        jobs = [j for j in jobs if j.component == component]
    if actionability:
        jobs = [j for j in jobs if j.actionability == actionability]

    summaries = [
        IngestionJobSummary(
            ingestion_job_id=j.ingestion_job_id,
            file_name=j.file_name,
            source_type=j.source_type,
            status=j.status,
            component=j.component,
            phase=j.phase,
            error_code=j.error_code,
            actionability=j.actionability,
            retryable=j.retryable,
            user_title=j.user_title,
            created_at=j.created_at,
        )
        for j in jobs
    ]

    response = IngestionJobListResponse(total=len(summaries), jobs=summaries)
    return JSONResponse(response.model_dump())


async def get_ingestion_job(
    job_id: str,
    user: User = Depends(get_api_key_user_async),
):
    """Get a specific ingestion job by ID."""
    job = MOCK_JOBS.get(job_id)
    if not job:
        return JSONResponse({"error": "Ingestion job not found"}, status_code=404)

    return JSONResponse(job.model_dump())
