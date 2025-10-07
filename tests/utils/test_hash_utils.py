"""
Tests for hash utility functions.
"""

import hashlib
import io
import pytest
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from utils.hash_utils import stream_hash, hash_id, _b64url


@pytest.mark.unit
class TestB64Url:
    """Test suite for base64 URL encoding."""

    def test_b64url_basic(self):
        """Test basic base64 URL encoding."""
        data = b"hello world"
        result = _b64url(data)

        assert isinstance(result, str)
        assert "=" not in result  # No padding
        assert "+" not in result  # URL-safe
        assert "/" not in result  # URL-safe

    def test_b64url_empty(self):
        """Test encoding empty bytes."""
        result = _b64url(b"")
        assert isinstance(result, str)

    def test_b64url_deterministic(self):
        """Test that encoding is deterministic."""
        data = b"test data"
        result1 = _b64url(data)
        result2 = _b64url(data)

        assert result1 == result2


@pytest.mark.unit
class TestStreamHash:
    """Test suite for stream_hash function."""

    def test_stream_hash_from_bytes_io(self):
        """Test hashing from BytesIO stream."""
        content = b"This is test content for hashing"
        stream = io.BytesIO(content)

        digest = stream_hash(stream)

        assert isinstance(digest, bytes)
        assert len(digest) == 32  # SHA256 produces 32 bytes

    def test_stream_hash_from_file_path(self, test_file: Path):
        """Test hashing from file path."""
        digest = stream_hash(test_file)

        assert isinstance(digest, bytes)
        assert len(digest) == 32

    def test_stream_hash_preserves_stream_position(self):
        """Test that stream position is preserved after hashing."""
        content = b"Test content for position preservation"
        stream = io.BytesIO(content)

        # Seek to middle
        stream.seek(10)
        initial_pos = stream.tell()

        # Hash the stream
        stream_hash(stream)

        # Position should be restored
        assert stream.tell() == initial_pos

    def test_stream_hash_with_filename(self):
        """Test that including filename changes the hash."""
        content = b"Same content"
        stream1 = io.BytesIO(content)
        stream2 = io.BytesIO(content)

        hash_without_filename = stream_hash(stream1)
        hash_with_filename = stream_hash(stream2, include_filename="test.txt")

        assert hash_without_filename != hash_with_filename

    def test_stream_hash_different_algorithms(self):
        """Test hashing with different algorithms."""
        content = b"Test content"
        stream = io.BytesIO(content)

        # Test SHA256
        stream.seek(0)
        digest_sha256 = stream_hash(stream, algo="sha256")
        assert len(digest_sha256) == 32

        # Test SHA512
        stream.seek(0)
        digest_sha512 = stream_hash(stream, algo="sha512")
        assert len(digest_sha512) == 64

        # Test MD5
        stream.seek(0)
        digest_md5 = stream_hash(stream, algo="md5")
        assert len(digest_md5) == 16

    def test_stream_hash_invalid_algorithm(self):
        """Test that invalid algorithm raises ValueError."""
        stream = io.BytesIO(b"test")

        with pytest.raises(ValueError, match="Unsupported hash algorithm"):
            stream_hash(stream, algo="invalid_algo")

    def test_stream_hash_large_content(self, temp_dir: Path):
        """Test hashing large files with chunking."""
        # Create a large file (5 MB)
        large_file = temp_dir / "large_file.bin"
        content = b"x" * (5 * 1024 * 1024)
        large_file.write_bytes(content)

        digest = stream_hash(large_file)

        assert isinstance(digest, bytes)
        assert len(digest) == 32

    def test_stream_hash_custom_chunk_size(self):
        """Test hashing with custom chunk size."""
        content = b"Test content with custom chunk size"
        stream = io.BytesIO(content)

        digest = stream_hash(stream, chunk_size=8)

        assert isinstance(digest, bytes)
        assert len(digest) == 32

    def test_stream_hash_deterministic(self):
        """Test that hashing is deterministic for same content."""
        content = b"Deterministic test content"

        stream1 = io.BytesIO(content)
        stream2 = io.BytesIO(content)

        digest1 = stream_hash(stream1)
        digest2 = stream_hash(stream2)

        assert digest1 == digest2

    def test_stream_hash_different_content(self):
        """Test that different content produces different hashes."""
        stream1 = io.BytesIO(b"content1")
        stream2 = io.BytesIO(b"content2")

        digest1 = stream_hash(stream1)
        digest2 = stream_hash(stream2)

        assert digest1 != digest2


