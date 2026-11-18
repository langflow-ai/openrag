from typing import Literal

from pydantic import BaseModel, Field

from db.models.message_feedback import MAX_FEEDBACK_COMMENT_LENGTH


class FeedbackBody(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=MAX_FEEDBACK_COMMENT_LENGTH)
