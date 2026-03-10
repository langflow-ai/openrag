import multiprocessing
import os
from utils.logging_config import get_logger

logger = get_logger(__name__)


def detect_gpu_devices():
    """Detect if GPU devices are actually available"""
    try:
        import torch

        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return True, torch.cuda.device_count()
    except ImportError:
        pass

    try:
        import subprocess

        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        if result.returncode == 0:
            return True, "detected"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return False, 0


def get_worker_count():
    """Get optimal worker count based on downstream service capacity.

    The worker count controls concurrent ingestion requests to Langflow/Docling.
    The bottleneck is not the backend CPU (which is I/O-bound waiting on HTTP),
    but rather Langflow and Docling's processing capacity (default: 1 worker each).

    Uses min(4, cpu_count // 2) for both GPU and CPU modes to maintain a
    reasonable ratio with downstream services (4 backend : 1 Langflow worker).
    """
    has_gpu_devices, gpu_count = detect_gpu_devices()

    # Same formula for both modes: cap at 4, use half of available CPUs
    default_worker_count = max(1, min(4, multiprocessing.cpu_count() // 2))
    worker_count = max(1, int(os.getenv("MAX_WORKERS", default_worker_count)))
    mode = "GPU" if has_gpu_devices else "CPU-only"

    logger.info(
        f"{mode} mode enabled",
        gpu_count=gpu_count,
        worker_count=worker_count,
        default_worker_count=default_worker_count,
    )

    return worker_count
