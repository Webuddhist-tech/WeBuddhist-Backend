from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from pecha_api.group_assets.enums import GroupAssetType
from pecha_api.group_assets.models import (
    GroupAsset,
    GroupRecitationCollectionItemAsset,
)
from pecha_api.group_recitation_collection.models import (
    GroupRecitationCollection,
    GroupRecitationCollectionItem,
)


def create_asset(db: Session, asset: GroupAsset) -> GroupAsset:
    """Create a new asset in a group's library.

    Flushes before committing so the row is fully populated without a
    post-commit refresh: once the commit returns, nothing else here can fail
    and wrongly make the caller think the row never landed.
    """
    db.add(asset)
    db.flush()
    db.refresh(asset)
    db.commit()
    return asset


def get_asset_by_id(
    db: Session,
    group_id: UUID,
    asset_id: UUID,
    for_update: bool = False,
) -> Optional[GroupAsset]:
    """Fetch a live asset scoped to its owning group.

    Group scoping lives in the query, so an asset from another group is simply
    not found rather than found-and-forbidden.

    ``for_update`` takes a row lock, which is what serialises deletion against
    a concurrent link write.
    """
    query = db.query(GroupAsset).filter(
        GroupAsset.id == asset_id,
        GroupAsset.group_id == group_id,
        GroupAsset.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def get_assets_by_ids(
    db: Session,
    group_id: UUID,
    asset_ids: Sequence[UUID],
    for_update: bool = False,
) -> List[GroupAsset]:
    """Fetch live assets of a group by id, in one query.

    ``for_update`` takes a row lock so a concurrent delete cannot soft-delete
    an asset between this check and the link insert that follows it.
    """
    if not asset_ids:
        return []
    query = db.query(GroupAsset).filter(
        GroupAsset.id.in_(list(asset_ids)),
        GroupAsset.group_id == group_id,
        GroupAsset.deleted_at.is_(None),
    )
    if for_update:
        query = query.with_for_update()
    return query.all()


def get_group_assets(
    db: Session,
    group_id: UUID,
    asset_type: Optional[GroupAssetType] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[GroupAsset], int]:
    """List a group's assets, newest first. Returns (assets, total)."""
    query = db.query(GroupAsset).filter(
        GroupAsset.group_id == group_id,
        GroupAsset.deleted_at.is_(None),
    )
    if asset_type is not None:
        query = query.filter(GroupAsset.asset_type == asset_type)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                GroupAsset.title.ilike(pattern),
                GroupAsset.file_name.ilike(pattern),
            )
        )

    total = query.count()
    assets = (
        query.order_by(GroupAsset.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return assets, total


def update_asset(db: Session, asset: GroupAsset) -> GroupAsset:
    """Persist changes to an existing asset."""
    db.commit()
    db.refresh(asset)
    return asset


def soft_delete_asset(db: Session, asset: GroupAsset, deleted_by: str) -> None:
    """Soft delete an asset. Links must already be gone.

    Does not commit: the caller owns the transaction so link cleanup and the
    soft delete land together or not at all.
    """
    asset.deleted_at = datetime.now(timezone.utc)
    asset.updated_by = deleted_by
    asset.updated_at = datetime.now(timezone.utc)
    db.flush()


def get_item_asset_links(
    db: Session,
    item_id: UUID,
) -> List[GroupRecitationCollectionItemAsset]:
    """Ordered links for a single item."""
    return (
        db.query(GroupRecitationCollectionItemAsset)
        .filter(GroupRecitationCollectionItemAsset.item_id == item_id)
        .order_by(GroupRecitationCollectionItemAsset.display_order)
        .all()
    )


def get_assets_for_items(
    db: Session,
    item_ids: Sequence[UUID],
) -> Dict[UUID, List[GroupAsset]]:
    """Batch-fetch ordered assets for many items at once.

    One query for every item on the page, keyed by item id, so building a
    collection's DTOs never degrades into a query per item.
    """
    if not item_ids:
        return {}

    rows = (
        db.query(GroupRecitationCollectionItemAsset, GroupAsset)
        .join(GroupAsset, GroupRecitationCollectionItemAsset.asset_id == GroupAsset.id)
        .filter(
            GroupRecitationCollectionItemAsset.item_id.in_(list(item_ids)),
            GroupAsset.deleted_at.is_(None),
        )
        .order_by(
            GroupRecitationCollectionItemAsset.item_id,
            GroupRecitationCollectionItemAsset.display_order,
        )
        .all()
    )

    assets_by_item: Dict[UUID, List[GroupAsset]] = {}
    for link, asset in rows:
        assets_by_item.setdefault(link.item_id, []).append(asset)
    return assets_by_item


def replace_item_assets(
    db: Session,
    item_id: UUID,
    links: List[GroupRecitationCollectionItemAsset],
) -> None:
    """Replace an item's full audio set.

    The delete is flushed before the inserts so the (item_id, display_order)
    unique constraint cannot collide mid-statement on a reorder.
    """
    db.query(GroupRecitationCollectionItemAsset).filter(
        GroupRecitationCollectionItemAsset.item_id == item_id
    ).delete(synchronize_session=False)
    db.flush()
    if links:
        db.add_all(links)
    db.commit()


def delete_links_for_item(db: Session, item_id: UUID) -> int:
    """Drop every link belonging to an item.

    Items are soft-deleted, so the FK's ON DELETE CASCADE never fires; without
    this the links would outlive the item and keep their assets looking in use.

    Does not commit: the caller commits the whole delete as one transaction.
    """
    deleted = (
        db.query(GroupRecitationCollectionItemAsset)
        .filter(GroupRecitationCollectionItemAsset.item_id == item_id)
        .delete(synchronize_session=False)
    )
    db.flush()
    return deleted


def delete_links_for_collection(db: Session, collection_id: UUID) -> int:
    """Drop every link belonging to a collection's items.

    Same reason as delete_links_for_item: collections are soft-deleted too.

    Does not commit: the caller commits the whole delete as one transaction.
    """
    item_ids = [
        row[0]
        for row in db.query(GroupRecitationCollectionItem.id)
        .filter(
            GroupRecitationCollectionItem.group_recitation_collection_id
            == collection_id
        )
        .all()
    ]
    if not item_ids:
        return 0

    deleted = (
        db.query(GroupRecitationCollectionItemAsset)
        .filter(GroupRecitationCollectionItemAsset.item_id.in_(item_ids))
        .delete(synchronize_session=False)
    )
    db.flush()
    return deleted


def delete_links_for_asset(db: Session, asset_id: UUID) -> int:
    """Drop every link pointing at an asset. Used by force delete.

    Does not commit: the caller commits the whole delete as one transaction.
    """
    deleted = (
        db.query(GroupRecitationCollectionItemAsset)
        .filter(GroupRecitationCollectionItemAsset.asset_id == asset_id)
        .delete(synchronize_session=False)
    )
    db.flush()
    return deleted


def count_links_for_asset(db: Session, asset_id: UUID) -> int:
    """How many items currently use this asset."""
    return (
        db.query(func.count(GroupRecitationCollectionItemAsset.id))
        .filter(GroupRecitationCollectionItemAsset.asset_id == asset_id)
        .scalar()
        or 0
    )


def get_asset_usages(db: Session, asset_id: UUID) -> List[Tuple[UUID, str, UUID, str]]:
    """Where an asset is currently linked from, for the 409 on delete.

    Returns (collection_id, collection_name, item_id, text_id) tuples. The
    text title is resolved by the caller, which owns the OpenPecha lookup.
    """
    rows = (
        db.query(
            GroupRecitationCollection.id,
            GroupRecitationCollection.name,
            GroupRecitationCollectionItem.id,
            GroupRecitationCollectionItem.text_id,
        )
        .select_from(GroupRecitationCollectionItemAsset)
        .join(
            GroupRecitationCollectionItem,
            GroupRecitationCollectionItemAsset.item_id
            == GroupRecitationCollectionItem.id,
        )
        .join(
            GroupRecitationCollection,
            GroupRecitationCollectionItem.group_recitation_collection_id
            == GroupRecitationCollection.id,
        )
        .filter(
            GroupRecitationCollectionItemAsset.asset_id == asset_id,
            # Backstop: a stale link must never report a usage the author has
            # already removed.
            GroupRecitationCollectionItem.deleted_at.is_(None),
            GroupRecitationCollection.deleted_at.is_(None),
        )
        .all()
    )
    return [(r[0], r[1], r[2], r[3]) for r in rows]
