from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import Depends, Query

from dependencies import get_api_key_user_async
from session_manager import User

ComponentStatus = Literal["passing", "degraded", "offline", "unknown"]
OverallStatus = Literal["healthy", "degraded", "unhealthy", "unknown"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_version(
    display: str,
    image: str | None = None,
    git_sha: str | None = None,
    build_time: str | None = None,
) -> dict[str, Any]:
    return {
        "display": display,
        "semantic_version": display if display and display[0].isdigit() else None,
        "image": image,
        "image_digest": f"sha256:mock-{display.replace(':', '-').replace('/', '-')}-digest" if image else None,
        "git_sha": git_sha,
        "build_time": build_time,
    }


def mock_component(
    *,
    component_id: str,
    name: str,
    component_type: str,
    status: ComponentStatus,
    version_display: str,
    sort_order: int,
    expanded: bool = False,
    response_time_ms: int = 45,
    message: str = "Component is healthy.",
    image: str | None = None,
    git_sha: str | None = None,
    extra_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    severity_map = {
        "passing": "success",
        "degraded": "warning",
        "offline": "critical",
        "unknown": "neutral",
    }

    display_status_map = {
        "passing": "Passing",
        "degraded": "Degraded",
        "offline": "Offline",
        "unknown": "Unknown",
    }

    last_sync = datetime.now(timezone.utc) - timedelta(minutes=15 if status == "degraded" else 1)

    details = {
        "checks": [
            {
                "id": f"{component_id}.health",
                "name": "Health Check",
                "status": status,
                "message": message,
                "latency_ms": response_time_ms,
            }
        ]
    }

    if extra_details:
        details.update(extra_details)

    return {
        "id": component_id,
        "name": name,
        "type": component_type,
        "required": True,
        "status": status,
        "display_status": display_status_map[status],
        "severity": severity_map[status],
        "version": build_version(
            display=version_display,
            image=image,
            git_sha=git_sha,
            build_time="2026-05-10T12:00:00Z" if git_sha else None,
        ),
        "environment": {
            "id": "staging",
            "label": "Staging",
        },
        "last_sync_at": last_sync.isoformat(),
        "last_sync_display": "15 minutes ago" if status == "degraded" else "Just now",
        "uptime": {
            "percentage": 99.8 if status != "offline" else 0,
            "display": "99.8%" if status != "offline" else "0%",
        },
        "response_time": {
            "ms": response_time_ms,
            "display": f"{response_time_ms}ms",
            "trend": "up" if status == "degraded" else "flat",
        },
        "message": message,
        "details": details,
        "actions": {
            "can_view_logs": True,
            "can_sync": True,
            "can_configure": True,
            "can_restart": False,
        },
        "ui": {
            "expanded_by_default": expanded,
            "sort_order": sort_order,
        },
    }


def build_mock_status(scenario: str = "degraded") -> dict[str, Any]:
    if scenario == "healthy":
        langflow_status: ComponentStatus = "passing"
        overall_status: OverallStatus = "healthy"
    elif scenario == "offline":
        langflow_status = "offline"
        overall_status = "unhealthy"
    else:
        langflow_status = "degraded"
        overall_status = "degraded"

    components = [
        mock_component(
            component_id="langflow",
            name="Langflow",
            component_type="orchestration",
            status=langflow_status,
            version_display="2.11.0",
            image="langflow:2.11.0",
            sort_order=10,
            expanded=True,
            response_time_ms=45,
            message=(
                "Langflow is reachable but one or more flow checks are degraded."
                if langflow_status == "degraded"
                else "Langflow is healthy."
            ),
            extra_details={
                "health_endpoint": "/health",
                "api_reachable": langflow_status != "offline",
                "flow_execution_available": langflow_status != "offline",
                "last_error": (
                    "One configured ingestion flow returned a warning during validation."
                    if langflow_status == "degraded"
                    else None
                ),
                "checks": [
                    {
                        "id": "langflow.api",
                        "name": "Langflow API",
                        "status": "passing" if langflow_status != "offline" else "offline",
                        "message": "API is reachable" if langflow_status != "offline" else "API is unreachable",
                        "latency_ms": 45,
                    },
                    {
                        "id": "langflow.flows",
                        "name": "Flow Registry",
                        "status": "degraded" if langflow_status == "degraded" else langflow_status,
                        "message": (
                            "One flow is missing expected configuration"
                            if langflow_status == "degraded"
                            else "Flow registry is healthy"
                        ),
                        "latency_ms": 58,
                    },
                ],
            },
        ),
        mock_component(
            component_id="openrag-backend",
            name="OpenRAG Backend",
            component_type="backend",
            status="passing",
            version_display="0.4.0",
            image="openrag-api:0.4.0",
            git_sha="abc1234",
            sort_order=20,
            response_time_ms=28,
            message="OpenRAG backend is ready.",
            extra_details={
                "api_reachable": True,
                "auth_configured": True,
                "database_reachable": True,
            },
        ),
        mock_component(
            component_id="docling",
            name="Docling",
            component_type="ingestion",
            status="passing",
            version_display="2.39.0",
            image="docling-serve:2.39.0",
            sort_order=30,
            response_time_ms=82,
            message="Docling Serve is reachable.",
            extra_details={
                "serve_reachable": True,
                "rq_enabled": True,
                "queue_reachable": True,
                "workers_available": 4,
            },
        ),
        mock_component(
            component_id="opensearch",
            name="OpenSearch",
            component_type="search",
            status="passing",
            version_display="3.5.x",
            image="opensearch:3.5.x-ubi9",
            sort_order=40,
            response_time_ms=35,
            message="OpenSearch cluster is healthy.",
            extra_details={
                "cluster_name": "openrag-search",
                "cluster_health": "green",
                "index_available": True,
                "target_index": "openrag-documents",
                "target_alias": "openrag-documents-current",
                "document_count": 10000,
            },
        ),
        mock_component(
            component_id="embedding-models",
            name="Embedding Models",
            component_type="model_provider",
            status="passing",
            version_display="text-embedding-3-large",
            sort_order=50,
            response_time_ms=110,
            message="Embedding model provider is reachable.",
            extra_details={
                "provider": "openai",
                "model": "text-embedding-3-large",
                "configured": True,
            },
        ),
        mock_component(
            component_id="ai-providers",
            name="AI Providers",
            component_type="model_provider",
            status="passing",
            version_display="GPT-4",
            sort_order=60,
            response_time_ms=210,
            message="AI provider is configured and reachable.",
            extra_details={
                "provider": "openai",
                "model": "gpt-4",
                "configured": True,
            },
        ),
    ]

    summary = {
        "online": len([c for c in components if c["status"] == "passing"]),
        "degraded": len([c for c in components if c["status"] == "degraded"]),
        "offline": len([c for c in components if c["status"] == "offline"]),
        "unknown": len([c for c in components if c["status"] == "unknown"]),
        "total": len(components),
    }

    return {
        "schema_version": "2026-05-10",
        "environment": {
            "id": "staging",
            "label": "Staging",
            "region": "ca-tor",
            "deployment_id": "openrag-staging-001",
        },
        "overall_status": overall_status,
        "overall_display_status": overall_status.capitalize(),
        "last_updated_at": now_iso(),
        "last_updated_display": "Just now",
        "auto_refresh_seconds": 60,
        "summary": summary,
        "components": sorted(components, key=lambda c: c["ui"]["sort_order"]),
        "actions": {
            "can_refresh_all": True,
            "can_copy_diagnostics": True,
        },
    }


async def get_status_endpoint(
    mock: bool = Query(default=True),
    scenario: str = Query(default="degraded", pattern="^(healthy|degraded|offline)$"),
    user: User = Depends(get_api_key_user_async),
):
    """
    Returns the status dashboard payload.

    For now this returns mock data so the frontend team can build the UI.
    Later this can switch to live component checks.
    """
    return build_mock_status(scenario=scenario)


async def refresh_status_endpoint(
    user: User = Depends(get_api_key_user_async),
):
    """
    Refreshes all component checks.

    Mock implementation: returns a completed refresh response.
    """
    return {
        "request_id": "status-refresh-123",
        "status": "completed",
        "started_at": now_iso(),
        "completed_at": now_iso(),
        "duration_ms": 850,
        "result": {
            "overall_status": "degraded",
            "online": 5,
            "degraded": 1,
            "offline": 0,
        },
    }


async def sync_component_endpoint(
    component_id: str,
    user: User = Depends(get_api_key_user_async),
):
    """
    Refreshes one component check.

    Mock implementation: returns a synthetic component result.
    """
    component = mock_component(
        component_id=component_id,
        name=component_id.replace("-", " ").title(),
        component_type="other",
        status="passing",
        version_display="mock",
        sort_order=999,
        response_time_ms=44,
        message="Component check completed successfully.",
    )

    return {
        "request_id": "component-sync-456",
        "component_id": component_id,
        "status": "completed",
        "started_at": now_iso(),
        "completed_at": now_iso(),
        "duration_ms": 540,
        "component": component,
    }


async def get_component_logs_endpoint(
    component_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(get_api_key_user_async),
):
    """
    Returns mock logs for a component.
    """
    return {
        "component_id": component_id,
        "component_name": component_id.replace("-", " ").title(),
        "logs": [
            {
                "timestamp": now_iso(),
                "level": "info",
                "message": f"{component_id} health check started.",
            },
            {
                "timestamp": now_iso(),
                "level": "info",
                "message": f"{component_id} health check completed.",
            },
        ][:limit],
        "next_cursor": None,
    }


async def get_diagnostics_endpoint(
    user: User = Depends(get_api_key_user_async),
):
    """
    Returns compact mock diagnostics for copy/paste into Slack or support tickets.
    """
    status = build_mock_status("degraded")

    return {
        "generated_at": now_iso(),
        "environment": status["environment"]["id"],
        "deployment_id": status["environment"]["deployment_id"],
        "overall_status": status["overall_status"],
        "versions": {
            c["id"]: c["version"]["display"]
            for c in status["components"]
        },
        "summary": status["summary"],
        "failed_or_degraded_checks": [
            {
                "component_id": "langflow",
                "component_name": "Langflow",
                "check_id": "langflow.flows",
                "status": "degraded",
                "message": "One flow is missing expected configuration",
            }
        ],
    }
