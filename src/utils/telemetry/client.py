"""Telemetry client for OpenRAG backend using Scarf."""

import asyncio
import os
import platform
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Constants
SCARF_BASE_URL_DEFAULT = "https://langflow.gateway.scarf.sh"
SCARF_PATH = "openrag"
CLIENT_TYPE = "backend"
PLATFORM_TYPE = "backend"


def _get_openrag_version() -> str:
    """Get OpenRAG version from package metadata."""
    try:
        from importlib.metadata import version, PackageNotFoundError
        
        try:
            return version("openrag")
        except PackageNotFoundError:
            # Fallback: try to read from pyproject.toml if package not installed (dev mode)
            try:
                import tomllib
                from pathlib import Path
                
                # Try to find pyproject.toml relative to this file
                current_file = Path(__file__)
                project_root = current_file.parent.parent.parent.parent
                pyproject_path = project_root / "pyproject.toml"
                
                if pyproject_path.exists():
                    with open(pyproject_path, "rb") as f:
                        data = tomllib.load(f)
                        return data.get("project", {}).get("version", "dev")
            except Exception:
                pass
            
            return "dev"
    except Exception as e:
        logger.warning(f"Failed to get OpenRAG version: {e}")
        return "unknown"


# Get version dynamically
OPENRAG_VERSION = _get_openrag_version()

# HTTP timeouts
HTTP_REQUEST_TIMEOUT = 10.0
HTTP_CONNECT_TIMEOUT = 5.0

# Retry configuration
RETRY_BASE_MS = 250
MAX_WAIT_INTERVAL_MS = 5000
MAX_RETRIES = 3

# Global HTTP client
_http_client: Optional[httpx.AsyncClient] = None
_base_url_override: Optional[str] = None


def _get_http_client() -> Optional[httpx.AsyncClient]:
    """Get or create the HTTP client for telemetry."""
    global _http_client
    if _http_client is None:
        try:
            _http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=HTTP_CONNECT_TIMEOUT,
                    read=HTTP_REQUEST_TIMEOUT,
                    write=HTTP_REQUEST_TIMEOUT,
                    pool=HTTP_CONNECT_TIMEOUT,
                ),
                headers={
                    "User-Agent": f"OpenRAG-Backend/{OPENRAG_VERSION}",
                },
            )
            logger.debug("Telemetry HTTP client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize telemetry HTTP client: {e}")
            return None
    return _http_client


def set_base_url(url: str) -> None:
    """Override the default Scarf base URL (for testing)."""
    global _base_url_override
    _base_url_override = url
    logger.info(f"Telemetry base URL overridden: {url}")


def _get_effective_base_url() -> str:
    """Get the effective base URL (override or default)."""
    return _base_url_override or SCARF_BASE_URL_DEFAULT


def is_do_not_track() -> bool:
    """Check if DO_NOT_TRACK environment variable is set."""
    do_not_track = os.environ.get("DO_NOT_TRACK", "").lower()
    return do_not_track in ("true", "1", "yes", "on")


