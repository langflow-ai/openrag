from time import perf_counter

from api.schemas.status import ComponentBuild, ComponentState, ComponentStatus
from config.settings import DOCLING_SERVE_URL, LANGFLOW_URL, clients, get_openrag_config
from services.component_logs import record_check_result
from utils.logging_config import get_logger
from utils.version_utils import OPENRAG_VERSION

logger = get_logger(__name__)

_CHECK_TIMEOUT_S = 2.0


async def check_openrag_backend() -> ComponentStatus:
    start = perf_counter()
    try:
        get_openrag_config()
    except Exception as e:
        logger.warning("OpenRAG config not loaded", error=str(e))
        message = "OpenRAG configuration is not loaded"
        record_check_result(
            "openrag", False, message,
            detail=f"{type(e).__name__}: {e}",
        )
        return ComponentStatus(
            name="openrag",
            display_name="OpenRAG Backend",
            status=ComponentState.UNHEALTHY,
            required=True,
            latency_ms=int((perf_counter() - start) * 1000),
            message=message,
            version=None,
            build=ComponentBuild(),  # NOTE: deferring this to later Version and build traceability step
            metadata={},
            last_error=f"{type(e).__name__}: {e}",
        )

    missing = []
    if clients.opensearch is None:
        missing.append("opensearch client")
    if clients.langflow_http_client is None:
        missing.append("langflow client")
    if clients.docling_http_client is None:
        missing.append("docling client")

    if missing:
        status = ComponentState.DEGRADED
        message = "Backend serving but not fully initialized: " + ", ".join(missing)
        record_check_result("openrag", False, message)
        last_error: str | None = message
    else:
        status, message = ComponentState.HEALTHY, "OpenRAG backend is ready"
        record_check_result("openrag", True, message)
        last_error = None

    return ComponentStatus(
        name="openrag",
        display_name="OpenRAG Backend",
        status=status,
        required=True,
        latency_ms=int((perf_counter() - start) * 1000),
        message=message,
        version=OPENRAG_VERSION,
        build=ComponentBuild(),  # NOTE: deferring this to later Version and build traceability step
        metadata={},
        last_error=last_error,
    )


async def check_docling() -> ComponentStatus:
    start = perf_counter()
    version = None
    target_url = f"{DOCLING_SERVE_URL}/version"

    try:
        docling_client = clients.docling_http_client
        if not docling_client:
            message = "Docling client is not initialized"
            record_check_result("docling", False, message)
            return ComponentStatus(
                name="docling",
                display_name="Docling",
                status=ComponentState.UNKNOWN,
                required=True,
                latency_ms=int((perf_counter() - start) * 1000),
                message=message,
                version=version,
                build=ComponentBuild(),  # NOTE: deferring this to later Version and build traceability step
                metadata={},
                last_error=message,
            )

        resp = await docling_client.get(target_url, timeout=_CHECK_TIMEOUT_S)
        if resp.status_code == 200:
            status, message = ComponentState.HEALTHY, "Docling Serve reachable"
            version = resp.json().get("docling-serve")
            record_check_result("docling", True, message)
            last_error = None
        else:
            message = f"Docling returned HTTP {resp.status_code}"
            status = ComponentState.UNHEALTHY
            record_check_result(
                "docling", False, message,
                detail=f"HTTP {resp.status_code} — target: {target_url}",
            )
            last_error = message
    except Exception as e:
        logger.warning("Docling status check failed", error=str(e))
        message = "Docling Serve unreachable"
        status = ComponentState.UNHEALTHY
        record_check_result(
            "docling", False, message,
            detail=f"{type(e).__name__}: {e} — target: {target_url}",
        )
        last_error = f"{type(e).__name__}: {e} — target: {target_url}"

    return ComponentStatus(
        name="docling",
        display_name="Docling",
        status=status,
        required=True,
        latency_ms=int((perf_counter() - start) * 1000),
        message=message,
        version=version,
        build=ComponentBuild(),  # NOTE: deferring this to later Version and build traceability step
        metadata={},
        last_error=last_error,
    )


