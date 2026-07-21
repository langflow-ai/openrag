"""Cached IBM Cloud IAM token exchange for watsonx.ai.

watsonx.ai endpoints require a short-lived IAM bearer token (~1h TTL) obtained
from an IBM Cloud API key. This module exchanges and caches tokens so callers
(e.g. the Docling VLM pipeline) don't hit the IAM endpoint on every request.
"""

import asyncio
import time

import httpx

from utils.logging_config import get_logger

logger = get_logger(__name__)

IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"

# Refresh tokens that expire within this margin so in-flight conversions
# don't start with a nearly-expired token.
_REFRESH_MARGIN_SECONDS = 300

_cache: dict[str, tuple[str, float]] = {}  # api_key -> (token, expiry_epoch)
_lock = asyncio.Lock()


class WatsonxIamError(Exception):
    """Raised when the IAM token exchange fails with a non-transient error."""


async def get_iam_token(api_key: str, http_timeout: float = 15.0) -> str:
    """Exchange an IBM Cloud API key for an IAM bearer token, with caching.

    Raises:
        httpx.RequestError: network-level failure (caller may retry).
        WatsonxIamError: IAM rejected the exchange or returned no token.
    """
    async with _lock:
        cached = _cache.get(api_key)
        if cached and cached[1] - time.time() > _REFRESH_MARGIN_SECONDS:
            return cached[0]

        async with httpx.AsyncClient(timeout=http_timeout) as client:
            response = await client.post(
                IAM_TOKEN_URL,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
            )

        if response.status_code != 200:
            raise WatsonxIamError(
                f"IBM IAM token exchange failed: HTTP {response.status_code} {response.text[:200]}"
            )

        data = response.json()
        token = data.get("access_token")
        if not token:
            raise WatsonxIamError("IBM IAM response did not contain access_token")

        expiry = data.get("expiration") or (time.time() + float(data.get("expires_in", 3600)))
        _cache[api_key] = (token, float(expiry))
        logger.debug("Obtained IBM IAM token", expires_at=expiry)
        return token
