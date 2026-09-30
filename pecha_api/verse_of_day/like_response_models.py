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