def _get_os() -> str:
    """Get the operating system identifier."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    elif system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    else:
        return "unknown"


def _get_os_version() -> str:
    """Get the operating system version."""
    try:
        system = platform.system().lower()
        if system == "darwin":
            # macOS version
            return platform.mac_ver()[0] if platform.mac_ver()[0] else "unknown"
        elif system == "windows":
            # Windows version
            return platform.win32_ver()[0] if platform.win32_ver()[0] else "unknown"
        elif system == "linux":
            # Linux - try to get distribution info
            try:
                import distro
                return f"{distro.name()} {distro.version()}".strip() or platform.release()
            except ImportError:
                # Fallback to platform.release() if distro not available
                return platform.release()
        else:
            return platform.release()
    except Exception:
        return "unknown"


def _get_gpu_info() -> dict:
    """Get GPU information for telemetry."""
    gpu_info = {
        "gpu_available": False,
        "gpu_count": 0,
        "cuda_available": False,
        "cuda_version": None,
    }
    
    try:
        # Try to use the existing GPU detection utility
        from utils.gpu_detection import detect_gpu_devices
        
        has_gpu, gpu_count = detect_gpu_devices()
        gpu_info["gpu_available"] = has_gpu
        gpu_info["gpu_count"] = gpu_count if isinstance(gpu_count, int) else 0
        
        # Also check CUDA availability via torch
        try:
            import torch
            gpu_info["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                gpu_info["cuda_version"] = torch.version.cuda or "unknown"
        except ImportError:
            pass
    except Exception as e:
        logger.debug(f"Failed to detect GPU info: {e}")
    
    return gpu_info


def _get_current_utc() -> str:
    """Get current UTC time as RFC 3339 formatted string."""
    now = datetime.now(timezone.utc)
    return now.isoformat().replace("+00:00", "Z")


def _get_exponential_backoff_delay(attempt: int) -> float:
    """Calculate exponential backoff delay with full jitter (in seconds).
    
    Formula:
    temp = min(MAX_BACKOFF, base * 2^attempt)
    sleep = random_between(0, temp)
    """
    import random
    
    exp = min(2 ** attempt, MAX_WAIT_INTERVAL_MS // RETRY_BASE_MS)
    temp_ms = RETRY_BASE_MS * exp
    temp_ms = min(temp_ms, MAX_WAIT_INTERVAL_MS)
    
    # Full jitter: random duration between 0 and temp_ms
    sleep_ms = random.uniform(0, temp_ms) if temp_ms > 0 else 0
    return sleep_ms / 1000.0  # Convert to seconds


async def _send_scarf_event(
    category: str,
    message_id: str,
    metadata: dict = None,
) -> None:
    """Send a telemetry event to Scarf.
    
    Args:
        category: Event category
        message_id: Event message ID
        metadata: Optional dictionary of additional metadata to include in the event
    """
    if is_do_not_track():
        logger.debug(
            f"Telemetry event aborted: {category}:{message_id}. DO_NOT_TRACK is enabled"
        )
        return
    
    http_client = _get_http_client()
    if http_client is None:
        logger.error(
            f"Telemetry event aborted: {category}:{message_id}. HTTP client not initialized"
        )
        return
    
    os_name = _get_os()
    os_version = _get_os_version()
    gpu_info = _get_gpu_info()
    timestamp = _get_current_utc()
    effective_base_url = _get_effective_base_url()
    # Build URL with format: /openrag/{platform}.{version}
    base_url = f"{effective_base_url}/{SCARF_PATH}/{PLATFORM_TYPE}.{OPENRAG_VERSION}"
    
    # Build query parameters
    params = {
        "clientType": CLIENT_TYPE,
        "openrag_version": OPENRAG_VERSION,
        "platform": PLATFORM_TYPE,
        "os": os_name,
        "os_version": os_version,
        "gpu_available": str(gpu_info["gpu_available"]).lower(),
        "gpu_count": str(gpu_info["gpu_count"]),
        "cuda_available": str(gpu_info["cuda_available"]).lower(),
        "category": category,
        "message_id": message_id,
        "timestamp": timestamp,
    }
    
    # Add CUDA version if available
    if gpu_info["cuda_version"]:
        params["cuda_version"] = str(gpu_info["cuda_version"])
    
    # Add metadata if provided
    if metadata:
        for key, value in metadata.items():
            if value is not None:
                # URL encode the value
                params[key] = str(value)
    
    url = f"{base_url}?{urlencode(params)}"
    retry_count = 0
    
    while retry_count < MAX_RETRIES:
        if retry_count == 0:
            logger.info(f"Sending telemetry event: {category}:{message_id}...")
        else:
            logger.info(
                f"Sending telemetry event: {category}:{message_id}. Retry #{retry_count}..."
            )
        
        logger.debug(f"Telemetry URL: {url}")
        
        try:
            response = await http_client.get(url)
            status = response.status_code
            
            if 200 <= status < 300:
                logger.info(
                    f"Successfully sent telemetry event: {category}:{message_id}. Status: {status}"
                )
                return
            elif 500 <= status < 600:
                # Retry server errors
                logger.error(
                    f"Failed to send telemetry event: {category}:{message_id}. Status: {status}"
                )
            else:
                # Non-retryable status codes (400, 401, 403, 404, 429, etc.)
                logger.error(
                    f"Failed to send telemetry event: {category}:{message_id}. "
                    f"Status: {status} (non-retryable)"
                )
                return
                
        except httpx.TimeoutException as e:
            # Retry timeout errors
            logger.error(
                f"Failed to send telemetry event: {category}:{message_id}. "
                f"Timeout error: {e}"
            )
        except httpx.ConnectError as e:
            # Retry connection errors
            logger.error(
                f"Failed to send telemetry event: {category}:{message_id}. "
                f"Connection error: {e}"
            )
        except httpx.RequestError as e:
            # Non-retryable request errors
            logger.error(
                f"Failed to send telemetry event: {category}:{message_id}. "
                f"Request error: {e}"
            )
            return
        except Exception as e:
            logger.error(
                f"Failed to send telemetry event: {category}:{message_id}. "
                f"Unknown error: {e}"
            )
        
        retry_count += 1
        
        if retry_count < MAX_RETRIES:
            delay = _get_exponential_backoff_delay(retry_count)
            await asyncio.sleep(delay)
    
    logger.error(
        f"Failed to send telemetry event: {category}:{message_id}. "
        f"Maximum retries exceeded: {MAX_RETRIES}"
    )


class TelemetryClient:
    """Telemetry client for sending events to Scarf."""
    
    @staticmethod
    async def send_event(category: str, message_id: str, metadata: dict = None) -> None:
        """Send a telemetry event asynchronously.
        
        Args:
            category: Event category
            message_id: Event message ID
            metadata: Optional dictionary of additional metadata (e.g., {"llm_model": "gpt-4o"})
        """
        if is_do_not_track():
            logger.debug(
                f"Telemetry event aborted: {category}:{message_id}. DO_NOT_TRACK is enabled"
            )
            return
        
        try:
            await _send_scarf_event(category, message_id, metadata)
        except Exception as e:
            logger.error(f"Error sending telemetry event: {e}")
    
    @staticmethod
    def send_event_sync(category: str, message_id: str, metadata: dict = None) -> None:
        """Send a telemetry event synchronously (creates a task).
        
        This is a convenience method for use in synchronous contexts.
        It creates an async task but doesn't wait for it.
        
        Args:
            category: Event category
            message_id: Event message ID
            metadata: Optional dictionary of additional metadata
        """
        if is_do_not_track():
            logger.debug(
                f"Telemetry event aborted: {category}:{message_id}. DO_NOT_TRACK is enabled"
            )
            return
        
        try:
            # Try to get the current event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If loop is running, create a task
                    asyncio.create_task(_send_scarf_event(category, message_id, metadata))
                else:
                    # If loop exists but not running, run it
                    loop.run_until_complete(_send_scarf_event(category, message_id, metadata))
            except RuntimeError:
                # No event loop, create a new one
                asyncio.run(_send_scarf_event(category, message_id, metadata))
        except Exception as e:
            logger.error(f"Error sending telemetry event: {e}")


async def cleanup_telemetry_client() -> None:
    """Cleanup the telemetry HTTP client."""
    global _http_client
    if _http_client is not None:
        try:
            await _http_client.aclose()
            _http_client = None
            logger.debug("Telemetry HTTP client closed")
        except Exception as e:
            logger.error(f"Error closing telemetry HTTP client: {e}")

