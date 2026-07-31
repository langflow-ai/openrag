from time import perf_counter

from api.schemas.status import ComponentBuild, ComponentState, ComponentStatus
from config.settings import clients, DOCLING_SERVE_URL, get_openrag_config
from utils.logging_config import get_logger
from utils.version_utils import OPENRAG_VERSION

logger = get_logger(__name__)

_CHECK_TIMEOUT_S = 3.0

async def check_openrag_backend() -> ComponentStatus:
    start = perf_counter()
    try:
        get_openrag_config()
    except Exception as e:
        logger.warning("OpenRAG config not loaded", error=str(e))

        return ComponentStatus(
            name="openrag",
            display_name="OpenRAG Backend",
            status=ComponentState.UNHEALTHY,
            required=True,
            latency_ms=int((perf_counter() - start) * 1000),
            message="OpenRAG configuration is not loaded",
            version=None, 
            build=ComponentBuild(), # NOTE: deferring this to later Version and build traceability step
            metadata={}
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
    else:
        status, message = ComponentState.HEALTHY, "OpenRAG backend is ready"

    return ComponentStatus(
        name="openrag",
        display_name="OpenRAG Backend",
        status=status,
        required=True,
        latency_ms=int((perf_counter() - start) * 1000),
        message=message,
        version=OPENRAG_VERSION,
        build=ComponentBuild(), # NOTE: deferring this to later Version and build traceability step
        metadata={}
    )

async def check_docling() -> ComponentStatus:
    start = perf_counter()
    version = None

    try:
        docling_client = clients.docling_http_client
        if not docling_client:
            return ComponentStatus(
                name="docling",
                display_name="Docling",
                status=ComponentState.UNKNOWN,
                required=True,
                latency_ms=int((perf_counter() - start) * 1000),
                message="Docling client is not initialized",
                version=version,
                build=ComponentBuild(), # NOTE: deferring this to later Version and build traceability step
                metadata={}
            )
        
        resp = await docling_client.get(f"{DOCLING_SERVE_URL}/version", timeout=_CHECK_TIMEOUT_S)
        if resp.status_code == 200:
            status, message = ComponentState.HEALTHY, "Docling Serve reachable"
            version = resp.json().get("docling-serve")
        else:
            status, message = ComponentState.UNHEALTHY, f"Docling returned HTTP {resp.status_code}"
    except Exception as e:
        logger.warning("Docling status check failed", error=str(e))
        status, message = ComponentState.UNHEALTHY, "Docling Serve unreachable"

    return ComponentStatus(
        name="docling",
        display_name="Docling",
        status=status,
        required=True,
        latency_ms=int((perf_counter() - start) * 1000),
        message=message,
        version=version,
        build=ComponentBuild(), # NOTE: deferring this to later Version and build traceability step
        metadata={}
    )

async def check_langflow() -> ComponentStatus:
    start = perf_counter()
    version = None

    try:
        langflow_client = clients.langflow_http_client
        if not langflow_client:
            return ComponentStatus(
                name="langflow",
                display_name="Langflow",
                status=ComponentState.UNKNOWN,
                required=True,
                latency_ms=int((perf_counter() - start) * 1000),
                message="Langflow client is not initialized",
                version=version,
                build=ComponentBuild(), # NOTE: deferring this to later Version and build traceability step
                metadata={}
            )

        resp = await langflow_client.get("/api/v1/version", timeout=_CHECK_TIMEOUT_S)
        if resp.status_code == 200:
            status, message = ComponentState.HEALTHY, "Langflow API reachable"
            version = resp.json().get("version")
        else:
            status, message = ComponentState.UNHEALTHY, f"Langflow returned HTTP {resp.status_code}"
    except Exception as e:
        logger.warning("Langflow status check failed", error=str(e))

        status, message = ComponentState.UNHEALTHY, "Langflow is unreachable"

    return ComponentStatus(
        name="langflow",
        display_name="Langflow",
        status=status,
        required=True,
        latency_ms=int((perf_counter() - start) * 1000),
        message=message,
        version=version,
        build=ComponentBuild(), # NOTE: deferring this to later Version and build traceability step
        metadata={}
    )

async def check_opensearch() -> ComponentStatus:
    start = perf_counter()
    version = None
    os_version = None

    try:
        opensearch = clients.opensearch
        if opensearch is None:
            return ComponentStatus(
                name="opensearch",
                display_name="OpenSearch",
                status=ComponentState.UNKNOWN,
                required=True,
                latency_ms=int((perf_counter() - start) * 1000),
                message="OpenSearch client is not initialized",
                version=version,
                build=ComponentBuild(), # NOTE: deferring this to later Version and build traceability step
                metadata={}
            )

        health = await opensearch.cluster.health()
        info = await opensearch.info()
        cluster_status = health.get("status")
        os_version = (info.get("version") or {}).get("number")
        distribution = (info.get("version") or {}).get("distribution")

        status = {
            "green": ComponentState.HEALTHY,
            "yellow": ComponentState.DEGRADED,
            "red": ComponentState.UNHEALTHY
        }.get(cluster_status, ComponentState.UNKNOWN)
        message = f"Cluster Health is {cluster_status}"
        metadata={
            "cluster_name": health.get("cluster_name"),
            "cluster_health": cluster_status,
            "distribution": distribution
        }

    except Exception as e:
        logger.warning("OpenSearch status check failed", error=str(e))

        status, message = ComponentState.UNHEALTHY, "OpenSearch is unreachable"
        metadata = {}

    return ComponentStatus(
        name="opensearch",
        display_name="OpenSearch",
        status=status,
        required=True,
        latency_ms=int((perf_counter() - start) * 1000),
        message=message,
        version=os_version,
        build=ComponentBuild(), # NOTE: deferring this to later Version and build traceability step
        metadata=metadata
    )