import os
import re
import unicodedata
from collections import defaultdict

from utils.logging_config import get_logger

logger = get_logger(__name__)

IMAGE_PLACEHOLDER = "<!-- image -->"

# Some PDF fonts map common kanji (日, 月, 木, 金, 土, ...) to the look-alike
# Kangxi Radical code points in their /ToUnicode CMap, and Docling copies them
# through unchanged. Map just those blocks back to CJK Unified Ideographs;
# full NFKC would also rewrite full-width digits, ㈱, ①, half-width katakana.
_CJK_RADICAL_TABLE = {
    cp: unicodedata.normalize("NFKC", chr(cp))
    for cp in range(0x2E80, 0x2FE0)  # CJK Radicals Supplement + Kangxi Radicals
    if unicodedata.normalize("NFKC", chr(cp)) != chr(cp)
}


def normalize_cjk_radicals(text: str) -> str:
    """Replace Kangxi/CJK radical code points with their unified ideographs."""
    return text.translate(_CJK_RADICAL_TABLE)


_SENTENCE_END = re.compile(r"(?<=[。．！？.!?])")


def split_to_size(
    text: str, limit: int, levels: tuple[str, ...] = ("line", "sentence")
) -> list[str]:
    """Split text into pieces of at most ``limit`` characters.

    Cuts on line breaks first, then after sentence-ending punctuation, and only
    then at a fixed character count, so pieces end at natural boundaries when
    the text has any.
    """
    if len(text) <= limit:
        return [text]
    if not levels:
        return [text[i : i + limit] for i in range(0, len(text), limit)]
    if levels[0] == "line":
        parts, joiner = text.split("\n"), "\n"
    else:
        parts, joiner = _SENTENCE_END.split(text), ""

    pieces: list[str] = []
    current = ""
    for part in parts:
        for sub in split_to_size(part, limit, levels[1:]):
            candidate = f"{current}{joiner}{sub}" if current else sub
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    pieces.append(current)
                current = sub
    if current:
        pieces.append(current)
    return pieces


