from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.cms.cms_plans_repository import get_plan_by_id
from pecha_api.plans.tags.tag_helpers import generate_tag_image_url, tags_to_summary_dtos
from pecha_api.plans.tags.tag_model import Tag
from pecha_api.plans.tags.tag_metadata_model import TagMetadata
from pecha_api.plans.tags.tag_repository import (
    delete_tag_metadata_by_tag_id,
    get_tag_by_id,
    get_tag_by_name,
    get_tag_metadata_by_tag_and_language,
    get_tags_paginated,
    get_tags_by_ids,
    get_next_tag_display_order,
    save_tag,
    save_tag_metadata,
    set_tag_plans,
    set_tag_segments,
    soft_delete_tag,
    update_tag_row,
)
from pecha_api.plans.tags.tag_response_models import (
    CreateTagRequest,
    TagDTO,
    TagMetadataDTO,
    TagsListResponse,
    UpdateTagRequest,
)
from pecha_api.plans.tags.tag_segments_openpecha import validate_segment_ids


def _active_plan_ids(tag: Tag) -> List[UUID]:
    if not tag.plans:
        return []
    return [p.id for p in tag.plans if p.deleted_at is None]


def _tag_segment_ids(tag: Tag) -> List[str]:
    return getattr(tag, "segment_ids", []) or []


def _tag_to_dto(tag: Tag, language: str = 'EN') -> TagDTO:
    featured = tag.featured if isinstance(tag.featured, bool) else False
    
    # Get name and description from metadata for the specified language
    name = ""
    description = None
    metadata_dtos = []
    
    if hasattr(tag, 'metadata_entries') and tag.metadata_entries:
        for meta in tag.metadata_entries:
            metadata_dtos.append(TagMetadataDTO(
                id=meta.id,
                language=meta.language.value if hasattr(meta.language, 'value') else str(meta.language),
                name=meta.name,
                description=meta.description
            ))
            if (hasattr(meta.language, 'value') and meta.language.value == language) or str(meta.language) == language:
                name = meta.name
                description = meta.description
        
        # Fallback to first metadata entry if requested language not found
        if not name and tag.metadata_entries:
            first_meta = tag.metadata_entries[0]
            name = first_meta.name
            description = first_meta.description
    
    return TagDTO(
        id=tag.id,
        name=name,
        image=generate_tag_image_url(tag.image_key),
        image_key=tag.image_key,
        description=description,
        featured=featured,
        plan_ids=_active_plan_ids(tag),
        segment_ids=_tag_segment_ids(tag),
        display_order=tag.display_order,
        metadata=metadata_dtos,
    )


def _validate_plan_ids(db, plan_ids: List[UUID]) -> None:
    if not plan_ids:
        return
    seen = set()
    for plan_id in plan_ids:
        if plan_id in seen:
            continue
        seen.add(plan_id)
        plan = get_plan_by_id(db=db, plan_id=plan_id)
        if plan is None or plan.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Plan with id '{plan_id}' does not exist",
            )


def _segments_by_language_from_metadata(
    metadata_inputs: List,
    fallback_segment_ids: Optional[List[str]] = None,
) -> dict[str, List[str]]:
    segments_by_language: dict[str, List[str]] = {}
    for meta_input in metadata_inputs:
        if meta_input.segment_ids is not None:
            segments_by_language[meta_input.language] = meta_input.segment_ids
    if fallback_segment_ids is not None and "EN" not in segments_by_language:
        segments_by_language["EN"] = fallback_segment_ids
    return segments_by_language


def _apply_tag_segments_by_language(
    db_session,
    tag: Tag,
    segments_by_language: dict[str, List[str]],
    commit: bool = False,
) -> None:
    for language, segment_ids in segments_by_language.items():
        set_tag_segments(
            db=db_session,
            tag=tag,
            segment_ids=segment_ids,
            language=language,
            commit=commit,
        )


async def create_new_tag(token: str, create_tag_request: CreateTagRequest) -> TagDTO:
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db_session:
        # Validate metadata entries
        if not create_tag_request.metadata or len(create_tag_request.metadata) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one metadata entry is required",
            )
        
        # Check for duplicate names in any language
        for meta_input in create_tag_request.metadata:
            existing = get_tag_by_name(db=db_session, name=meta_input.name, language=meta_input.language)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Tag with name '{meta_input.name}' in language '{meta_input.language}' already exists",
                )

        plan_ids = create_tag_request.plan_ids or []
        segments_by_language = _segments_by_language_from_metadata(
            metadata_inputs=create_tag_request.metadata,
            fallback_segment_ids=create_tag_request.segment_ids,
        )
        _validate_plan_ids(db=db_session, plan_ids=plan_ids)
        for segment_ids in segments_by_language.values():
            await validate_segment_ids(segment_ids)

        tag = Tag(
            image_key=create_tag_request.image_key,
            featured=create_tag_request.featured,
            display_order=(
                create_tag_request.display_order
                if create_tag_request.display_order is not None
                else get_next_tag_display_order(db=db_session)
            ),
            updated_by=author.email,
        )
        try:
            # Use commit=False to defer commit until all operations complete
            tag = save_tag(db=db_session, tag=tag, commit=False)
            
            # Create metadata entries
            for meta_input in create_tag_request.metadata:
                tag_metadata = TagMetadata(
                    tag_id=tag.id,
                    name=meta_input.name.strip(),
                    description=meta_input.description,
                    language=meta_input.language,
                )
                save_tag_metadata(db=db_session, tag_metadata=tag_metadata, commit=False)
            
            if plan_ids:
                tag = set_tag_plans(db=db_session, tag=tag, plan_ids=plan_ids, commit=False)
            if segments_by_language:
                _apply_tag_segments_by_language(
                    db_session=db_session,
                    tag=tag,
                    segments_by_language=segments_by_language,
                    commit=False,
                )
            
            # Single commit for the entire transaction
            db_session.commit()
            
            tag = get_tag_by_id(db=db_session, tag_id=tag.id)
            return _tag_to_dto(tag)
        except IntegrityError:
            db_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tag metadata constraint violation",
            )


