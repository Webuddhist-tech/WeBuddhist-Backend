from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class LikeVerseOfDayResponse(BaseModel):
    verse_id: UUID
    user_id: UUID
    liked: bool
    like_count: int
    created_at: str
    is_new: bool


class VerseOfDayLikesResponse(BaseModel):
    verse_id: UUID
    like_count: int
    liked_by_me: bool


class VerseOfDayLikerDTO(BaseModel):
    user_id: UUID
    first_name: str
    last_name: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: str


class VerseOfDayLikersResponse(BaseModel):
    likes: List[VerseOfDayLikerDTO]
    skip: int
    limit: int
    total: int
