from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class LikeCommentResponse(BaseModel):
    """Response when liking a comment."""
    comment_id: UUID
    user_id: UUID
    liked: bool
    like_count: int
    created_at: str
    is_new: bool


class CommentLikerDTO(BaseModel):
    """DTO for a single liker in the list."""
    user_id: UUID
    user_email: Optional[str] = None
    created_at: str


class CommentLikersResponse(BaseModel):
    """Response for list comment likers endpoint."""
    likes: List[CommentLikerDTO]
    skip: int
    limit: int
    total: int
