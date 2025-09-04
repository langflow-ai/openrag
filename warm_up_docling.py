from docling.document_converter import DocumentConverter
from utils.logging_config import get_logger

logger = get_logger(__name__)

logger.info("Warming up docling models...")

try:
    # Use the sample document to warm up docling
    test_file = "/app/warmup_ocr.pdf"
    logger.info(f"Using {test_file} to warm up docling...")
    DocumentConverter().convert(test_file)
    logger.info("Docling models warmed up successfully")
except Exception as e:
    logger.error(f"Docling warm-up completed with: {e}")
    # This is expected - we just want to trigger the model downloads
