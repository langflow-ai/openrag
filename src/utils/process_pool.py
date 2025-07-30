import os
from concurrent.futures import ProcessPoolExecutor
from utils.gpu_detection import get_worker_count

# Create shared process pool at import time (before CUDA initialization)
# This avoids the "Cannot re-initialize CUDA in forked subprocess" error
MAX_WORKERS = get_worker_count()
process_pool = ProcessPoolExecutor(max_workers=MAX_WORKERS)

print(f"Shared process pool initialized with {MAX_WORKERS} workers")