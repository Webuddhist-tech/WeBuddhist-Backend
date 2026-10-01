from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID


class AmbientSoundDTO(BaseModel):
    """One catalogue entry: a background sound and its optional cover.

    ``url`` and ``image_url`` are presigned and short-lived, so clients should
    re-list rather than persist them. ``image_url`` is None when no cover was
    uploaded, and either can be None if the object cannot be signed."""
    id: UUID
    name: str
    url: Optional[str] = None
    image_url: Optional[str] = None
    is_default: bool
    display_order: int


class AmbientSoundsResponse(BaseModel):
    sounds: List[AmbientSoundDTO]
