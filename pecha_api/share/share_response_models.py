from typing import Optional
from pydantic import BaseModel
from .share_enums import (
    TextColor,
    BgColor
)

class ShareRequest(BaseModel):
    logo: bool = False
    segment_id: Optional[str] = None
    content_id: Optional[str] = None
    text_id: Optional[str] = None
    poem_id: Optional[str] = None
    event_id: Optional[str] = None
    post_id: Optional[str] = None
    content_index: Optional[int] = None
    language: Optional[str] = None
    url: Optional[str] = None
    text_color: Optional[TextColor] = TextColor.DEFAULT
    bg_color: Optional[BgColor] = BgColor.DEFAULT
    tags: Optional[str] = None

class ShortUrlResponse(BaseModel):
    shortUrl: str