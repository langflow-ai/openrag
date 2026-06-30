# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

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
