from typing import Optional, Dict, List
from uuid import UUID
from datetime import date, datetime, timedelta, timezone
import logging

from pecha_api.timezone_utils import get_date_in_timezone
from fastapi import HTTPException
from starlette import status

from ..db.database import SessionLocal
from .verse_of_day_repository import (
    get_verse_of_day_by_filters, 
    get_verses_of_day_list,
    get_verse_of_day_by_id, 
    get_verse_of_day_today, 
    create_verse_of_day,
    create_verse_metadata_bulk,
    get_group_metadata_by_group_id,
    update_verse_of_day,
    delete_verse_metadata_by_verse_id,
    delete_verse_of_day,
    delete_verses_of_day_older_than,
)
from .verse_of_day_response_models import (
    VerseOfDayPublicDTO, 
    VerseOfDayPublicResponse,
    VerseOfDayListResponse,
    CreateVerseOfDayRequest, 
    UpdateVerseOfDayRequest,
    VerseOfDayDTO,
    VersesDict,
    GroupInfoDTO
)
from .verse_of_day_model import VerseOfDay
from .verse_of_day_enums import SortOrder
from ..uploads.S3_utils import generate_presigned_access_url
from ..config import get

logger = logging.getLogger(__name__)


def _generate_verse_image_url(image_keys: Optional[List[str]]) -> Optional[str]:

    if not image_keys:
        logger.debug(f"No image_keys provided: {image_keys}")
        return None
    
    logger.debug(f"Generating presigned URL for image_keys: {image_keys}")
    bucket_name = get("AWS_BUCKET_NAME")
    
    for key in image_keys:
        if not key or not isinstance(key, str) or not key.strip():
            logger.debug(f"Skipping invalid key: {key}")
            continue
            
        try:
            presigned_url = generate_presigned_access_url(bucket_name, key)
            logger.debug(f"Generated presigned URL for key {key}: {presigned_url[:100] if presigned_url else None}...")
            if presigned_url:
                return presigned_url  
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for key {key}: {e}", exc_info=True)
            continue
    
    return None  


def build_verses_dict(verse_metadata_list) -> VersesDict:
    """Build a dictionary of verses by language from verse_metadata relationship."""
    verses = {}
    for metadata in verse_metadata_list:
        verses[metadata.lang] = metadata.verse
    return verses


def build_public_dto(verse: VerseOfDay, lang: Optional[str] = None, group_info: Optional[List[GroupInfoDTO]] = None) -> VerseOfDayPublicDTO:
    """Build public DTO with optional language filtering and group metadata."""
    verses_dict = build_verses_dict(verse.verse_metadata) if verse.verse_metadata else {}
    
    # Generate presigned URL from first S3 key
    presigned_image_url = _generate_verse_image_url(verse.image_urls)
    
    if lang and lang in verses_dict:
        return VerseOfDayPublicDTO(
            id=verse.id,
            verse=verses_dict[lang],
            verses=None,
            image_url=presigned_image_url,
            ref_id=verse.ref_id,
            source=verse.source,
            ref_type=verse.ref_type,
            date=verse.date,
            group_id=verse.group_id,
            group_info=group_info
        )
    else:
        return VerseOfDayPublicDTO(
            id=verse.id,
            verses=verses_dict if verses_dict else None,
            verse=None,
            image_url=presigned_image_url,
            ref_id=verse.ref_id,
            source=verse.source,
            ref_type=verse.ref_type,
            date=verse.date,
            group_id=verse.group_id,
            group_info=group_info
        )


