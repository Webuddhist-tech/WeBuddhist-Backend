from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class GroupPostCommentUserDTO(BaseModel):
    """Public user details included with a comment."""
    first_name: str
    last_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None


class GroupPostCommentDTO(BaseModel):
    """DTO for a single comment."""
    id: UUID
    post_id: UUID
    parent_comment_id: Optional[UUID] = None
    user_email: Optional[str] = None
    user: GroupPostCommentUserDTO
    text: str
    created_at: str
    updated_at: Optional[str] = None
    like_count: int = 0
    liked_by_me: bool = False


class GroupPostCommentsResponse(BaseModel):
    """Response for list comments endpoint."""
    comments: List[GroupPostCommentDTO]
    skip: int
    limit: int
    total: int


class CreateGroupPostCommentRequest(BaseModel):
    """Request to create a comment."""
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
