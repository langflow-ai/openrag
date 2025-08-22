import hashlib
import os
from collections import defaultdict
from .gpu_detection import detect_gpu_devices

# Global converter cache for worker processes
_worker_converter = None

def get_worker_converter():
    """Get or create a DocumentConverter instance for this worker process"""
    global _worker_converter
    if _worker_converter is None:
        from docling.document_converter import DocumentConverter
        
        # Configure GPU settings for this worker
        has_gpu_devices, _ = detect_gpu_devices()
        if not has_gpu_devices:
            # Force CPU-only mode in subprocess
            os.environ['USE_CPU_ONLY'] = 'true'
            os.environ['CUDA_VISIBLE_DEVICES'] = ''
            os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'
            os.environ['TRANSFORMERS_OFFLINE'] = '0'
            os.environ['TORCH_USE_CUDA_DSA'] = '0'
            
            # Try to disable CUDA in torch if available
            try:
                import torch
                torch.cuda.is_available = lambda: False
            except ImportError:
                pass
        else:
            # GPU mode - let libraries use GPU if available
            os.environ.pop('USE_CPU_ONLY', None)
            os.environ['HF_HUB_DISABLE_PROGRESS_BARS'] = '1'  # Still disable progress bars
        
        print(f"[WORKER {os.getpid()}] Initializing DocumentConverter in worker process")
        _worker_converter = DocumentConverter()
        print(f"[WORKER {os.getpid()}] DocumentConverter ready in worker process")
    
    return _worker_converter

def extract_relevant(doc_dict: dict) -> dict:
    """
    Given the full export_to_dict() result:
      - Grabs origin metadata (hash, filename, mimetype)
      - Finds every text fragment in `texts`, groups them by page_no
      - Flattens tables in `tables` into tab-separated text, grouping by row
      - Concatenates each page's fragments and each table into its own chunk
    Returns a slimmed dict ready for indexing, with each chunk under "text".
    """
    origin = doc_dict.get("origin", {})
    chunks = []

    # 1) process free-text fragments
    page_texts = defaultdict(list)
    for txt in doc_dict.get("texts", []):
        prov = txt.get("prov", [])
        page_no = prov[0].get("page_no") if prov else None
        if page_no is not None:
            page_texts[page_no].append(txt.get("text", "").strip())

    for page in sorted(page_texts):
        chunks.append({
            "page": page,
            "type": "text",
            "text": "\n".join(page_texts[page])
        })

    # 2) process tables
    for t_idx, table in enumerate(doc_dict.get("tables", [])):
        prov = table.get("prov", [])
        page_no = prov[0].get("page_no") if prov else None

        # group cells by their row index
        rows = defaultdict(list)
        for cell in table.get("data").get("table_cells", []):
            r = cell.get("start_row_offset_idx")
            c = cell.get("start_col_offset_idx")
            text = cell.get("text", "").strip()
            rows[r].append((c, text))

        # build a tab‑separated line for each row, in order
        flat_rows = []
        for r in sorted(rows):
            cells = [txt for _, txt in sorted(rows[r], key=lambda x: x[0])]
            flat_rows.append("\t".join(cells))

        chunks.append({
            "page": page_no,
            "type": "table",
            "table_index": t_idx,
            "text": "\n".join(flat_rows)
        })

    return {
        "id": origin.get("binary_hash"),
        "filename": origin.get("filename"),
        "mimetype": origin.get("mimetype"),
        "chunks": chunks
    }

