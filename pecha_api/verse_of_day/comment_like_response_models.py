from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class LikeVerseOfDayCommentResponse(BaseModel):
    comment_id: UUID
    user_id: UUID
    liked: bool
    like_count: int
    created_at: str
    is_new: bool


class VerseOfDayCommentLikerDTO(BaseModel):
    user_id: UUID
    first_name: str
    last_name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: str


class VerseOfDayCommentLikersResponse(BaseModel):
    likes: List[VerseOfDayCommentLikerDTO]
    skip: int
    limit: int
    total: int