async def update_existing_tag(token: str, tag_id: UUID, update_tag_request: UpdateTagRequest) -> TagDTO:
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db_session:
        tag = get_tag_by_id(db=db_session, tag_id=tag_id)
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tag with id '{tag_id}' not found",
            )

        if update_tag_request.metadata is not None:
            # Validate metadata entries for duplicates
            for meta_input in update_tag_request.metadata:
                other = get_tag_by_name(db=db_session, name=meta_input.name, language=meta_input.language)
                if other and other.id != tag_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Tag with name '{meta_input.name}' in language '{meta_input.language}' already exists",
                    )
            
            # Delete existing metadata and create new ones (defer commit)
            delete_tag_metadata_by_tag_id(db=db_session, tag_id=tag_id, commit=False)
            for meta_input in update_tag_request.metadata:
                tag_metadata = TagMetadata(
                    tag_id=tag.id,
                    name=meta_input.name.strip(),
                    description=meta_input.description,
                    language=meta_input.language,
                )
                save_tag_metadata(db=db_session, tag_metadata=tag_metadata, commit=False)

        if update_tag_request.image_key is not None:
            tag.image_key = update_tag_request.image_key
        if update_tag_request.featured is not None:
            tag.featured = update_tag_request.featured
        if update_tag_request.display_order is not None:
            tag.display_order = update_tag_request.display_order

        tag.updated_at = datetime.now(timezone.utc)
        tag.updated_by = author.email

        if update_tag_request.plan_ids is not None:
            _validate_plan_ids(db=db_session, plan_ids=update_tag_request.plan_ids)
            tag = set_tag_plans(db=db_session, tag=tag, plan_ids=update_tag_request.plan_ids, commit=False)

        segments_by_language = None
        if update_tag_request.metadata is not None:
            segments_by_language = _segments_by_language_from_metadata(
                metadata_inputs=update_tag_request.metadata,
            )
        elif update_tag_request.segment_ids is not None:
            segments_by_language = {"EN": update_tag_request.segment_ids}

        if segments_by_language is not None:
            for segment_ids in segments_by_language.values():
                await validate_segment_ids(segment_ids)
            _apply_tag_segments_by_language(
                db_session=db_session,
                tag=tag,
                segments_by_language=segments_by_language,
                commit=False,
            )

        try:
            # Single commit for the entire transaction
            update_tag_row(db=db_session, tag=tag, commit=False)
            db_session.commit()
            
            tag = get_tag_by_id(db=db_session, tag_id=tag.id)
            return _tag_to_dto(tag)
        except IntegrityError:
            db_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tag metadata constraint violation",
            )


def delete_tag(token: str, tag_id: UUID) -> None:
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db_session:
        tag = get_tag_by_id(db=db_session, tag_id=tag_id)
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tag with id '{tag_id}' not found",
            )
        soft_delete_tag(db=db_session, tag=tag, deleted_by=author.email)


def get_cms_tags_list(
    token: str,
    search: Optional[str],
    language: str = 'EN',
    skip: int = 0,
    limit: int = 10,
) -> TagsListResponse:
    validate_and_extract_author_details(token=token)

    with SessionLocal() as db_session:
        rows, total = get_tags_paginated(
            db=db_session,
            search=search,
            skip=skip,
            limit=limit,
            language=language,
        )

    return TagsListResponse(
        tags=[_tag_to_dto(row, language=language) for row in rows],
        skip=skip,
        limit=limit,
        total=total,
    )


def get_cms_tag_detail(token: str, tag_id: UUID, language: str = 'EN') -> TagDTO:
    validate_and_extract_author_details(token=token)

    with SessionLocal() as db_session:
        tag = get_tag_by_id(db=db_session, tag_id=tag_id, language=language)
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag with id '{tag_id}' not found",
        )
    return _tag_to_dto(tag, language=language)


def validate_tag_ids(db, tag_ids: List[UUID]) -> None:
    if not tag_ids:
        return
    found = get_tags_by_ids(db=db, tag_ids=tag_ids)
    found_ids = {t.id for t in found}
    for tag_id in tag_ids:
        if tag_id not in found_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tag with id '{tag_id}' does not exist",
            )
