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

"""Amazon S3 / S3-compatible connector for OpenRAG."""

from .connector import S3Connector
from .models import S3ConfigureBody
from .api import (
    s3_defaults,
    s3_configure,
    s3_list_buckets,
    s3_bucket_status,
)

__all__ = [
    "S3Connector",
    "S3ConfigureBody",
    "s3_defaults",
    "s3_configure",
    "s3_list_buckets",
    "s3_bucket_status",
]
