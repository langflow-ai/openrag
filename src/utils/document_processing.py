import hashlib
import os
from collections import defaultdict
from utils.logging_config import get_logger

logger = get_logger(__name__)


def process_text_file(file_path: str) -> dict:
    """
    Process a plain text file without using docling.
    Returns the same structure as extract_relevant() for consistency.

    Args:
        file_path: Path to the .txt file

    Returns:
        dict with keys: id, filename, mimetype, chunks
    """
    import os
    from utils.hash_utils import hash_id

    # Read the file
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    # Compute hash
    file_hash = hash_id(file_path)
    filename = os.path.basename(file_path)

    # Split content into chunks of ~1000 characters to match typical docling chunk sizes
    # This ensures embeddings stay within reasonable token limits
    chunk_size = 1000
    chunks = []

    # Split by paragraphs first (double newline)
    paragraphs = content.split('\n\n')
    current_chunk = ""
    chunk_index = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph would exceed chunk size, save current chunk
        if len(current_chunk) + len(para) + 2 > chunk_size and current_chunk:
            chunks.append({
                "page": chunk_index + 1,  # Use chunk_index + 1 as "page" number
                "type": "text",
                "text": current_chunk.strip()
            })
            chunk_index += 1
            current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    # Add the last chunk if any
    if current_chunk.strip():
        chunks.append({
            "page": chunk_index + 1,
            "type": "text",
            "text": current_chunk.strip()
        })

    # If no chunks were created (empty file), create a single empty chunk
    if not chunks:
        chunks.append({
            "page": 1,
            "type": "text",
            "text": ""
        })

    return {
        "id": file_hash,
        "filename": filename,
        "mimetype": "text/plain",
        "chunks": chunks,
    }


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
