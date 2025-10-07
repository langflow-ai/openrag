import hashlib
import os
import sys
import platform
from collections import defaultdict
from .gpu_detection import detect_gpu_devices
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Global converter cache for worker processes
_worker_converter = None


def create_document_converter(ocr_engine: str | None = None):
    """Create a Docling DocumentConverter with OCR disabled unless requested."""
    if ocr_engine is None:
        ocr_engine = os.getenv("DOCLING_OCR_ENGINE")

    try:
        from docling.document_converter import (
            DocumentConverter,
            InputFormat,
            PdfFormatOption,
        )
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except Exception as exc:  # pragma: no cover - fallback path
        logger.debug(
            "Falling back to default DocumentConverter import",
            error=str(exc),
        )
        from docling.document_converter import DocumentConverter  # type: ignore

        return DocumentConverter()

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False

    if ocr_engine:
        try:
            from docling.models.factories import get_ocr_factory

            factory = get_ocr_factory(allow_external_plugins=False)
            pipeline_options.do_ocr = True
            pipeline_options.ocr_options = factory.create_options(kind=ocr_engine)
        except Exception as exc:  # pragma: no cover - optional path
            pipeline_options.do_ocr = False
            logger.warning(
                "Unable to enable requested Docling OCR engine, using OCR-off",
                ocr_engine=ocr_engine,
                error=str(exc),
            )

    format_options = {}
    if hasattr(InputFormat, "PDF"):
        format_options[getattr(InputFormat, "PDF")] = PdfFormatOption(
            pipeline_options=pipeline_options
        )
    if hasattr(InputFormat, "IMAGE"):
        format_options[getattr(InputFormat, "IMAGE")] = PdfFormatOption(
            pipeline_options=pipeline_options
        )

    try:
        converter = DocumentConverter(
            format_options=format_options if format_options else None
        )
    except Exception as exc:  # pragma: no cover - fallback path
        logger.warning(
            "Docling converter initialization failed, falling back to defaults",
            error=str(exc),
        )
        converter = DocumentConverter()

    logger.info(
        "Docling converter initialized",
        ocr_engine=ocr_engine if pipeline_options.do_ocr else None,
        ocr_enabled=pipeline_options.do_ocr,
    )

    return converter


