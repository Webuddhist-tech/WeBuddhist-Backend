from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from pecha_api.events.event_response_models import EventDTO
from pecha_api.group_posts.response_models import GroupPostDTO


class AuthorGroupFeedItemType(str, Enum):
    POST = "post"
    EVENT = "event"


class AuthorGroupFeedItemDTO(BaseModel):
    type: AuthorGroupFeedItemType
    feed_at: str
    is_joined: bool
    can_view_linked_content: bool = False
    group_id: UUID
    group_name: Optional[str] = None
    group_slug: Optional[str] = None
    group_avatar_url: Optional[str] = None
    post: Optional[GroupPostDTO] = None
    event: Optional[EventDTO] = None


class AuthorGroupFeedResponse(BaseModel):
    items: List[AuthorGroupFeedItemDTO]
    skip: int
    limit: int
    total: int
    should_include_unfollowed: bool = Field(serialization_alias="include_unfollowed")
