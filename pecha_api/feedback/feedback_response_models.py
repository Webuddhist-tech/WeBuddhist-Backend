from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class FeedbackDTO(BaseModel):
    id: UUID
    user_id: UUID
    content: str
    image_urls: List[str]
    platform: Optional[str] = None
    app_version: Optional[str] = None
    created_at: datetime
    updated_at: datetime
