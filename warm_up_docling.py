from docling.document_converter import DocumentConverter
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

logger.info("Warming up docling models")

try:
    # Use the sample document to warm up docling
    test_file = "/app/warmup_ocr.pdf"
    logger.info("Using test file to warm up docling", test_file=test_file)
    DocumentConverter().convert(test_file)
    logger.info("Docling models warmed up successfully")
except Exception as e:
    logger.info("Docling warm-up completed with exception", error=str(e))
    # This is expected - we just want to trigger the model downloads
