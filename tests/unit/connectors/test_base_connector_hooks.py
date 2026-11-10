"""Defaults of the optional BaseConnector hooks the host calls for every connector.

The host no longer special-cases connector types: the duplicate check always
calls ``filename_for_index`` and orphan reconciliation consults
``REQUIRES_CONFIRMED_DELETION`` / ``is_definitively_missing``. These defaults
must leave existing connectors' behaviour unchanged and fail safe.
"""

import pytest

from connectors.base import BaseConnector


def test_filename_for_index_defaults_to_the_picker_name():
    assert BaseConnector.filename_for_index(None, "file-1", "report.pdf") == "report.pdf"


def test_confirmed_deletion_is_off_by_default():
    assert BaseConnector.REQUIRES_CONFIRMED_DELETION is False


@pytest.mark.asyncio
async def test_is_definitively_missing_never_confirms_by_default():
    # A connector that sets the flag without overriding the hook deletes nothing.
    assert await BaseConnector.is_definitively_missing(None, "file-1") is False