def get_verse_of_day(
    group_id: Optional[UUID] = None,
    filter_date: Optional[date] = None,
    lang: Optional[str] = None
) -> VerseOfDayPublicResponse:

    with SessionLocal() as db:
        verse = get_verse_of_day_by_filters(db, group_id=group_id, filter_date=filter_date)
        
        if verse is None:
            return VerseOfDayPublicResponse(verse_of_day=None)
        
        # Fetch group metadata if group_id exists
        group_info = None
        if verse.group_id:
            group_metadata_list = get_group_metadata_by_group_id(db, verse.group_id)
            if group_metadata_list:
                # Filter by language if lang parameter is provided
                if lang:
                    filtered_metadata = [m for m in group_metadata_list if m.language.lower() == lang.lower()]
                else:
                    filtered_metadata = group_metadata_list
                
                if filtered_metadata:
                    group_info = [
                        GroupInfoDTO(
                            id=metadata.id,
                            title=metadata.title,
                            sub_title=metadata.sub_title,
                            description=metadata.description,
                            language=metadata.language
                        )
                        for metadata in filtered_metadata
                    ]
        
        return VerseOfDayPublicResponse(
            verse_of_day=build_public_dto(verse, lang, group_info)
        )


def get_verses_of_day_list_service(
    group_id: Optional[UUID] = None,
    filter_date: Optional[date] = None,
    lang: Optional[str] = None,
    search: Optional[str] = None,
    sort_order: SortOrder = SortOrder.DESC,
    skip: int = 0,
    limit: int = 100
) -> VerseOfDayListResponse:
    """Get list of verses with search, sorting, and pagination."""
    with SessionLocal() as db:
        verses, total = get_verses_of_day_list(db, group_id=group_id, filter_date=filter_date, search=search, sort_order=sort_order, skip=skip, limit=limit)
        
        verse_dtos = []
        for verse in verses:
            # Fetch group metadata if group_id exists
            group_info = None
            if verse.group_id:
                group_metadata_list = get_group_metadata_by_group_id(db, verse.group_id)
                if group_metadata_list:
                    # Filter by language if lang parameter is provided
                    if lang:
                        filtered_metadata = [m for m in group_metadata_list if m.language.lower() == lang.lower()]
                    else:
                        filtered_metadata = group_metadata_list
                    
                    if filtered_metadata:
                        group_info = [
                            GroupInfoDTO(
                                id=metadata.id,
                                title=metadata.title,
                                sub_title=metadata.sub_title,
                                description=metadata.description,
                                language=metadata.language
                            )
                            for metadata in filtered_metadata
                        ]
            
            verse_dtos.append(build_public_dto(verse, lang, group_info))
        
        return VerseOfDayListResponse(verses=verse_dtos, total=total)


def get_verse_of_day_by_id_service(
    verse_id: UUID,
    lang: Optional[str] = None
) -> VerseOfDayPublicResponse:

    with SessionLocal() as db:
        verse = get_verse_of_day_by_id(db, verse_id=verse_id)
        
        if verse is None:
            return VerseOfDayPublicResponse(verse_of_day=None)
        
        # Fetch group metadata if group_id exists
        group_info = None
        if verse.group_id:
            group_metadata_list = get_group_metadata_by_group_id(db, verse.group_id)
            if group_metadata_list:
                # Filter by language if lang parameter is provided
                if lang:
                    filtered_metadata = [m for m in group_metadata_list if m.language.lower() == lang.lower()]
                else:
                    filtered_metadata = group_metadata_list
                
                if filtered_metadata:
                    group_info = [
                        GroupInfoDTO(
                            id=metadata.id,
                            title=metadata.title,
                            sub_title=metadata.sub_title,
                            description=metadata.description,
                            language=metadata.language
                        )
                        for metadata in filtered_metadata
                    ]
        
        return VerseOfDayPublicResponse(
            verse_of_day=build_public_dto(verse, lang, group_info)
        )


def get_verse_of_day_today_service(
    lang: Optional[str] = None,
    timezone: Optional[str] = None,
) -> VerseOfDayPublicResponse:

    with SessionLocal() as db:
        today = get_date_in_timezone(timezone)
        verse = get_verse_of_day_today(db, today=today)
        
        if verse is None:
            return VerseOfDayPublicResponse(verse_of_day=None)
        
        # Fetch group metadata if group_id exists
        group_info = None
        if verse.group_id:
            group_metadata_list = get_group_metadata_by_group_id(db, verse.group_id)
            if group_metadata_list:
                # Filter by language if lang parameter is provided
                if lang:
                    filtered_metadata = [m for m in group_metadata_list if m.language.lower() == lang.lower()]
                else:
                    filtered_metadata = group_metadata_list
                
                if filtered_metadata:
                    group_info = [
                        GroupInfoDTO(
                            id=metadata.id,
                            title=metadata.title,
                            sub_title=metadata.sub_title,
                            description=metadata.description,
                            language=metadata.language
                        )
                        for metadata in filtered_metadata
                    ]
        
        return VerseOfDayPublicResponse(
            verse_of_day=build_public_dto(verse, lang, group_info)
        )


