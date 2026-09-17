from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SetPositionFrame(BaseModel):
    """An operator's `set` frame: where the puja is right now.

    `segment_id` is the wire key - stable across content edits, and resolvable
    by each client into its own language through the segment's mappings.
    `index` is advisory only, kept so the existing OBS overlays keep working.
    """

    segment_id: str = Field(..., max_length=128)
    index: Optional[int] = Field(None, ge=0)
    round_number: Optional[int] = Field(None, ge=1)

    @field_validator("segment_id")
    @classmethod
    def validate_segment_id(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("segment_id must not be empty")
        return value.strip()
