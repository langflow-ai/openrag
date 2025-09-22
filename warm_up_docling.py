import logging
import os
import sys

repo_root = os.path.dirname(__file__)
src_path = os.path.join(repo_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from utils.document_processing import create_document_converter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info("Warming up docling models")

try:
    # Use the sample document to warm up docling
    test_file = "/app/warmup_ocr.pdf"
    logger.info(f"Using test file to warm up docling: {test_file}")
    converter = create_document_converter()
    converter.convert(test_file)
    logger.info("Docling models warmed up successfully")
except Exception as e:
    logger.info(f"Docling warm-up completed with exception: {str(e)}")
    # This is expected - we just want to trigger the model downloads
