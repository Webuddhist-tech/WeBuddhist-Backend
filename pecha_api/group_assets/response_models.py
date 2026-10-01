from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class GroupAssetDTO(BaseModel):
    """A single asset in a group's library. s3_key is never returned raw."""
    id: UUID
    group_id: UUID
    asset_type: str
    title: str
    file_name: str
    asset_url: Optional[str] = None
    mime_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    duration_ms: Optional[int] = None
    created_at: str


class GroupAssetsResponse(BaseModel):
    """Response for the asset list / picker endpoint."""
    assets: List[GroupAssetDTO]
    skip: int
    limit: int
    total: int


class UpdateGroupAssetRequest(BaseModel):
    """Request to rename an asset."""
    title: Optional[str] = None


class GroupAssetUsageDTO(BaseModel):
    """One place an asset is currently linked from."""
    collection_id: UUID
    collection_name: str
    item_id: UUID
    text_title: Optional[str] = None


class SetItemAudioRequest(BaseModel):
    """Declarative replace: the array is the state. Links, unlinks and reorders
    an item's audio in one atomic call. [] clears it."""
    asset_ids: List[UUID]
