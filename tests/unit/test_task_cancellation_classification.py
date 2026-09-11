"""Test task cancellation error classification.

Ensures that cancelled files are properly classified with failure_phase: "cancelled",
actionable_by: "USER_ACTIONABLE", and no component field.
"""

from src.services.task_service import _is_task_cancellation_error


class TestCancellationErrorDetection:
    """Test that cancellation errors are correctly detected."""

    def test_file_cancelled_by_user(self):
        """Test that 'File cancelled by user' is recognized as cancellation."""
        assert _is_task_cancellation_error("File cancelled by user") is True

    def test_task_cancelled_by_user(self):
        """Test that 'Task cancelled by user' is recognized as cancellation."""
        assert _is_task_cancellation_error("Task cancelled by user") is True

    def test_file_processing_task_cancelled(self):
        """Test that 'file processing task cancelled' is recognized as cancellation."""
        assert (
            _is_task_cancellation_error("File processing task cancelled during docling parse")
            is True
        )

    def test_cancelled_during_parsing(self):
        """Test that cancellation during parsing is detected."""
        assert _is_task_cancellation_error("File cancelled by user during document parsing") is True

    def test_case_insensitive_matching(self):
        """Test that cancellation detection is case-insensitive."""
        assert _is_task_cancellation_error("FILE CANCELLED BY USER") is True
        assert _is_task_cancellation_error("Task Cancelled By User") is True

    def test_non_cancellation_errors(self):
        """Test that non-cancellation errors are not detected as cancellations."""
        assert _is_task_cancellation_error("Document parsing failed") is False
        assert _is_task_cancellation_error("Embedding generation failed") is False
        assert _is_task_cancellation_error("Failed to index document") is False
        assert _is_task_cancellation_error("Something went wrong") is False
        assert _is_task_cancellation_error("") is False

    def test_cancellation_with_context(self):
        """Test that cancellation is detected even with additional context."""
        assert _is_task_cancellation_error("Error: File cancelled by user at 10:30 AM") is True
        assert _is_task_cancellation_error("Processing interrupted: Task cancelled by user") is True