def create_verse_of_day_service(request: CreateVerseOfDayRequest, created_by: str) -> VerseOfDayDTO:

    with SessionLocal() as db:
        # Check if a verse already exists for this date
        existing_verse = get_verse_of_day_by_filters(db, filter_date=request.date)
        if existing_verse:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A verse of the day already exists for date {request.date}. Please update the existing verse or choose a different date."
            )
        
        verse_of_day = VerseOfDay(
            verse_id=request.verse_id,
            ref_id=request.ref_id,
            source=request.source,
            ref_type=request.ref_type,
            image_urls=request.image_urls,
            group_id=request.group_id,
            date=request.date,
            created_by=created_by
        )
        
        created = create_verse_of_day(db, verse_of_day)
        
        create_verse_metadata_bulk(db, created.id, request.verses)
        
        return VerseOfDayDTO(
            id=created.id,
            verses=request.verses,
            verse_id=created.verse_id,
            ref_id=created.ref_id,
            source=created.source,
            ref_type=created.ref_type,
            image_urls=created.image_urls,
            group_id=created.group_id,
            date=created.date
        )


def update_verse_of_day_service(
    verse_id: UUID,
    request: UpdateVerseOfDayRequest,
    updated_by: str
) -> VerseOfDayDTO:

    with SessionLocal() as db:
        existing_verse = get_verse_of_day_by_id(db, verse_id)
        
        if not existing_verse:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Verse of day with ID {verse_id} not found"
            )
        
        updates = {}
        if request.verse_id is not None:
            updates['verse_id'] = request.verse_id
        if request.ref_id is not None:
            updates['ref_id'] = request.ref_id
        if "source" in request.model_fields_set:
            updates['source'] = request.source
        if request.ref_type is not None:
            updates['ref_type'] = request.ref_type
        if request.image_urls is not None:
            updates['image_urls'] = request.image_urls
        if request.group_id is not None:
            updates['group_id'] = request.group_id
        if request.date is not None:
            updates['date'] = request.date
        
        updated_verse = update_verse_of_day(db, verse_id, updates, updated_by)
        
        if request.verses is not None:
            delete_verse_metadata_by_verse_id(db, verse_id)
            create_verse_metadata_bulk(db, verse_id, request.verses)
        
        db.refresh(updated_verse)
        
        verses_dict = build_verses_dict(updated_verse.verse_metadata) if updated_verse.verse_metadata else {}
        
        return VerseOfDayDTO(
            id=updated_verse.id,
            verses=verses_dict if verses_dict else None,
            verse_id=updated_verse.verse_id,
            ref_id=updated_verse.ref_id,
            source=updated_verse.source,
            ref_type=updated_verse.ref_type,
            image_urls=updated_verse.image_urls,
            group_id=updated_verse.group_id,
            date=updated_verse.date
        )


def delete_verse_of_day_service(verse_id: UUID) -> None:

    with SessionLocal() as db:
        existing_verse = get_verse_of_day_by_id(db, verse_id)
        
        if not existing_verse:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Verse of day with ID {verse_id} not found"
            )
        
        delete_verse_of_day(db, verse_id)


def cleanup_expired_verses_of_day(expiry_days: int) -> int:
    if expiry_days < 1:
        raise ValueError(f"expiry_days must be a positive integer, got {expiry_days}")
    cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=expiry_days)
    with SessionLocal() as db:
        deleted_count = delete_verses_of_day_older_than(db, cutoff_date)
        logger.info(
            "Deleted %s verse(s) of the day older than %s",
            deleted_count,
            cutoff_date,
        )
        return deleted_count
