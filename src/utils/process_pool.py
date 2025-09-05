import os
from concurrent.futures import ProcessPoolExecutor
from utils.gpu_detection import get_worker_count
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Create shared process pool at import time (before CUDA initialization)
# This avoids the "Cannot re-initialize CUDA in forked subprocess" error
MAX_WORKERS = get_worker_count()
process_pool = ProcessPoolExecutor(max_workers=MAX_WORKERS)

logger.info("Shared process pool initialized", max_workers=MAX_WORKERS)
