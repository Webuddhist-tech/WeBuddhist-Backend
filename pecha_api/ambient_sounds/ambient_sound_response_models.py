from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID


class AmbientSoundDTO(BaseModel):
    id: UUID
    name: str
    url: Optional[str] = None
    is_default: bool
    display_order: int


class AmbientSoundsResponse(BaseModel):
    sounds: List[AmbientSoundDTO]
