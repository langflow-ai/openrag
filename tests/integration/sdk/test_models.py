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

"""Tests for the models endpoint."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_SDK_INTEGRATION_TESTS") == "true",
    reason="SDK integration tests skipped",
)


class TestModels:
    """Test model listing per provider."""

    @pytest.mark.asyncio
    async def test_list_models(self, client):
        """Listing models for a provider must return language and embedding model lists."""
        models = await client.models.list("openai")

        assert models.language_models is not None
        assert isinstance(models.language_models, list)
        assert models.embedding_models is not None
        assert isinstance(models.embedding_models, list)
