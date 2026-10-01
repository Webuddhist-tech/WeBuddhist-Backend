from typing import List
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
    last_name: str | None = None
    avatar_url: str | None = None
    created_at: str


class VerseOfDayCommentLikersResponse(BaseModel):
    likes: List[VerseOfDayCommentLikerDTO]
    skip: int
    limit: int
    total: int