def process_text_file(file_path: str) -> dict:
    """
    Process a plain text file without using docling.
    Returns the same structure as extract_relevant() for consistency.

    Args:
        file_path: Path to the .txt file

    Returns:
        dict with keys: id, filename, mimetype, chunks
    """
    from utils.hash_utils import hash_id

    # Read the file
    with open(file_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Compute hash
    file_hash = hash_id(file_path)
    filename = os.path.basename(file_path)

    # Split content into chunks of ~1000 characters to match typical docling chunk sizes
    # This ensures embeddings stay within reasonable token limits
    chunk_size = 1000
    chunks = []

    # Split by paragraphs first (double newline)
    paragraphs = content.split("\n\n")
    current_chunk = ""
    chunk_index = 0

    # A file with no blank lines is one paragraph, so oversized paragraphs are
    # cut on lines and sentences before packing.
    pieces = (
        piece.strip() for para in paragraphs for piece in split_to_size(para.strip(), chunk_size)
    )
    for para in pieces:
        if not para:
            continue

        # If adding this paragraph would exceed chunk size, save current chunk
        if len(current_chunk) + len(para) + 2 > chunk_size and current_chunk:
            chunks.append(
                {
                    "page": chunk_index + 1,  # Use chunk_index + 1 as "page" number
                    "type": "text",
                    "text": current_chunk.strip(),
                }
            )
            chunk_index += 1
            current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    # Add the last chunk if any
    if current_chunk.strip():
        chunks.append({"page": chunk_index + 1, "type": "text", "text": current_chunk.strip()})

    # If no chunks were created (empty file), create a single empty chunk
    if not chunks:
        chunks.append({"page": 1, "type": "text", "text": ""})

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
      - Emits a picture chunk for each picture with description annotations
      - Emits one image placeholder only when pictures exist and no other chunks were produced
    Returns a slimmed dict ready for indexing, with each chunk under "text".
    """
    origin = doc_dict.get("origin", {})
    chunks = []

    # 1) process free-text fragments
    page_texts = defaultdict(list)
    for txt in doc_dict.get("texts", []):
        prov = txt.get("prov", [])
        page_no = prov[0].get("page_no") if prov else None
        if page_no is None:
            page_no = 1
        page_texts[page_no].append(txt.get("text", "").strip())

    for page in sorted(page_texts):
        chunks.append({"page": page, "type": "text", "text": "\n".join(page_texts[page])})

    # 2) process tables
    for t_idx, table in enumerate(doc_dict.get("tables", [])):
        prov = table.get("prov", [])
        page_no = prov[0].get("page_no") if prov else None
        if page_no is None:
            page_no = 1

        # group cells by their row index
        rows = defaultdict(list)
        table_data = table.get("data")
        if table_data:
            for cell in table_data.get("table_cells", []):
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

    # 3) process picture descriptions (VLM-generated annotations)
    # Docling stores these under pictures[].annotations with kind == "description".
    # Without this, image-only documents (no text layer) yield zero chunks on the
    # non-Langflow path, which surfaces as a misleading "corrupted or invalid" error.
    # The Langflow path already captures them via Docling's export_to_markdown.
    pictures = doc_dict.get("pictures", [])
    for p_idx, picture in enumerate(pictures):
        prov = picture.get("prov", [])
        page_no = prov[0].get("page_no") if prov else None
        if page_no is None:
            page_no = 1

        descriptions = [
            ann.get("text", "").strip()
            for ann in picture.get("annotations", [])
            if ann.get("kind") == "description" and ann.get("text", "").strip()
        ]
        if descriptions:
            chunks.append(
                {
                    "page": page_no,
                    "type": "picture",
                    "picture_index": p_idx,
                    "text": "\n".join(descriptions),
                }
            )

    # Preserve a non-empty signal for image-only documents without descriptions,
    # but avoid embedding one identical placeholder for every uncaptioned picture.
    if not chunks and pictures:
        first_picture = pictures[0]
        prov = first_picture.get("prov", [])
        page_no = prov[0].get("page_no") if prov else None
        chunks.append(
            {
                "page": page_no if page_no is not None else 1,
                "type": "picture",
                "picture_index": 0,
                "text": IMAGE_PLACEHOLDER,
            }
        )

    for chunk in chunks:
        chunk["text"] = normalize_cjk_radicals(chunk["text"])

    return {
        "id": origin.get("binary_hash"),
        "filename": origin.get("filename"),
        "mimetype": origin.get("mimetype"),
        "chunks": chunks,
    }


def resplit_chunks_character_windows(
    chunks: list,
    chunk_size: int,
    chunk_overlap: int,
) -> list:
    """Split long chunk texts into fixed-size character windows with overlap.

    Used by the non-Langflow ingestion path when the UI supplies ``chunkSize`` /
    ``chunkOverlap``. Invalid combinations (non-positive size or overlap >= size)
    return ``chunks`` unchanged.
    """
    if chunk_size <= 0 or chunk_overlap >= chunk_size:
        return chunks
    stride = chunk_size - chunk_overlap
    if stride <= 0:
        return chunks

    out: list = []
    for ch in chunks:
        text = ch.get("text") if isinstance(ch, dict) else None
        if not isinstance(text, str):
            out.append(dict(ch) if isinstance(ch, dict) else ch)
            continue
        # This marker is a semantic signal that Docling detected an image even
        # though it extracted no text. Keep it intact so image-only documents
        # remain ingestible and display the same placeholder as the Langflow path.
        if text.strip() == IMAGE_PLACEHOLDER:
            out.append(dict(ch))
            continue
        if len(text) <= chunk_size:
            out.append(dict(ch))
            continue
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            piece = text[start:end]
            new_ch = dict(ch)
            new_ch["text"] = piece
            out.append(new_ch)
            if end >= len(text):
                break
            start += stride
    return out


def _is_surrogate_pair(text: str, pos: int) -> bool:
    return (
        "\ud800" <= text[pos] <= "\udbff"
        and pos + 1 < len(text)
        and "\udc00" <= text[pos + 1] <= "\udfff"
    )


def _char_end(text: str, pos: int) -> int:
    """End of the character tiktoken reads at ``pos``."""
    return pos + 2 if _is_surrogate_pair(text, pos) else pos + 1


def _decoded_to_text_index(text: str) -> list[int]:
    """Map each index of tiktoken's view of ``text`` to its index in ``text``.

    tiktoken joins a surrogate pair stored as two halves into one character
    and replaces a lone surrogate with U+FFFD, so ``decode_with_offsets``
    indexes a string that can be shorter than ``text``.
    """
    index: list[int] = []
    pos = 0
    while pos < len(text):
        index.append(pos)
        pos = _char_end(text, pos)
    return index


def _split_text_to_max_tokens(text: str, encoding, max_tokens: int) -> list[str]:
    """Cut ``text`` into pieces that each encode to at most ``max_tokens``.

    Encodes the chunk once and cuts on token start positions from
    ``decode_with_offsets``. Each slice is re-encoded: a slice that comes back
    over the cap (a 500-token Watsonx window can re-encode to 501) moves back
    one token, and a slice that fits is extended until the next one would not.
    A single code point that is already over the cap is kept
    so the cursor still advances. The pieces join back to ``text``.
    """
    if max_tokens < 1:
        raise ValueError(f"max_tokens must be at least 1, got {max_tokens}")

    # Extracted documents can contain "<|endoftext|>" literally; count it as text.
    tokens = encoding.encode(text, disallowed_special=())
    if len(tokens) <= max_tokens:
        return [text]

    decoded, offsets = encoding.decode_with_offsets(tokens)
    if decoded != text:
        text_index = _decoded_to_text_index(text)
        offsets = [text_index[offset] for offset in offsets]

    pieces: list[str] = []
    char_pos = 0
    token_index = 0
    token_count = len(tokens)
    text_length = len(text)
    while char_pos < text_length:
        # The character cursor can sit inside a token after a one-character
        # fallback. The next piece must start there, not at the next token.
        while token_index + 1 < token_count and offsets[token_index + 1] <= char_pos:
            token_index += 1
        cut = min(token_count, token_index + max_tokens)
        while cut < token_count and offsets[cut] <= char_pos:
            cut += 1
        first_char_end = _char_end(text, char_pos)
        fit_end = 0
        while True:
            char_end = text_length if cut >= token_count else offsets[cut]
            if char_end <= char_pos:
                fit_end = fit_end or first_char_end
                break
            slice_tokens = len(encoding.encode(text[char_pos:char_end], disallowed_special=()))
            if slice_tokens <= max_tokens:
                fit_end = char_end
                if cut >= token_count:
                    break
                # A slice can re-encode to fewer tokens than it spans (two
                # spaces split across tokens become one), so try a longer one.
                cut = min(token_count, cut + max(1, max_tokens - slice_tokens))
                while cut < token_count and offsets[cut] <= char_end:
                    cut += 1
                continue
            if fit_end:
                break
            if char_end <= first_char_end or cut <= token_index + 1:
                fit_end = first_char_end
                break
            cut -= 1
        pieces.append(text[char_pos:fit_end])
        char_pos = fit_end
    return pieces


def split_chunks_by_max_tokens(
    chunks: list[dict], max_tokens: int, model: str | None = None
) -> list[dict]:
    """Split any chunks whose token count exceeds max_tokens.

    Each resulting chunk encodes to at most ``max_tokens`` (unless a single
    code point is already over the cap), so the embedding batcher can keep one
    vector per chunk.
    """
    import tiktoken

    from config.settings import get_embedding_model

    model = model or get_embedding_model()
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")

    new_chunks = []
    for chunk in chunks:
        text = chunk.get("text", "")
        if not text:
            new_chunks.append(chunk)
            continue

        for piece in _split_text_to_max_tokens(text, encoding, max_tokens):
            new_chunk = dict(chunk)
            new_chunk["text"] = piece
            new_chunks.append(new_chunk)

    return new_chunks
