import logging
import mimetypes
import os
import uuid
from datetime import datetime, timezone as tz
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.config import DEFAULTS, get, get_int
from pecha_api.db.database import SessionLocal
from pecha_api.group_assets.enums import GroupAssetType
from pecha_api.group_assets.models import GroupAsset
from pecha_api.group_assets.repository import (
    create_asset,
    delete_links_for_asset,
    get_asset_by_id,
    get_asset_usages,
    get_group_assets,
    soft_delete_asset,
    update_asset,
)
from pecha_api.group_assets.response_models import (
    GroupAssetDTO,
    GroupAssetUsageDTO,
    GroupAssetsResponse,
    UpdateGroupAssetRequest,
)
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_repository import get_group_by_id
from pecha_api.plans.response_message import (
    AUDIO_FILE_TOO_LARGE,
    INVALID_AUDIO_FILE_FORMAT,
    NOT_FOUND,
)
from pecha_api.plans.shared.permissions import (
    require_can_create_content,
    require_can_read_group_content,
)
from pecha_api.texts.texts_openpecha_service import get_texts_by_edition_or_text_ids
from pecha_api.uploads.S3_utils import (
    delete_file,
    generate_presigned_access_url,
    upload_file,
)

logger = logging.getLogger(__name__)

ASSET_NOT_FOUND = "Asset not found"
ASSET_IN_USE = "Asset is used by {count} recitation item(s)"
ASSET_TYPE_NOT_SUPPORTED = "Only AUDIO assets are supported"


def validate_audio_file(file: UploadFile) -> None:
    """Shared audio validation: extension allowlist and size ceiling."""
    file_extension = os.path.splitext(file.filename.lower())[1] if file.filename else ""
    if file_extension not in DEFAULTS["ALLOWED_AUDIO_EXTENSIONS"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_AUDIO_FILE_FORMAT,
        )
    if hasattr(file, "size") and file.size and file.size > get_int("MAX_AUDIO_FILE_SIZE"):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=AUDIO_FILE_TOO_LARGE,
        )


def generate_asset_presigned_url(s3_key: Optional[str]) -> Optional[str]:
    """Safely generate a presigned URL for an asset's S3 key."""
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


def build_asset_dto(asset: GroupAsset) -> GroupAssetDTO:
    """Map an asset row to its DTO, presigning on the way out."""
    asset_type = (
        asset.asset_type.value
        if hasattr(asset.asset_type, "value")
        else str(asset.asset_type)
    )
    return GroupAssetDTO(
        id=asset.id,
        group_id=asset.group_id,
        asset_type=asset_type,
        title=asset.title,
        file_name=asset.file_name,
        asset_url=generate_asset_presigned_url(asset.s3_key),
        mime_type=asset.mime_type,
        file_size_bytes=asset.file_size_bytes,
        duration_ms=asset.duration_ms,
        created_at=asset.created_at.isoformat() if asset.created_at else "",
    )


def _validate_group_exists(db: Session, group_id: UUID) -> None:
    if not get_group_by_id(db=db, group_id=group_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=NOT_FOUND,
        )


