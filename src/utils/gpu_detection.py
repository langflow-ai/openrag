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
    """Get optimal worker count based on GPU availability"""
    has_gpu_devices, gpu_count = detect_gpu_devices()

    if has_gpu_devices:
        default_workers = min(4, multiprocessing.cpu_count() // 2)
        logger.info(
            "GPU mode enabled with limited concurrency",
            gpu_count=gpu_count,
            worker_count=default_workers,
        )
    else:
        default_workers = multiprocessing.cpu_count()
        logger.info(
            "CPU-only mode enabled with full concurrency", worker_count=default_workers
        )

    return int(os.getenv("MAX_WORKERS", default_workers))