def get_worker_converter():
    """Get or create a DocumentConverter instance for this worker process"""
    global _worker_converter
    if _worker_converter is None:
        
        # Configure GPU settings for this worker
        has_gpu_devices, _ = detect_gpu_devices()
        if not has_gpu_devices:
            # Force CPU-only mode in subprocess
            os.environ["USE_CPU_ONLY"] = "true"
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "0"
            os.environ["TORCH_USE_CUDA_DSA"] = "0"

            # Try to disable CUDA in torch if available
            try:
                import torch

                torch.cuda.is_available = lambda: False
            except ImportError:
                pass
        else:
            # GPU mode - let libraries use GPU if available
            os.environ.pop("USE_CPU_ONLY", None)
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = (
                "1"  # Still disable progress bars
            )

        logger.info(
            "Initializing DocumentConverter in worker process", worker_pid=os.getpid()
        )
        _worker_converter = create_document_converter()
        logger.info("DocumentConverter ready in worker process", worker_pid=os.getpid())

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
        chunks.append(
            {"page": page, "type": "text", "text": "\n".join(page_texts[page])}
        )

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

        chunks.append(
            {
                "page": page_no,
                "type": "table",
                "table_index": t_idx,
                "text": "\n".join(flat_rows),
            }
        )

    return {
        "id": origin.get("binary_hash"),
        "filename": origin.get("filename"),
        "mimetype": origin.get("mimetype"),
        "chunks": chunks,
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
        logger.info(
            "Starting document processing",
            worker_pid=os.getpid(),
            file_path=file_path,
            initial_memory_mb=f"{start_memory:.1f}",
        )

        # Check file size
        try:
            file_size = os.path.getsize(file_path) / 1024 / 1024  # MB
            logger.info(
                "File size determined",
                worker_pid=os.getpid(),
                file_size_mb=f"{file_size:.1f}",
            )
        except OSError as e:
            logger.warning("Cannot get file size", worker_pid=os.getpid(), error=str(e))
            file_size = 0

        # Get the cached converter for this worker
        try:
            logger.info("Getting document converter", worker_pid=os.getpid())
            converter = get_worker_converter()
            memory_after_converter = process.memory_info().rss / 1024 / 1024
            logger.info(
                "Memory after converter init",
                worker_pid=os.getpid(),
                memory_mb=f"{memory_after_converter:.1f}",
            )
        except Exception as e:
            logger.error(
                "Failed to initialize converter", worker_pid=os.getpid(), error=str(e)
            )
            traceback.print_exc()
            raise

        # Compute file hash
        try:
            from utils.hash_utils import hash_id
            logger.info("Computing file hash", worker_pid=os.getpid())
            file_hash = hash_id(file_path)
            logger.info(
                "File hash computed",
                worker_pid=os.getpid(),
                file_hash_prefix=file_hash[:12],
            )
        except Exception as e:
            logger.error(
                "Failed to compute file hash", worker_pid=os.getpid(), error=str(e)
            )
            traceback.print_exc()
            raise

        # Convert with docling
        try:
            logger.info("Starting docling conversion", worker_pid=os.getpid())
            memory_before_convert = process.memory_info().rss / 1024 / 1024
            logger.info(
                "Memory before conversion",
                worker_pid=os.getpid(),
                memory_mb=f"{memory_before_convert:.1f}",
            )

            result = converter.convert(file_path)

            memory_after_convert = process.memory_info().rss / 1024 / 1024
            logger.info(
                "Memory after conversion",
                worker_pid=os.getpid(),
                memory_mb=f"{memory_after_convert:.1f}",
            )
            logger.info("Docling conversion completed", worker_pid=os.getpid())

            full_doc = result.document.export_to_dict()
            memory_after_export = process.memory_info().rss / 1024 / 1024
            logger.info(
                "Memory after export",
                worker_pid=os.getpid(),
                memory_mb=f"{memory_after_export:.1f}",
            )

        except Exception as e:
            current_memory = process.memory_info().rss / 1024 / 1024
            logger.error(
                "Failed during docling conversion",
                worker_pid=os.getpid(),
                error=str(e),
                current_memory_mb=f"{current_memory:.1f}",
            )
            traceback.print_exc()
            raise

        # Extract relevant content (same logic as extract_relevant)
        try:
            logger.info("Extracting relevant content", worker_pid=os.getpid())
            origin = full_doc.get("origin", {})
            texts = full_doc.get("texts", [])
            logger.info(
                "Found text fragments",
                worker_pid=os.getpid(),
                fragment_count=len(texts),
            )

            page_texts = defaultdict(list)
            for txt in texts:
                prov = txt.get("prov", [])
                page_no = prov[0].get("page_no") if prov else None
                if page_no is not None:
                    page_texts[page_no].append(txt.get("text", "").strip())

            chunks = []
            for page in sorted(page_texts):
                joined = "\n".join(page_texts[page])
                chunks.append({"page": page, "text": joined})

            logger.info(
                "Created chunks from pages",
                worker_pid=os.getpid(),
                chunk_count=len(chunks),
                page_count=len(page_texts),
            )

        except Exception as e:
            logger.error(
                "Failed during content extraction", worker_pid=os.getpid(), error=str(e)
            )
            traceback.print_exc()
            raise

        final_memory = process.memory_info().rss / 1024 / 1024
        memory_delta = final_memory - start_memory
        logger.info(
            "Document processing completed successfully",
            worker_pid=os.getpid(),
            final_memory_mb=f"{final_memory:.1f}",
            memory_delta_mb=f"{memory_delta:.1f}",
        )

        return {
            "id": file_hash,
            "filename": origin.get("filename"),
            "mimetype": origin.get("mimetype"),
            "chunks": chunks,
            "file_path": file_path,
        }

    except Exception as e:
        final_memory = process.memory_info().rss / 1024 / 1024
        memory_delta = final_memory - start_memory
        logger.error(
            "FATAL ERROR in process_document_sync",
            worker_pid=os.getpid(),
            file_path=file_path,
            python_version=sys.version,
            memory_at_crash_mb=f"{final_memory:.1f}",
            memory_delta_mb=f"{memory_delta:.1f}",
            error_type=type(e).__name__,
            error=str(e),
        )
        logger.error("Full traceback:", worker_pid=os.getpid())
        traceback.print_exc()

        # Try to get more system info before crashing
        try:
            import platform

            logger.error(
                "System info",
                worker_pid=os.getpid(),
                system=f"{platform.system()} {platform.release()}",
                architecture=platform.machine(),
            )
        except:
            pass

        # Re-raise to trigger BrokenProcessPool in main process
        raise
