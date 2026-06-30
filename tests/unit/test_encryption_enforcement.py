# ******************************************************************************
# IBM Confidential
#
# OCO Source Materials
#
#  Copyright IBM Corp. 2026  All Rights Reserved.
#
# The source code for this program is not published or otherwise divested
# of its trade secrets, irrespective of what has been deposited with
# the U.S. Copyright Office.
# ******************************************************************************

import os
from unittest.mock import patch

import pytest

from utils.encryption import get_master_secret


@pytest.fixture(autouse=True)
def reset_encryption_cache():
    """Reset the encryption cache before and after each test."""
    import utils.encryption

    utils.encryption._cached_master_secret = None
    yield
    utils.encryption._cached_master_secret = None


def test_enforce_prerequisites_fail():
    """Test that get_master_secret raises RuntimeError when enforcement is enabled and key is missing."""
    with patch.dict(
        os.environ,
        {
            "OPENRAG_ENFORCE_PREREQUISITES": "true",
            "OPENRAG_ENCRYPTION_KEY": "",
            "IBM_AUTH_ENABLED": "false",
        },
    ):
        with pytest.raises(RuntimeError) as excinfo:
            get_master_secret()
        assert (
            "OPENRAG_ENFORCE_PREREQUISITES is enabled but no master encryption key could be retrieved"
            in str(excinfo.value)
        )


def test_enforce_prerequisites_success():
    """Test that get_master_secret succeeds when enforcement is enabled and key is present."""
    with patch.dict(
        os.environ,
        {
            "OPENRAG_ENFORCE_PREREQUISITES": "true",
            "OPENRAG_ENCRYPTION_KEY": "some-key",
            "IBM_AUTH_ENABLED": "false",
        },
    ):
        secret = get_master_secret()
        assert secret == "some-key"


def test_no_enforce_prerequisites_none():
    """Test that get_master_secret returns None when enforcement is disabled and key is missing."""
    with patch.dict(
        os.environ,
        {
            "OPENRAG_ENFORCE_PREREQUISITES": "false",
            "OPENRAG_ENCRYPTION_KEY": "",
            "IBM_AUTH_ENABLED": "false",
        },
    ):
        secret = get_master_secret()
        assert secret is None
