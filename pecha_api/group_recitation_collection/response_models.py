from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID

from pecha_api.group_assets.response_models import GroupAssetDTO


class GroupRecitationCollectionItemDTO(BaseModel):
    """DTO for collection item with text details from MongoDB"""
    id: UUID
    # str, not UUID: text_id can hold a non-UUID pecha-style text id.
    text_id: str
    title: str
    language: Optional[str] = None
    type: Optional[str] = None
    display_order: int
    # Ordered by display_order, presigned. Additive with a default, so existing
    # clients are unaffected.
    audio: List[GroupAssetDTO] = []


class GroupRecitationCollectionDTO(BaseModel):
    """DTO for collection list (without items)"""
    id: UUID
    group_id: UUID
    name: str
    img_url: Optional[str] = None
    item_count: int
    created_at: str


class GroupRecitationCollectionDetailDTO(BaseModel):
    """DTO for single collection with items"""
    id: UUID
    group_id: UUID
    name: str
    img_url: Optional[str] = None
    created_at: str
    items: List[GroupRecitationCollectionItemDTO]


class GroupRecitationCollectionsResponse(BaseModel):
    """Response for list collections endpoint"""
    collections: List[GroupRecitationCollectionDTO]
    skip: int
    limit: int
    total: int


class CreateGroupRecitationCollectionRequest(BaseModel):
    """Request to create a new collection"""
    name: str
    img_url: Optional[str] = None


class UpdateGroupRecitationCollectionRequest(BaseModel):
    """Request to update a collection"""
    name: Optional[str] = None
    img_url: Optional[str] = None


class AddGroupRecitationCollectionItemsRequest(BaseModel):
    """Request to add items to a collection"""
    # str, not UUID: text_id can hold a non-UUID pecha-style text id.
    text_ids: List[str]


class AddGroupRecitationCollectionItemsResponse(BaseModel):
    """Response after adding items"""
    collection_id: UUID
    added_count: int
    items: List[GroupRecitationCollectionItemDTO]


class ReorderGroupRecitationCollectionItemsRequest(BaseModel):
    """Request to reorder items in a collection"""
    item_ids: List[UUID]
