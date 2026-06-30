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

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error: str
    message: str | None = None
    task_id: str | None = None


class TaskRetrySkippedFile(BaseModel):
    file_path: str
    filename: str | None = None
    reason: str | None = None


class TaskRetryResponse(BaseModel):
    task_id: str
    retried: int = 0
    skipped: list[TaskRetrySkippedFile] = Field(default_factory=list)
    status: str
    message: str | None = None
    error: str | None = None
