import logging
from typing import List
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.group_assets.enums import GroupAssetType
from pecha_api.group_assets.models import GroupRecitationCollectionItemAsset
from pecha_api.group_assets.repository import (
    get_assets_by_ids,
    replace_item_assets,
)
from pecha_api.group_recitation_collection.repository import (
    get_collection_by_id,
    get_collection_item_by_id,
    get_collection_items,
)
from pecha_api.group_recitation_collection.response_models import (
    GroupRecitationCollectionDetailDTO,
)
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_repository import get_group_by_id
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.plans.shared.permissions import require_can_create_content

logger = logging.getLogger(__name__)

MAX_AUDIO_ASSETS_PER_ITEM = 10
MAX_AUDIO_ASSETS_MESSAGE = (
    f"An item can have at most {MAX_AUDIO_ASSETS_PER_ITEM} audio assets"
)
DUPLICATE_ASSET_IDS = "Duplicate asset ids are not allowed"


async def set_item_audio_service(
    token: str,
    group_id: UUID,
    collection_id: UUID,
    item_id: UUID,
    asset_ids: List[UUID],
) -> "GroupRecitationCollectionDetailDTO":
    """Replace an item's ordered audio set.

    The array is the state: this links, unlinks and reorders in one atomic
    replace, with display_order taken from the array index. Sending the same
    body twice changes nothing; [] clears the item.
    """
    if len(asset_ids) != len(set(asset_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=DUPLICATE_ASSET_IDS,
        )
    if len(asset_ids) > MAX_AUDIO_ASSETS_PER_ITEM:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MAX_AUDIO_ASSETS_MESSAGE,
        )

    with SessionLocal() as db:
        author = validate_and_extract_author_details(token=token)
        if not get_group_by_id(db=db, group_id=group_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )
        require_can_create_content(db=db, group_id=group_id, author=author)

        collection = get_collection_by_id(
            db=db, collection_id=collection_id, group_id=group_id
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        item = get_collection_item_by_id(
            db=db, item_id=item_id, collection_id=collection_id
        )
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=NOT_FOUND,
            )

        links: List[GroupRecitationCollectionItemAsset] = []
        if asset_ids:
            # Scoped to this group, so an asset from another group resolves to
            # nothing and is reported as not found rather than forbidden.
            # Locked, so a concurrent delete cannot soft-delete these assets
            # between this check and the link insert below.
            assets = get_assets_by_ids(
                db=db, group_id=group_id, asset_ids=asset_ids, for_update=True
            )
            assets_by_id = {asset.id: asset for asset in assets}

            missing = [str(aid) for aid in asset_ids if aid not in assets_by_id]
            if missing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Assets not found: {', '.join(missing)}",
                )

            wrong_type = [
                str(aid)
                for aid in asset_ids
                if assets_by_id[aid].asset_type != GroupAssetType.AUDIO
            ]
            if wrong_type:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Assets are not audio: {', '.join(wrong_type)}",
                )

            links = [
                GroupRecitationCollectionItemAsset(
                    item_id=item_id,
                    asset_id=asset_id,
                    display_order=index,
                    created_by=author.email,
                )
                for index, asset_id in enumerate(asset_ids, start=1)
            ]

        replace_item_assets(db=db, item_id=item_id, links=links)

        # Imported here: cms_service imports this module's siblings, so a
        # top-level import would close a cycle.
        from pecha_api.group_recitation_collection.cms_service import (
            _build_items_dto,
            _generate_presigned_url,
        )

        updated_items = get_collection_items(db=db, collection_id=collection_id)
        items_dto = await _build_items_dto(updated_items, db=db)

        return GroupRecitationCollectionDetailDTO(
            id=collection.id,
            group_id=collection.group_id,
            name=collection.name,
            img_url=_generate_presigned_url(collection.img_url),
            created_at=(
                collection.created_at.isoformat()
                if hasattr(collection.created_at, "isoformat")
                else str(collection.created_at)
            ),
            items=items_dto,
        )