def process_document_sync(file_path: str):
    """Synchronous document processing function for multiprocessing"""
    import traceback
    import psutil
    import sys
    from collections import defaultdict
    
    process = psutil.Process()
    start_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    try:
        print(f"[WORKER {os.getpid()}] Starting document processing: {file_path}")
        print(f"[WORKER {os.getpid()}] Initial memory usage: {start_memory:.1f} MB")
        
        # Check file size
        try:
            file_size = os.path.getsize(file_path) / 1024 / 1024  # MB
            print(f"[WORKER {os.getpid()}] File size: {file_size:.1f} MB")
        except OSError as e:
            print(f"[WORKER {os.getpid()}] WARNING: Cannot get file size: {e}")
            file_size = 0
        
        # Get the cached converter for this worker
        try:
            print(f"[WORKER {os.getpid()}] Getting document converter...")
            converter = get_worker_converter()
            memory_after_converter = process.memory_info().rss / 1024 / 1024
            print(f"[WORKER {os.getpid()}] Memory after converter init: {memory_after_converter:.1f} MB")
        except Exception as e:
            print(f"[WORKER {os.getpid()}] ERROR: Failed to initialize converter: {e}")
            traceback.print_exc()
            raise
        
        # Compute file hash
        try:
            print(f"[WORKER {os.getpid()}] Computing file hash...")
            sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    sha256.update(chunk)
            file_hash = sha256.hexdigest()
            print(f"[WORKER {os.getpid()}] File hash computed: {file_hash[:12]}...")
        except Exception as e:
            print(f"[WORKER {os.getpid()}] ERROR: Failed to compute file hash: {e}")
            traceback.print_exc()
            raise
        
        # Convert with docling
        try:
            print(f"[WORKER {os.getpid()}] Starting docling conversion...")
            memory_before_convert = process.memory_info().rss / 1024 / 1024
            print(f"[WORKER {os.getpid()}] Memory before conversion: {memory_before_convert:.1f} MB")
            
            result = converter.convert(file_path)
            
            memory_after_convert = process.memory_info().rss / 1024 / 1024
            print(f"[WORKER {os.getpid()}] Memory after conversion: {memory_after_convert:.1f} MB")
            print(f"[WORKER {os.getpid()}] Docling conversion completed")
            
            full_doc = result.document.export_to_dict()
            memory_after_export = process.memory_info().rss / 1024 / 1024
            print(f"[WORKER {os.getpid()}] Memory after export: {memory_after_export:.1f} MB")
            
        except Exception as e:
            print(f"[WORKER {os.getpid()}] ERROR: Failed during docling conversion: {e}")
            print(f"[WORKER {os.getpid()}] Current memory usage: {process.memory_info().rss / 1024 / 1024:.1f} MB")
            traceback.print_exc()
            raise
        
        # Extract relevant content (same logic as extract_relevant)
        try:
            print(f"[WORKER {os.getpid()}] Extracting relevant content...")
            origin = full_doc.get("origin", {})
            texts = full_doc.get("texts", [])
            print(f"[WORKER {os.getpid()}] Found {len(texts)} text fragments")

            page_texts = defaultdict(list)
            for txt in texts:
                prov = txt.get("prov", [])
                page_no = prov[0].get("page_no") if prov else None
                if page_no is not None:
                    page_texts[page_no].append(txt.get("text", "").strip())

            chunks = []
            for page in sorted(page_texts):
                joined = "\n".join(page_texts[page])
                chunks.append({
                    "page": page,
                    "text": joined
                })
            
            print(f"[WORKER {os.getpid()}] Created {len(chunks)} chunks from {len(page_texts)} pages")
            
        except Exception as e:
            print(f"[WORKER {os.getpid()}] ERROR: Failed during content extraction: {e}")
            traceback.print_exc()
            raise

        final_memory = process.memory_info().rss / 1024 / 1024
        memory_delta = final_memory - start_memory
        print(f"[WORKER {os.getpid()}] Document processing completed successfully")
        print(f"[WORKER {os.getpid()}] Final memory: {final_memory:.1f} MB (Delta +{memory_delta:.1f} MB)")
        
        return {
            "id": file_hash,
            "filename": origin.get("filename"),
            "mimetype": origin.get("mimetype"),
            "chunks": chunks,
            "file_path": file_path
        }
        
    except Exception as e:
        final_memory = process.memory_info().rss / 1024 / 1024
        memory_delta = final_memory - start_memory
        print(f"[WORKER {os.getpid()}] FATAL ERROR in process_document_sync")
        print(f"[WORKER {os.getpid()}] File: {file_path}")
        print(f"[WORKER {os.getpid()}] Python version: {sys.version}")
        print(f"[WORKER {os.getpid()}] Memory at crash: {final_memory:.1f} MB (Delta +{memory_delta:.1f} MB)")
        print(f"[WORKER {os.getpid()}] Error: {type(e).__name__}: {e}")
        print(f"[WORKER {os.getpid()}] Full traceback:")
        traceback.print_exc()
        
        # Try to get more system info before crashing
        try:
            import platform
            print(f"[WORKER {os.getpid()}] System: {platform.system()} {platform.release()}")
            print(f"[WORKER {os.getpid()}] Architecture: {platform.machine()}")
        except:
            pass
            
        # Re-raise to trigger BrokenProcessPool in main process
        raise