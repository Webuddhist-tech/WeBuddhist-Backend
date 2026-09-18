import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.plans.groups.groups_repository import get_group_by_id
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.group_posts.service_utils import validate_group_content_access
from pecha_api.region_restrictions.region_restriction_enums import RestrictedItemType
from pecha_api.region_restrictions.region_restriction_service import filter_items_for_timezone
from pecha_api.texts.texts_openpecha_service import get_texts_by_edition_or_text_ids
from pecha_api.uploads.S3_utils import generate_presigned_access_url

from pecha_api.group_assets.repository import get_assets_for_items
from pecha_api.group_assets.service import build_asset_dto
from pecha_api.group_recitation_collection.models import GroupRecitationCollectionItem
from pecha_api.group_recitation_collection.repository import (
    get_collection_item_counts,
    get_collection_items,
    get_collection_without_group_filter,
    get_group_collections,
)
from pecha_api.group_recitation_collection.response_models import (
    GroupRecitationCollectionDTO,
    GroupRecitationCollectionDetailDTO,
    GroupRecitationCollectionItemDTO,
    GroupRecitationCollectionsResponse,
)

logger = logging.getLogger(__name__)


def _generate_presigned_url(s3_key: Optional[str]) -> Optional[str]:
    """Safely generate presigned URL for S3 key."""
    if not s3_key:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=s3_key,
        )
    except Exception as e:
        logger.error(f"Failed to generate presigned URL for {s3_key}: {e}")
        return None


def _validate_group_access(db: Session, group_id: UUID, user_id: Optional[UUID]) -> None:
    validate_group_content_access(db=db, group_id=group_id, user_id=user_id)


async def _build_items_dto(
    items: list[GroupRecitationCollectionItem],
    db: Optional[Session] = None,
) -> list[GroupRecitationCollectionItemDTO]:
    """Build item DTOs with text metadata fetched from OpenPecha."""
    if not items:
        return []

    text_ids_str = [str(item.text_id) for item in items]
    texts_dict = await get_texts_by_edition_or_text_ids(text_ids_str)

    # One batched fetch for every item on the page, never a query per item.
    assets_by_item = (
        get_assets_for_items(db=db, item_ids=[item.id for item in items])
        if db is not None
        else {}
    )

    items_dto = []
    for item in items:
        text_id_str = str(item.text_id)
        if text_id_str in texts_dict:
            text = texts_dict[text_id_str]
            items_dto.append(
                GroupRecitationCollectionItemDTO(
                    id=item.id,
                    text_id=item.text_id,
                    title=text.title,
                    language=text.language,
                    type=None,
                    display_order=item.display_order,
                    audio=[
                        build_asset_dto(asset)
                        for asset in assets_by_item.get(item.id, [])
                    ],
                )
            )
    return items_dto


async def list_group_collections_service(
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    timezone_name: Optional[str] = None,
    user_id: Optional[UUID] = None,
) -> GroupRecitationCollectionsResponse:
    """List a group's collections with region filtering."""
    with SessionLocal() as db:
        _validate_group_access(db, group_id, user_id)
        collections, total = get_group_collections(
            db=db,
            group_id=group_id,
            skip=skip,
            limit=limit,
        )

        if not collections:
            return GroupRecitationCollectionsResponse(
                collections=[],
                skip=skip,
                limit=limit,
                total=0,
            )

        collections = filter_items_for_timezone(
            collections,
            timezone_name=timezone_name,
            item_type=RestrictedItemType.GROUP_RECITATION_COLLECTION,
            id_of=lambda c: c.id,
        )

        collection_ids = [c.id for c in collections]
        item_counts = get_collection_item_counts(db=db, collection_ids=collection_ids)

        collections_dto = [
            GroupRecitationCollectionDTO(
                id=collection.id,
                group_id=collection.group_id,
                name=collection.name,
                img_url=_generate_presigned_url(collection.img_url),
                item_count=item_counts.get(collection.id, 0),
                created_at=collection.created_at.isoformat() if hasattr(collection.created_at, 'isoformat') else str(collection.created_at),
            )
            for collection in collections
        ]

        return GroupRecitationCollectionsResponse(
            collections=collections_dto,
            skip=skip,
            limit=limit,
            total=total,
        )


async def get_group_collection_detail_service(
    collection_id: UUID,
    timezone_name: Optional[str] = None,
    group_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
) -> GroupRecitationCollectionDetailDTO:
    """Get collection detail with items.

    When ``group_id`` is provided (legacy group-scoped route), the collection
    must belong to that group.
    """
    with SessionLocal() as db:
        collection = get_collection_without_group_filter(
            db=db,
            collection_id=collection_id,
        )

        if not collection or (group_id is not None and collection.group_id != group_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        _validate_group_access(db, collection.group_id, user_id)

        filtered_collections = filter_items_for_timezone(
            [collection],
            timezone_name=timezone_name,
            item_type=RestrictedItemType.GROUP_RECITATION_COLLECTION,
            id_of=lambda c: c.id,
        )

        if not filtered_collections:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        items = get_collection_items(db=db, collection_id=collection_id)
        items_dto = await _build_items_dto(items, db=db)

        return GroupRecitationCollectionDetailDTO(
            id=collection.id,
            group_id=collection.group_id,
            name=collection.name,
            img_url=_generate_presigned_url(collection.img_url),
            created_at=collection.created_at.isoformat() if hasattr(collection.created_at, 'isoformat') else str(collection.created_at),
            items=items_dto,
        )
