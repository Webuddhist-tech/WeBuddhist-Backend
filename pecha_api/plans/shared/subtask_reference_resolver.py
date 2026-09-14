"""Resolution and validation for subtasks that reference other content.

A subtask whose content_type is one of REFERENCE_CONTENT_TYPES carries no
inline content: it stores the target's id in `reference_id` and the
content_type says which table that id belongs to. This module turns those
ids into a display payload at read time and enforces, at write time, that
the target exists and belongs to the plan's own group.
"""
import logging
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.config import get
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.plans_enums import ContentType, REFERENCE_CONTENT_TYPES
from pecha_api.plans.response_message import BAD_REQUEST
from pecha_api.uploads.S3_utils import generate_presigned_access_url

logger = logging.getLogger(__name__)

REFERENCE_ID_REQUIRED = "A reference_id is required for this content type"
REFERENCE_NOT_FOUND = "The referenced content was not found in this plan's group"
REFERENCE_ID_NOT_ALLOWED = "reference_id is only valid for reference content types"


class SubTaskReferenceDTO(BaseModel):
    """Display payload for a subtask that points at other content."""

    id: UUID
    content_type: ContentType
    title: Optional[str] = None
    subtitle: Optional[str] = None
    image_url: Optional[str] = None
    group_id: Optional[UUID] = None


def _presign(s3_key: Optional[str]) -> Optional[str]:
    if not s3_key:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=s3_key,
        )
    except Exception:
        logger.exception("Failed to presign subtask reference image '%s'", s3_key)
        return None


def _language_value(language) -> Optional[str]:
    if language is None:
        return None
    return language.value if hasattr(language, "value") else str(language)


def _pick_metadata(entries, language):
    """Pick the metadata row for `language`, else the first one available.

    `language` may be a plain code or a LanguageCode enum (plans carry the
    enum), so it goes through the same unwrapping as the stored value.
    """
    entries = list(entries or [])
    wanted = (_language_value(language) or "").upper()
    if wanted:
        for entry in entries:
            if (_language_value(entry.language) or "").upper() == wanted:
                return entry
    return next(iter(entries), None)


def _truncate(value: Optional[str], limit: int = 120) -> Optional[str]:
    if not value:
        return None
    collapsed = " ".join(value.split())
    if not collapsed:
        # Whitespace-only text is no title at all; let the caller fall back.
        return None
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _load_group_accumulations(db: Session, ids: List[UUID], language: Optional[str]):
    from pecha_api.accumulator.group_accumulator_models import GroupAccumulator

    rows = (
        db.query(GroupAccumulator)
        .filter(GroupAccumulator.id.in_(ids), GroupAccumulator.deleted_at.is_(None))
        .all()
    )
    return {
        row.id: SubTaskReferenceDTO(
            id=row.id,
            content_type=ContentType.GROUP_ACCUMULATION,
            title=row.title,
            image_url=_presign(row.image_key),
            group_id=row.group_id,
        )
        for row in rows
    }


def _load_group_collections(db: Session, ids: List[UUID], language: Optional[str]):
    from pecha_api.group_recitation_collection.models import GroupRecitationCollection

    rows = (
        db.query(GroupRecitationCollection)
        .filter(
            GroupRecitationCollection.id.in_(ids),
            GroupRecitationCollection.deleted_at.is_(None),
        )
        .all()
    )
    return {
        row.id: SubTaskReferenceDTO(
            id=row.id,
            content_type=ContentType.GROUP_COLLECTION,
            title=row.name,
            image_url=_presign(row.img_url),
            group_id=row.group_id,
        )
        for row in rows
    }


def _load_events(db: Session, ids: List[UUID], language: Optional[str]):
    from pecha_api.events.event_model import Event

    rows = db.query(Event).filter(Event.id.in_(ids)).all()
    resolved = {}
    for row in rows:
        metadata = _pick_metadata(row.metadata_entries, language)
        resolved[row.id] = SubTaskReferenceDTO(
            id=row.id,
            content_type=ContentType.EVENT,
            title=metadata.name if metadata else None,
            subtitle=_truncate(metadata.description if metadata else None),
            image_url=_presign(row.image_url),
            group_id=row.group_id,
        )
    return resolved


