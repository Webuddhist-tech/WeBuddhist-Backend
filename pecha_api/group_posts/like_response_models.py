from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class LikePostResponse(BaseModel):
    """Response when liking a post."""
    post_id: UUID
    user_id: UUID
    liked: bool
    like_count: int
    created_at: str
    is_new: bool


class PostLikerDTO(BaseModel):
    """DTO for a single liker in the list."""
    user_id: UUID
    user_email: Optional[str] = None
    created_at: str


class PostLikersResponse(BaseModel):
    """Response for list post likers endpoint."""
    likes: List[PostLikerDTO]
    skip: int
    limit: int
    total: int
