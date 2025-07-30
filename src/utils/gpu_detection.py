import multiprocessing
import os

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
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
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
        print(f"GPU mode enabled with {gpu_count} GPU(s) - using limited concurrency ({default_workers} workers)")
    else:
        default_workers = multiprocessing.cpu_count()
        print(f"CPU-only mode enabled - using full concurrency ({default_workers} workers)")
    
    return int(os.getenv("MAX_WORKERS", default_workers))