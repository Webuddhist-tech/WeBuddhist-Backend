import math

from pydantic import BaseModel, ConfigDict, field_validator
from typing import List, Optional
from uuid import UUID


class CreateCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    img_url: str


class CreateCollectionResponse(BaseModel):
    id: UUID
    name: str
    img_url: Optional[str] = None
    created_at: str
    updated_at: str


class UpdateCollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    img_url: Optional[str] = None


class AddItemsRequest(BaseModel):
    # str, not UUID: text_id can hold a non-UUID pecha-style text id.
    text_ids: List[str]


class AddItemsResponse(BaseModel):
    collection_id: UUID
    added_count: int
    items: List["RecitationCollectionItemDTO"]


class UpdateCollectionItemRequest(BaseModel):
    """Patch a collection item's display_order. Fractional values (1.4) are
    allowed so an item can sit between neighbors; the value must be unique
    among active items in the same collection."""
    model_config = ConfigDict(extra="forbid")

    display_order: float

    @field_validator("display_order")
    @classmethod
    def validate_display_order(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("display_order must be a finite number")
        return value


class RecitationCollectionItemDTO(BaseModel):
    """DTO for collection item with text details from MongoDB"""
    id: UUID
    # str, not UUID: text_id can hold a non-UUID pecha-style text id.
    text_id: str
    title: str
    language: Optional[str] = None
    type: Optional[str] = None
    display_order: float


class RecitationCollectionDTO(BaseModel):
    """DTO for collection list (without items)"""
    id: UUID
    name: str
    img_url: Optional[str] = None
    item_count: int
    created_at: str
    updated_at: str


class RecitationCollectionDetailDTO(BaseModel):
    """DTO for single collection with items"""
    id: UUID
    name: str
    img_url: Optional[str] = None
    created_at: str
    updated_at: str
    items: List[RecitationCollectionItemDTO]


class RecitationCollectionsResponse(BaseModel):
    """Response for list collections endpoint"""
    collections: List[RecitationCollectionDTO]
    skip: int
    limit: int
    total: int
