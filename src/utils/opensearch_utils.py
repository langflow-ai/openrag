import asyncio
import random
from opensearchpy import AsyncOpenSearch
from utils.logging_config import get_logger

logger = get_logger(__name__)

DISK_SPACE_ERROR_MESSAGE = (
    "OpenSearch has run out of available disk space. "
    "Search and indexing operations are blocked. "
    "Please free up disk space to restore OpenRAG functionality."
)

# Error strings emitted by OpenSearch when disk watermark thresholds are breached
_DISK_SPACE_INDICATORS = [
    "disk watermark",
    "flood_stage",
    "flood stage",
    "disk usage exceeded",
    "index read-only",
    "no space left on device",
    "cluster_block_exception",
    "forbidden/12",
    "too_many_requests/12",
]


class OpenSearchNotReadyError(Exception):
    """Raised when OpenSearch fails to become ready within the retry limit."""


class OpenSearchDiskSpaceError(Exception):
    """Raised when OpenSearch operations fail due to insufficient disk space."""


def is_disk_space_error(error: Exception) -> bool:
    """Check whether an exception is caused by OpenSearch disk space constraints.

    OpenSearch blocks write and search operations when disk usage crosses
    the high-watermark or flood-stage watermark thresholds.
    This function detects those error signatures.

    Args:
        error: The exception to inspect.

    Returns:
        True if the error is disk-space related, False otherwise.
    """
    error_str = str(error).lower()
    return any(indicator in error_str for indicator in _DISK_SPACE_INDICATORS)

async def wait_for_opensearch(
    opensearch_client: AsyncOpenSearch,
    max_retries: int = 15,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> None:
    """Wait for OpenSearch to be ready with exponential backoff and jitter.

    Args:
        opensearch_client: The OpenSearch client to use for health checks.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Upper bound in seconds for the retry delay.

    Raises:
        OpenSearchNotReadyError: If OpenSearch fails to become ready within the retry limit.
    """
    for attempt in range(max_retries):
        display_attempt: int = attempt + 1

        logger.info(
            "Verifying whether OpenSearch is ready...",
            attempt=display_attempt,
            max_retries=max_retries,
        )

        try:
            # Simple ping to check connection
            if await opensearch_client.ping():
                # Also check cluster health
                health = await opensearch_client.cluster.health()
                status = health.get("status")
                if status in ["green", "yellow"]:
                    logger.info(
                        "Successfully verified that OpenSearch is ready.",
                        attempt=display_attempt,
                        status=status,
                    )
                    return
                else:
                    logger.warning(
                        "OpenSearch is up but cluster health is red.",
                        attempt=display_attempt,
                        status=status,
                    )
            else:
                logger.warning(
                    "OpenSearch ping failed.",
                    attempt=display_attempt,
                )
        except Exception as e:
            logger.warning(
                "OpenSearch is not ready.",
                attempt=display_attempt,
                error=str(e),
            )

        if attempt < max_retries - 1:
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay = random.uniform(delay / 2, delay)

            logger.debug(
                "Retry OpenSearch readiness check after a delay (seconds).",
                attempt=display_attempt,
                delay=delay,
            )

            await asyncio.sleep(delay)

    message: str = "Failed to verify whether OpenSearch is ready."
    logger.error(message)
    raise OpenSearchNotReadyError(message)


async def graceful_opensearch_shutdown(opensearch_client: AsyncOpenSearch) -> None:
    """Gracefully shutdown OpenSearch client connection.
    
    This ensures that all pending operations are completed and connections
    are properly closed before the application exits.
    
    Args:
        opensearch_client: The OpenSearch client to shutdown.
    """
    if opensearch_client is None:
        logger.debug("OpenSearch client is None, skipping graceful shutdown")
        return
    
    try:
        logger.info("Initiating graceful OpenSearch shutdown...")
        
        # Flush any pending write operations before closing
        try:
            await asyncio.wait_for(
                opensearch_client.indices.flush(index="_all", wait_if_ongoing=True),
                timeout=10.0
            )
            logger.debug("Index flush completed")
        except asyncio.TimeoutError:
            logger.warning("Timeout during index flush")
        except Exception as e:
            logger.warning("Error during index flush", error=str(e))
        
        # Close the client connection
        await opensearch_client.close()
        logger.info("OpenSearch client connection closed gracefully")
        
    except Exception as e:
        logger.error("Error during graceful OpenSearch shutdown", error=str(e))

