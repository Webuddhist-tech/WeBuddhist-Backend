from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Tuple
from uuid import UUID
from fastapi import HTTPException
from starlette import status

from pecha_api.plans.users.recitation_collection.recitation_collection_models import (
    RecitationCollection,
    RecitationCollectionItem
)
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.response_message import BAD_REQUEST, DUPLICATE_DISPLAY_ORDER


def get_user_collections(
    db: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20
) -> Tuple[List[RecitationCollection], int]:

    query = db.query(RecitationCollection).filter(
        RecitationCollection.user_id == user_id
    ).order_by(RecitationCollection.created_at.desc())
    
    total = query.count()
    collections = query.offset(skip).limit(limit).all()
    
    return collections, total


def get_all_user_collections(
    db: Session,
    user_id: UUID,
) -> List[RecitationCollection]:
    """Return all individual recitation collections for a user, newest first."""
    return (
        db.query(RecitationCollection)
        .filter(RecitationCollection.user_id == user_id)
        .order_by(RecitationCollection.created_at.desc())
        .all()
    )


def get_collection_item_counts(
    db: Session,
    collection_ids: List[UUID]
) -> dict:

    if not collection_ids:
        return {}
    
    counts = db.query(
        RecitationCollectionItem.recitation_collection_id,
        func.count(RecitationCollectionItem.id).label('count')
    ).filter(
        RecitationCollectionItem.recitation_collection_id.in_(collection_ids),
        RecitationCollectionItem.deleted_at.is_(None)
    ).group_by(
        RecitationCollectionItem.recitation_collection_id
    ).all()
    
    return {row[0]: row[1] for row in counts}


def get_collection_by_id(
    db: Session,
    collection_id: UUID,
    user_id: UUID
) -> Optional[RecitationCollection]:

    return db.query(RecitationCollection).filter(
        RecitationCollection.id == collection_id,
        RecitationCollection.user_id == user_id
    ).first()


def get_collection_items(
    db: Session,
    collection_id: UUID
) -> List[RecitationCollectionItem]:

    return db.query(RecitationCollectionItem).filter(
        RecitationCollectionItem.recitation_collection_id == collection_id,
        RecitationCollectionItem.deleted_at.is_(None)
    ).order_by(RecitationCollectionItem.display_order).all()


def get_collection_item_by_id(
    db: Session,
    item_id: UUID,
    collection_id: UUID
) -> Optional[RecitationCollectionItem]:

    return db.query(RecitationCollectionItem).filter(
        RecitationCollectionItem.id == item_id,
        RecitationCollectionItem.recitation_collection_id == collection_id,
        RecitationCollectionItem.deleted_at.is_(None)
    ).first()


def save_collection(
    db: Session,
    collection: RecitationCollection
) -> RecitationCollection:

    try:
        db.add(collection)
        db.commit()
        db.refresh(collection)
        return collection
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump()
        )


def update_collection(
    db: Session,
    collection: RecitationCollection
) -> RecitationCollection:

    db.commit()
    db.refresh(collection)
    return collection


def get_max_display_order_for_collection(
    db: Session,
    collection_id: UUID
) -> Optional[float]:

    result = db.query(func.max(RecitationCollectionItem.display_order)).filter(
        RecitationCollectionItem.recitation_collection_id == collection_id,
        RecitationCollectionItem.deleted_at.is_(None)
    ).scalar()
    return result


def collection_item_display_order_taken(
    db: Session,
    collection_id: UUID,
    display_order: float,
    exclude_item_id: UUID,
) -> bool:
    """True when another active item in this collection already has this order."""
    return (
        db.query(RecitationCollectionItem.id)
        .filter(
            RecitationCollectionItem.recitation_collection_id == collection_id,
            RecitationCollectionItem.display_order == display_order,
            RecitationCollectionItem.id != exclude_item_id,
            RecitationCollectionItem.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def update_collection_item(
    db: Session,
    item: RecitationCollectionItem,
) -> RecitationCollectionItem:
    try:
        db.commit()
        db.refresh(item)
        return item
    except IntegrityError as e:
        db.rollback()
        message = str(e.orig)
        if "uq_recitation_collection_items_collection_display_order" in message:
            message = DUPLICATE_DISPLAY_ORDER
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=message).model_dump()
        )


def save_collection_items(
    db: Session,
    items: List[RecitationCollectionItem]
) -> List[RecitationCollectionItem]:

    try:
        db.add_all(items)
        db.commit()
        for item in items:
            db.refresh(item)
        return items
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump()
        )


def delete_collection(
    db: Session,
    collection_id: UUID,
    user_id: UUID
) -> Optional[RecitationCollection]:

    collection = get_collection_by_id(db=db, collection_id=collection_id, user_id=user_id)

    if not collection:
        return None

    try:
        db.delete(collection)
        db.commit()
        return collection
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump()
        )


def soft_delete_collection_item(
    db: Session,
    item: RecitationCollectionItem
) -> RecitationCollectionItem:
    """Soft delete a collection item by setting deleted_at.

    The row is kept (never physically deleted) so completion history
    referencing it via chant_id survives and the day-count total is not
    reduced by removing an item from a collection.
    """
    try:
        item.deleted_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(item)
        return item
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump()
        )