async def check_langflow() -> ComponentStatus:
    start = perf_counter()
    version = None
    target_url = f"{LANGFLOW_URL}/api/v1/version"

    try:
        langflow_client = clients.langflow_http_client
        if not langflow_client:
            message = "Langflow client is not initialized"
            record_check_result("langflow", False, message)
            return ComponentStatus(
                name="langflow",
                display_name="Langflow",
                status=ComponentState.UNKNOWN,
                required=True,
                latency_ms=int((perf_counter() - start) * 1000),
                message=message,
                version=version,
                build=ComponentBuild(),  # NOTE: deferring this to later Version and build traceability step
                metadata={},
                last_error=message,
            )

        resp = await langflow_client.get("/api/v1/version", timeout=_CHECK_TIMEOUT_S)
        if resp.status_code == 200:
            status, message = ComponentState.HEALTHY, "Langflow API reachable"
            version = resp.json().get("version")
            record_check_result("langflow", True, message)
            last_error = None
        else:
            message = f"Langflow returned HTTP {resp.status_code}"
            status = ComponentState.UNHEALTHY
            record_check_result(
                "langflow", False, message,
                detail=f"HTTP {resp.status_code} — target: {target_url}",
            )
            last_error = message
    except Exception as e:
        logger.warning("Langflow status check failed", error=str(e))
        message = "Langflow is unreachable"
        status = ComponentState.UNHEALTHY
        record_check_result(
            "langflow", False, message,
            detail=f"{type(e).__name__}: {e} — target: {target_url}",
        )
        last_error = f"{type(e).__name__}: {e} — target: {target_url}"

    return ComponentStatus(
        name="langflow",
        display_name="Langflow",
        status=status,
        required=True,
        latency_ms=int((perf_counter() - start) * 1000),
        message=message,
        version=version,
        build=ComponentBuild(),  # NOTE: deferring this to later Version and build traceability step
        metadata={},
        last_error=last_error,
    )


async def check_opensearch() -> ComponentStatus:
    start = perf_counter()
    version = None
    os_version = None

    try:
        opensearch = clients.opensearch
        if opensearch is None:
            message = "OpenSearch client is not initialized"
            record_check_result("opensearch", False, message)
            return ComponentStatus(
                name="opensearch",
                display_name="OpenSearch",
                status=ComponentState.UNKNOWN,
                required=True,
                latency_ms=int((perf_counter() - start) * 1000),
                message=message,
                version=version,
                build=ComponentBuild(),  # NOTE: deferring this to later Version and build traceability step
                metadata={},
                last_error=message,
            )

        health = await opensearch.cluster.health()
        info = await opensearch.info()
        cluster_status = health.get("status")
        os_version = (info.get("version") or {}).get("number")
        distribution = (info.get("version") or {}).get("distribution")

        status = {
            "green": ComponentState.HEALTHY,
            "yellow": ComponentState.DEGRADED,
            "red": ComponentState.UNHEALTHY,
        }.get(cluster_status, ComponentState.UNKNOWN)
        message = f"Cluster Health is {cluster_status}"
        metadata = {
            "cluster_name": health.get("cluster_name"),
            "cluster_health": cluster_status,
            "distribution": distribution,
        }
        ok = status in (ComponentState.HEALTHY, ComponentState.DEGRADED)
        record_check_result(
            "opensearch", ok, message,
            detail=None if ok else f"cluster_health={cluster_status}",
        )
        last_error = None if ok else f"cluster_health={cluster_status}"

    except Exception as e:
        logger.warning("OpenSearch status check failed", error=str(e))
        message = "OpenSearch is unreachable"
        status = ComponentState.UNHEALTHY
        metadata = {}
        record_check_result(
            "opensearch", False, message,
            detail=f"{type(e).__name__}: {e}",
        )
        last_error = f"{type(e).__name__}: {e}"

    return ComponentStatus(
        name="opensearch",
        display_name="OpenSearch",
        status=status,
        required=True,
        latency_ms=int((perf_counter() - start) * 1000),
        message=message,
        version=os_version,
        build=ComponentBuild(),  # NOTE: deferring this to later Version and build traceability step
        metadata=metadata,
        last_error=last_error,
    )
