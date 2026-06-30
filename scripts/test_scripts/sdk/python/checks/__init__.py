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

"""Suite registry. Order matters: documents are ingested before search/chat
run so retrieval checks have content to find."""

from checks import (
    check_chat,
    check_documents,
    check_errors,
    check_filters,
    check_models,
    check_search,
    check_settings,
)

ALL_SUITES = [
    ("settings", check_settings.CHECKS),
    ("models", check_models.CHECKS),
    ("documents", check_documents.CHECKS),
    ("search", check_search.CHECKS),
    ("chat", check_chat.CHECKS),
    ("filters", check_filters.CHECKS),
    ("errors", check_errors.CHECKS),
]

SUITE_NAMES = [name for name, _ in ALL_SUITES]
