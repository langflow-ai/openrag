import io
import os
import base64
import hashlib
from typing import BinaryIO, Optional, Union


def _b64url(data: bytes) -> str:
    """URL-safe base64 without padding"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def stream_hash(
    source: Union[str, os.PathLike, BinaryIO],
    *,
    algo: str = "sha256",
    include_filename: Optional[str] = None,
    chunk_size: int = 1024 * 1024,  # 1 MiB
) -> bytes:
    """
    Memory-safe, incremental hash of a file path or binary stream.
    - source: path or file-like object with .read()
    - algo: hashlib algorithm name ('sha256', 'blake2b', 'sha3_256', etc.)
    - include_filename: if provided, the UTF-8 bytes of this string are prepended
    - chunk_size: read size per iteration
    Returns: raw digest bytes
    """
    try:
        h = hashlib.new(algo)
    except ValueError as e:
        raise ValueError(f"Unsupported hash algorithm: {algo}") from e

    def _update_from_file(f: BinaryIO):
        if include_filename:
            h.update(include_filename.encode("utf-8"))
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)

    if isinstance(source, (str, os.PathLike)):
        with open(source, "rb", buffering=io.DEFAULT_BUFFER_SIZE) as f:
            _update_from_file(f)
    else:
        f = source
        # Preserve position if seekable
        pos = None
        try:
            if f.seekable():
                pos = f.tell()
                f.seek(0)
        except Exception:
            pos = None
        try:
            _update_from_file(f)
        finally:
            if pos is not None:
                try:
                    f.seek(pos)
                except Exception:
                    pass

    return h.digest()


def hash_id(
    source: Union[str, os.PathLike, BinaryIO],
    *,
    algo: str = "sha256",
    include_filename: Optional[str] = None,
    length: int = 24,  # characters of base64url (set 0 or None for full)
) -> str:
    """
    Deterministic, URL-safe base64 digest (no prefix).
    """
    b = stream_hash(source, algo=algo, include_filename=include_filename)
    s = _b64url(b)
    return s[:length] if length else s