@pytest.mark.unit
class TestHashId:
    """Test suite for hash_id function."""

    def test_hash_id_basic(self):
        """Test basic hash ID generation."""
        content = b"Test content for hash ID"
        stream = io.BytesIO(content)

        hash_str = hash_id(stream)

        assert isinstance(hash_str, str)
        assert len(hash_str) == 24  # Default length
        assert "=" not in hash_str  # No padding
        assert "+" not in hash_str  # URL-safe
        assert "/" not in hash_str  # URL-safe

    def test_hash_id_from_file(self, test_file: Path):
        """Test hash ID generation from file path."""
        hash_str = hash_id(test_file)

        assert isinstance(hash_str, str)
        assert len(hash_str) == 24

    def test_hash_id_custom_length(self):
        """Test hash ID with custom length."""
        stream = io.BytesIO(b"test")

        hash_8 = hash_id(stream, length=8)
        assert len(hash_8) == 8

        hash_16 = hash_id(stream, length=16)
        assert len(hash_16) == 16

        hash_32 = hash_id(stream, length=32)
        assert len(hash_32) == 32

    def test_hash_id_full_length(self):
        """Test hash ID with full length (no truncation)."""
        stream = io.BytesIO(b"test")

        hash_full = hash_id(stream, length=0)
        assert len(hash_full) > 24

        hash_none = hash_id(stream, length=None)
        assert len(hash_none) > 24

    def test_hash_id_with_filename(self):
        """Test that including filename produces different hash IDs."""
        content = b"Same content"
        stream1 = io.BytesIO(content)
        stream2 = io.BytesIO(content)

        hash_without = hash_id(stream1)
        hash_with = hash_id(stream2, include_filename="document.pdf")

        assert hash_without != hash_with

    def test_hash_id_different_algorithms(self):
        """Test hash ID with different algorithms."""
        content = b"test content"
        stream = io.BytesIO(content)

        hash_sha256 = hash_id(stream, algo="sha256")
        stream.seek(0)
        hash_sha512 = hash_id(stream, algo="sha512")

        assert hash_sha256 != hash_sha512
        assert isinstance(hash_sha256, str)
        assert isinstance(hash_sha512, str)

    def test_hash_id_deterministic(self):
        """Test that hash ID is deterministic."""
        content = b"Deterministic content"

        hash1 = hash_id(io.BytesIO(content))
        hash2 = hash_id(io.BytesIO(content))

        assert hash1 == hash2

    def test_hash_id_url_safe(self):
        """Test that hash ID is URL-safe."""
        content = b"URL safety test content"
        stream = io.BytesIO(content)

        hash_str = hash_id(stream)

        # Check that all characters are URL-safe
        url_safe_chars = set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )
        assert all(c in url_safe_chars for c in hash_str)

    def test_hash_id_collision_resistance(self):
        """Test that similar content produces different hash IDs."""
        hash1 = hash_id(io.BytesIO(b"content1"))
        hash2 = hash_id(io.BytesIO(b"content2"))
        hash3 = hash_id(io.BytesIO(b"content11"))

        # All should be different
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3

    def test_hash_id_with_file_and_filename(self, test_file: Path):
        """Test hash ID with both file path and filename parameter."""
        hash_without = hash_id(test_file)
        hash_with = hash_id(test_file, include_filename="override.txt")

        assert hash_without != hash_with

    def test_hash_id_empty_content(self):
        """Test hash ID with empty content."""
        stream = io.BytesIO(b"")
        hash_str = hash_id(stream)

        assert isinstance(hash_str, str)
        assert len(hash_str) == 24


@pytest.mark.integration
class TestHashUtilsIntegration:
    """Integration tests for hash utilities."""

    def test_consistent_hashing_file_vs_stream(self, test_file: Path):
        """Test that hashing file path vs stream produces same result."""
        # Hash from file path
        hash_from_path = hash_id(test_file)

        # Hash from stream
        with open(test_file, "rb") as f:
            hash_from_stream = hash_id(f)

        assert hash_from_path == hash_from_stream

    def test_document_id_generation(self, test_file: Path):
        """Test realistic document ID generation scenario."""
        # Simulate generating document IDs
        doc_id = hash_id(test_file, include_filename=test_file.name, length=32)

        assert isinstance(doc_id, str)
        assert len(doc_id) == 32
        assert doc_id  # Not empty

        # Same file should produce same ID
        doc_id_2 = hash_id(test_file, include_filename=test_file.name, length=32)
        assert doc_id == doc_id_2
