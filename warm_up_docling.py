from docling.document_converter import DocumentConverter
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Warming up docling models")

try:
    # Use the sample document to warm up docling
    test_file = "/app/warmup_ocr.pdf"
    logger.info(f"Using test file to warm up docling: {test_file}")
    DocumentConverter().convert(test_file)
    logger.info("Docling models warmed up successfully")
except Exception as e:
    logger.info(f"Docling warm-up completed with exception: {str(e)}")
    # This is expected - we just want to trigger the model downloads
