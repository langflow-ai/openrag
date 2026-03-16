"""
Unit tests for OpenSearch disk space error detection.

When OpenSearch disk usage exceeds the high-watermark or flood-stage
watermark, it blocks operations and returns errors with specific
signatures. These tests verify that those signatures are correctly detected
and surfaced as OpenSearchDiskSpaceError.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from utils.opensearch_utils import (
    OpenSearchDiskSpaceError,
    is_disk_space_error,
    DISK_SPACE_ERROR_MESSAGE,
)


# ---------------------------------------------------------------------------
# is_disk_space_error
# ---------------------------------------------------------------------------

class TestIsDiskSpaceError:
    def test_disk_watermark_message(self):
        assert is_disk_space_error(Exception("high disk watermark exceeded on node"))

    def test_flood_stage_underscore(self):
        assert is_disk_space_error(Exception("flood_stage disk watermark exceeded"))

    def test_flood_stage_space(self):
        assert is_disk_space_error(Exception("flood stage disk watermark exceeded"))

    def test_disk_usage_exceeded(self):
        assert is_disk_space_error(Exception("disk usage exceeded flood-stage watermark"))

    def test_index_read_only(self):
        assert is_disk_space_error(Exception("index read-only / allow delete (api)"))

    def test_no_space_left_on_device(self):
        assert is_disk_space_error(Exception("no space left on device"))

    def test_cluster_block_exception(self):
        assert is_disk_space_error(Exception("cluster_block_exception: blocked by index"))

    def test_forbidden_12(self):
        assert is_disk_space_error(Exception("[FORBIDDEN/12/index read-only]"))

    def test_too_many_requests_12(self):
        assert is_disk_space_error(Exception("[TOO_MANY_REQUESTS/12/disk usage exceeded]"))

    def test_case_insensitive(self):
        assert is_disk_space_error(Exception("DISK WATERMARK EXCEEDED"))

    def test_unrelated_error_returns_false(self):
        assert not is_disk_space_error(Exception("Connection refused"))

    def test_auth_error_returns_false(self):
        assert not is_disk_space_error(Exception("AuthenticationException: access denied"))

    def test_timeout_error_returns_false(self):
        assert not is_disk_space_error(Exception("ConnectionTimeout caused by timeout"))

    def test_empty_error_returns_false(self):
        assert not is_disk_space_error(Exception(""))


# ---------------------------------------------------------------------------
# DISK_SPACE_ERROR_MESSAGE content
# ---------------------------------------------------------------------------

class TestDiskSpaceErrorMessage:
    def test_message_mentions_disk_space_blocked(self):
        assert "run out of available disk space" in DISK_SPACE_ERROR_MESSAGE.lower()

    def test_message_mentions_disk_space(self):
        assert "disk" in DISK_SPACE_ERROR_MESSAGE.lower()

    def test_message_mentions_resolution(self):
        assert "free up" in DISK_SPACE_ERROR_MESSAGE.lower()


# ---------------------------------------------------------------------------
# OpenSearchDiskSpaceError is an Exception subclass
# ---------------------------------------------------------------------------

class TestOpenSearchDiskSpaceError:
    def test_is_exception(self):
        err = OpenSearchDiskSpaceError("test")
        assert isinstance(err, Exception)

    def test_carries_message(self):
        err = OpenSearchDiskSpaceError("disk full")
        assert str(err) == "disk full"

    def test_can_chain_cause(self):
        cause = ValueError("original")
        err = OpenSearchDiskSpaceError("disk full")
        try:
            raise err from cause
        except OpenSearchDiskSpaceError as caught:
            assert caught.__cause__ is cause
