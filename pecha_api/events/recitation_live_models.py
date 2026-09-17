from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SetPositionFrame(BaseModel):
    """An operator's `set` frame: where the puja is right now.

    `segment_id` is the wire key - stable across content edits, and resolvable
    by each client into its own language through the segment's mappings.
    `text_id` says which liturgy that segment belongs to, so a client whose
    text is no longer the one being recited knows to load the new one rather
    than silently failing to find the segment: an event's recitation collection
    holds several texts, and the operator works through them in order.
    `index` is advisory only, kept so the existing OBS overlays keep working.
    """

    # Matches group_recitation_collection_items.text_id: not UUID-only, since
    # it can hold an external (pecha-style) text id too.
    text_id: str = Field(..., max_length=255)
    segment_id: str = Field(..., max_length=128)
    index: Optional[int] = Field(None, ge=0)
    round_number: Optional[int] = Field(None, ge=1)

    @field_validator("text_id", "segment_id")
    @classmethod
    def validate_not_empty(cls, value: str, info) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value.strip()
