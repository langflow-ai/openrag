"""Wait for docling-serve to be healthy before proceeding."""

import logging
import os
import sys
import time

import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

url = os.getenv("DOCLING_SERVE_URL", "http://localhost:5001")
timeout = int(os.getenv("DOCLING_WARMUP_TIMEOUT", "120"))

logger.info("Waiting for docling-serve at %s (timeout: %ds)", url, timeout)

start = time.time()
while time.time() - start < timeout:
    try:
        resp = httpx.get(f"{url}/health", timeout=2.0)
        if resp.status_code == 200:
            logger.info("docling-serve is healthy (%.1fs)", time.time() - start)
            sys.exit(0)
    except Exception:
        pass
    time.sleep(2)

logger.error("docling-serve did not become healthy within %ds", timeout)
sys.exit(1)
