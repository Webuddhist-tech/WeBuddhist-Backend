from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class VerseOfDayCommentUserDTO(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    avatar_url: Optional[str] = None


class VerseOfDayCommentDTO(BaseModel):
    id: UUID
    verse_id: UUID
    user_id: UUID
    parent_comment_id: Optional[UUID] = None
    user: VerseOfDayCommentUserDTO
    text: str
    created_at: str
    updated_at: Optional[str] = None
    like_count: int = 0
    liked_by_me: bool = False


class VerseOfDayCommentsResponse(BaseModel):
    comments: List[VerseOfDayCommentDTO]
    skip: int
    limit: int
    total: int


class CreateVerseOfDayCommentRequest(BaseModel):
    text: str
    parent_comment_id: Optional[UUID] = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Comment text must not be empty")
        if len(value) > 5000:
            raise ValueError("Comment text must not exceed 5000 characters")
        return value
