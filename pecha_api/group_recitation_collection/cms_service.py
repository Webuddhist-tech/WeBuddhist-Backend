import logging
from datetime import datetime, timezone as tz
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_repository import get_group_by_id
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.plans.shared.permissions import require_can_create_content, require_can_read_group_content
from pecha_api.texts.texts_openpecha_service import get_texts_by_edition_or_text_ids
from pecha_api.uploads.S3_utils import generate_presigned_access_url

from pecha_api.group_assets.repository import (
    delete_links_for_collection,
    delete_links_for_item,
    get_assets_for_items,
)
from pecha_api.group_assets.service import build_asset_dto
from pecha_api.group_recitation_collection.models import (
    GroupRecitationCollection,
    GroupRecitationCollectionItem,
)
from pecha_api.group_recitation_collection.repository import (
    create_collection,
    create_collection_items,
    get_collection_by_id,
    get_collection_item_by_id,
    get_collection_item_counts,
    get_collection_items,
    get_collection_without_group_filter,
    get_group_collections,
    get_max_display_order,
    soft_delete_collection,
    soft_delete_collection_item,
    update_collection,
    update_item_display_orders,
)
from pecha_api.group_recitation_collection.response_models import (
    AddGroupRecitationCollectionItemsResponse,
    CreateGroupRecitationCollectionRequest,
    GroupRecitationCollectionDTO,
    GroupRecitationCollectionDetailDTO,
    GroupRecitationCollectionItemDTO,
    GroupRecitationCollectionsResponse,
    UpdateGroupRecitationCollectionRequest,
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


def _validate_group_exists(db: Session, group_id: UUID) -> None:
    """Validate that group exists."""
    group = get_group_by_id(db=db, group_id=group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NOT_FOUND,
        )


async def _build_items_dto(
    items: List[GroupRecitationCollectionItem],
    db: Optional[Session] = None,
) -> List[GroupRecitationCollectionItemDTO]:
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


def cms_list_group_collections_service(
    token: str,
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> GroupRecitationCollectionsResponse:
    """List all collections for a group (CMS - requires auth)."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_read_group_content(db=db, group_id=group_id, author=author)

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


async def cms_get_group_collection_detail_service(
    token: str,
    group_id: UUID,
    collection_id: UUID,
) -> GroupRecitationCollectionDetailDTO:
    """Get collection detail with items (CMS - requires auth)."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_read_group_content(db=db, group_id=group_id, author=author)

        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            group_id=group_id,
        )

        if not collection:
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


def cms_create_collection_service(
    token: str,
    group_id: UUID,
    request: CreateGroupRecitationCollectionRequest,
) -> GroupRecitationCollectionDetailDTO:
    """Create a new collection for a group."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        now = datetime.now(tz.utc)
        collection = GroupRecitationCollection(
            group_id=group_id,
            name=request.name,
            img_url=request.img_url,
            created_at=now,
            updated_at=now,
            created_by=author.id,
            updated_by=author.id,
        )

        created = create_collection(db=db, collection=collection)

        return GroupRecitationCollectionDetailDTO(
            id=created.id,
            group_id=created.group_id,
            name=created.name,
            img_url=_generate_presigned_url(created.img_url),
            created_at=created.created_at.isoformat() if hasattr(created.created_at, 'isoformat') else str(created.created_at),
            items=[],
        )


def cms_update_collection_service(
    token: str,
    group_id: UUID,
    collection_id: UUID,
    request: UpdateGroupRecitationCollectionRequest,
) -> GroupRecitationCollectionDetailDTO:
    """Update an existing collection."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            group_id=group_id,
        )

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        if request.name is not None:
            collection.name = request.name
        if request.img_url is not None:
            collection.img_url = request.img_url

        collection.updated_at = datetime.now(tz.utc)
        collection.updated_by = author.id

        update_collection(db=db, collection=collection)

        items = get_collection_items(db=db, collection_id=collection_id)

        return GroupRecitationCollectionDetailDTO(
            id=collection.id,
            group_id=collection.group_id,
            name=collection.name,
            img_url=_generate_presigned_url(collection.img_url),
            created_at=collection.created_at.isoformat() if hasattr(collection.created_at, 'isoformat') else str(collection.created_at),
            items=[],
        )


def cms_delete_collection_service(
    token: str,
    group_id: UUID,
    collection_id: UUID,
) -> None:
    """Soft delete a collection."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            group_id=group_id,
        )

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        # Collections are soft-deleted, so the link FK's CASCADE never fires.
        # Drop the links explicitly or they outlive the collection and keep
        # their assets looking in use.
        delete_links_for_collection(db=db, collection_id=collection_id)
        soft_delete_collection(db=db, collection=collection)


async def cms_add_items_service(
    token: str,
    group_id: UUID,
    collection_id: UUID,
    text_ids: List[str],
) -> AddGroupRecitationCollectionItemsResponse:
    """Add items to a collection."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            group_id=group_id,
        )

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        max_order = get_max_display_order(db=db, collection_id=collection_id)

        new_items = [
            GroupRecitationCollectionItem(
                group_recitation_collection_id=collection_id,
                text_id=str(text_id),
                display_order=max_order + idx + 1,
            )
            for idx, text_id in enumerate(text_ids)
        ]

        saved_items = create_collection_items(db=db, items=new_items)
        items_dto = await _build_items_dto(saved_items, db=db)

        return AddGroupRecitationCollectionItemsResponse(
            collection_id=collection_id,
            added_count=len(saved_items),
            items=items_dto,
        )


def cms_delete_item_service(
    token: str,
    group_id: UUID,
    collection_id: UUID,
    item_id: UUID,
) -> None:
    """Soft delete an item from a collection."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            group_id=group_id,
        )

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        item = get_collection_item_by_id(
            db=db,
            item_id=item_id,
            collection_id=collection_id,
        )

        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        # Same as collection delete: soft delete means no CASCADE, so the
        # item's audio links have to go explicitly. The assets stay in the
        # library, which is the point of having one.
        delete_links_for_item(db=db, item_id=item_id)
        soft_delete_collection_item(db=db, item=item)


async def cms_reorder_items_service(
    token: str,
    group_id: UUID,
    collection_id: UUID,
    item_ids: List[UUID],
) -> GroupRecitationCollectionDetailDTO:
    """Reorder items in a collection."""
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        _validate_group_exists(db, group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            group_id=group_id,
        )

        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        items = get_collection_items(db=db, collection_id=collection_id)
        item_map = {item.id: item for item in items}

        for idx, item_id in enumerate(item_ids):
            if item_id in item_map:
                item_map[item_id].display_order = idx + 1

        update_item_display_orders(db=db, items=list(item_map.values()))

        updated_items = get_collection_items(db=db, collection_id=collection_id)
        items_dto = await _build_items_dto(updated_items, db=db)

        return GroupRecitationCollectionDetailDTO(
            id=collection.id,
            group_id=collection.group_id,
            name=collection.name,
            img_url=_generate_presigned_url(collection.img_url),
            created_at=collection.created_at.isoformat() if hasattr(collection.created_at, 'isoformat') else str(collection.created_at),
            items=items_dto,
        )
