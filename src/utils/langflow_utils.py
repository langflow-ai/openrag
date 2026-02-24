import asyncio
import random

import httpx

from utils.logging_config import get_logger

logger = get_logger(__name__)


class LangflowNotReadyError(Exception):
    """Raised when Langflow fails to become ready within the retry limit."""


async def wait_for_langflow(
    langflow_http_client: httpx.AsyncClient | None = None,
    max_retries: int = 10,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
) -> None:
    """Wait for Langflow to be ready with exponential backoff and jitter.

    Args:
        langflow_http_client: The httpx client to use for health checks. If None,
            falls back to clients.langflow_http_client from config.settings.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Upper bound in seconds for the retry delay.

    Raises:
        LangflowNotReadyError: If Langflow fails to become ready within the retry limit.
    """
    if langflow_http_client is None:
        from config.settings import clients
        langflow_http_client = clients.langflow_http_client

    for attempt in range(max_retries):
        display_attempt: int = attempt + 1

        logger.info(
            "Verifying whether the Langflow service is ready...",
            attempt=display_attempt,
            max_retries=max_retries,
        )

        try:
            response = await langflow_http_client.get("/health", timeout=5.0)
            status_code = response.status_code

            if status_code == 200:
                logger.info(
                    "Successfully verified that the Langflow service is ready.",
                    attempt=display_attempt,
                    max_retries=max_retries,
                    status_code=status_code,
                )
                return
            else:
                logger.warning(
                    "The Langflow service is not ready. Encountered a non-200 HTTP status_code.",
                    attempt=display_attempt,
                    max_retries=max_retries,
                    status_code=status_code,
                )
        except Exception as e:
            logger.warning(
                "The Langflow service is not ready.",
                attempt=display_attempt,
                max_retries=max_retries,
                error=str(e),
            )

        if attempt < max_retries - 1:
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay = random.uniform(delay / 2, delay)

            logger.debug(
                "Retry the Langflow service readiness check after a delay (seconds).",
                attempt=display_attempt,
                max_retries=max_retries,
                delay=delay,
            )

            await asyncio.sleep(delay)

    message: str = "Failed to verify whether the Langflow service is ready."
    logger.error(message)
    raise LangflowNotReadyError(message)