def upload_group_asset_service(
    token: str,
    group_id: UUID,
    file: UploadFile,
    asset_type: GroupAssetType,
    title: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> GroupAssetDTO:
    """Upload one file into a group's library.

    Uploading links nothing. The file is in the library the moment it lands.
    """
    if asset_type != GroupAssetType.AUDIO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ASSET_TYPE_NOT_SUPPORTED,
        )
    validate_audio_file(file)

    file_extension = os.path.splitext(file.filename.lower())[1] if file.filename else ""
    content_type = (
        file.content_type
        or mimetypes.guess_type(file.filename or "")[0]
        or "audio/mpeg"
    )
    original_name = os.path.basename(file.filename) if file.filename else "audio"

    with SessionLocal() as db:
        author = validate_and_extract_author_details(token=token)
        _validate_group_exists(db=db, group_id=group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        # Group-scoped key: an asset's ownership is legible from the key alone.
        s3_key = f"groups/{group_id}/assets/audio/{uuid.uuid4()}{file_extension}"

        file.file.seek(0)
        upload_file(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=s3_key,
            file=file,
        )

        asset = create_asset(
            db=db,
            asset=GroupAsset(
                group_id=group_id,
                asset_type=asset_type,
                title=(title or original_name)[:255],
                s3_key=s3_key,
                file_name=original_name[:255],
                mime_type=content_type[:64] if content_type else None,
                file_size_bytes=file.size if hasattr(file, "size") else None,
                duration_ms=duration_ms,
                created_by=author.email,
            ),
        )
        return build_asset_dto(asset)


def list_group_assets_service(
    token: str,
    group_id: UUID,
    asset_type: Optional[GroupAssetType] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> GroupAssetsResponse:
    """List/search a group's assets. This is the Studio picker's source."""
    with SessionLocal() as db:
        author = validate_and_extract_author_details(token=token)
        _validate_group_exists(db=db, group_id=group_id)
        require_can_read_group_content(db=db, group_id=group_id, author=author)

        assets, total = get_group_assets(
            db=db,
            group_id=group_id,
            asset_type=asset_type,
            search=search,
            skip=skip,
            limit=limit,
        )
        return GroupAssetsResponse(
            assets=[build_asset_dto(asset) for asset in assets],
            skip=skip,
            limit=limit,
            total=total,
        )


def update_group_asset_service(
    token: str,
    group_id: UUID,
    asset_id: UUID,
    request: UpdateGroupAssetRequest,
) -> GroupAssetDTO:
    """Rename an asset."""
    with SessionLocal() as db:
        author = validate_and_extract_author_details(token=token)
        _validate_group_exists(db=db, group_id=group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        asset = get_asset_by_id(db=db, group_id=group_id, asset_id=asset_id)
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ASSET_NOT_FOUND,
            )

        if request.title is not None:
            title = request.title.strip()
            if not title:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Title cannot be empty",
                )
            asset.title = title[:255]

        asset.updated_by = author.email
        asset.updated_at = datetime.now(tz.utc)
        update_asset(db=db, asset=asset)
        return build_asset_dto(asset)


async def delete_group_asset_service(
    token: str,
    group_id: UUID,
    asset_id: UUID,
    force: bool = False,
) -> None:
    """Delete an asset from the library.

    Refuses with 409 when the asset is still linked, naming what uses it: an
    author deleting from the library cannot otherwise see which collections
    they are about to silently change. force=true drops the links anyway.
    """
    with SessionLocal() as db:
        author = validate_and_extract_author_details(token=token)
        _validate_group_exists(db=db, group_id=group_id)
        require_can_create_content(db=db, group_id=group_id, author=author)

        asset = get_asset_by_id(db=db, group_id=group_id, asset_id=asset_id)
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ASSET_NOT_FOUND,
            )

        usages = get_asset_usages(db=db, asset_id=asset_id)
        if usages and not force:
            titles = await _resolve_text_titles([u[3] for u in usages])
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "detail": ASSET_IN_USE.format(count=len(usages)),
                    "usages": [
                        GroupAssetUsageDTO(
                            collection_id=collection_id,
                            collection_name=collection_name,
                            item_id=item_id,
                            text_title=titles.get(str(text_id)),
                        ).model_dump(mode="json")
                        for collection_id, collection_name, item_id, text_id in usages
                    ],
                },
            )

        if usages:
            delete_links_for_asset(db=db, asset_id=asset_id)

        s3_key = asset.s3_key
        soft_delete_asset(db=db, asset=asset, deleted_by=author.email)

    try:
        delete_file(s3_key)
    except Exception as e:
        # The row is already soft-deleted; a stranded object is recoverable,
        # a failed request the author retries is not worth the confusion.
        logger.error(f"Failed to delete S3 object {s3_key}: {e}")


async def _resolve_text_titles(text_ids: List[str]) -> Dict[str, Optional[str]]:
    """Best-effort titles for the 409 usage list, fetched in one batch."""
    if not text_ids:
        return {}
    try:
        texts = await get_texts_by_edition_or_text_ids(
            list({str(text_id) for text_id in text_ids})
        )
        return {key: text.title for key, text in texts.items()}
    except Exception as e:
        logger.error(f"Failed to resolve text titles: {e}")
        return {}