def _load_posts(db: Session, ids: List[UUID], language: Optional[str]):
    from pecha_api.group_posts.enums import GroupPostStatus
    from pecha_api.group_posts.models import GroupPost

    # A hidden post is not public content, so it is not referenceable: it must
    # resolve to nothing on read and be rejected on write, same as a deleted one.
    rows = (
        db.query(GroupPost)
        .filter(
            GroupPost.id.in_(ids),
            GroupPost.deleted_at.is_(None),
            GroupPost.status == GroupPostStatus.PUBLISHED,
        )
        .all()
    )
    resolved = {}
    for row in rows:
        # Posts have no title; the caption stands in for one and the first
        # media item (if any) supplies the thumbnail.
        first_media = next(iter(row.media or []), None)
        resolved[row.id] = SubTaskReferenceDTO(
            id=row.id,
            content_type=ContentType.POST,
            title=_truncate(row.caption, limit=80),
            image_url=_presign(
                getattr(first_media, "thumbnail_key", None)
                or getattr(first_media, "media_key", None)
            ),
            group_id=row.group_id,
        )
    return resolved


_LOADERS = {
    ContentType.GROUP_ACCUMULATION: _load_group_accumulations,
    ContentType.GROUP_COLLECTION: _load_group_collections,
    ContentType.EVENT: _load_events,
    ContentType.POST: _load_posts,
}


def resolve_subtask_references(
    subtasks,
    db: Optional[Session] = None,
    language: Optional[str] = None,
) -> List[Optional[SubTaskReferenceDTO]]:
    """Hydrate reference subtasks, index-aligned with `subtasks`.

    One query per referenced content type, not one per subtask. A subtask
    that isn't a reference type - or whose target has since been deleted -
    comes back as None at its position rather than shifting the list.
    Callers without a session in hand can omit `db` and one is opened for
    the lookups.
    """
    subtasks = list(subtasks)
    ids_by_type: Dict[ContentType, List[UUID]] = {}
    for sub_task in subtasks:
        content_type = sub_task.content_type
        reference_id = getattr(sub_task, "reference_id", None)
        if content_type in REFERENCE_CONTENT_TYPES and reference_id:
            ids_by_type.setdefault(content_type, []).append(reference_id)

    if not ids_by_type:
        return [None] * len(subtasks)

    if db is None:
        from pecha_api.db.database import SessionLocal

        with SessionLocal() as owned_db:
            resolved_by_type = _load_all(owned_db, ids_by_type, language)
    else:
        resolved_by_type = _load_all(db, ids_by_type, language)

    return [
        resolved_by_type.get(sub_task.content_type, {}).get(
            getattr(sub_task, "reference_id", None)
        )
        for sub_task in subtasks
    ]


def _load_all(
    db: Session,
    ids_by_type: Dict[ContentType, List[UUID]],
    language: Optional[str],
) -> Dict[ContentType, Dict[UUID, SubTaskReferenceDTO]]:
    resolved_by_type: Dict[ContentType, Dict[UUID, SubTaskReferenceDTO]] = {}
    for content_type, ids in ids_by_type.items():
        try:
            resolved_by_type[content_type] = _LOADERS[content_type](
                db, list(set(ids)), language
            )
        except Exception:
            logger.exception("Failed to resolve %s subtask references", content_type)
            resolved_by_type[content_type] = {}
    return resolved_by_type


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ResponseError(error=BAD_REQUEST, message=message).model_dump(),
    )


def validate_subtask_reference(
    db: Session,
    content_type,
    reference_id: Optional[UUID],
    group_id: UUID,
) -> None:
    """Reject a reference subtask whose target is missing or in another group.

    Plans are owned by a group, and every referenceable entity is
    group-scoped, so a plan may only link content from its own group.
    """
    content_type = (
        content_type if isinstance(content_type, ContentType) else ContentType(content_type)
    )

    if content_type not in REFERENCE_CONTENT_TYPES:
        if reference_id is not None:
            raise _bad_request(REFERENCE_ID_NOT_ALLOWED)
        return

    if reference_id is None:
        raise _bad_request(REFERENCE_ID_REQUIRED)

    resolved = _LOADERS[content_type](db, [reference_id], None).get(reference_id)
    if resolved is None or resolved.group_id != group_id:
        raise _bad_request(REFERENCE_NOT_FOUND)
