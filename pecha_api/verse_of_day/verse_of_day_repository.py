from sqlalchemy.orm import Session, joinedload
from typing import Optional, List, Dict
from uuid import UUID
from datetime import date, datetime
import _datetime

from .verse_of_day_model import VerseOfDay
from .verse_metadata_model import VerseMetadata
from .verse_of_day_enums import SortOrder
from pecha_api.plans.groups.groups_enums import AuthorGroupType
from pecha_api.plans.groups.groups_models import AuthorGroup, AuthorGroupMetadata


def get_verse_of_day_by_filters(
    db: Session,
    group_id: Optional[UUID] = None,
    filter_date: Optional[date] = None
) -> Optional[VerseOfDay]:

    query = db.query(VerseOfDay).options(joinedload(VerseOfDay.verse_metadata))
    
    if group_id is not None:
        query = query.filter(VerseOfDay.group_id == group_id)
    
    if filter_date is not None:
        query = query.filter(VerseOfDay.date == filter_date)
    
    return query.first()


def get_verses_of_day_list(
    db: Session,
    group_id: Optional[UUID] = None,
    filter_date: Optional[date] = None,
    search: Optional[str] = None,
    sort_order: SortOrder = SortOrder.DESC,
    skip: int = 0,
    limit: int = 100
) -> tuple[List[VerseOfDay], int]:
    """Get list of verses with search, sorting, and pagination."""
    query = db.query(VerseOfDay).options(joinedload(VerseOfDay.verse_metadata))

    if group_id is not None:
        query = query.filter(VerseOfDay.group_id == group_id)

    if filter_date is not None:
        query = query.filter(VerseOfDay.date == filter_date)

    if search:
        query = query.filter(
            VerseOfDay.verse_metadata.any(VerseMetadata.verse.ilike(f"%{search}%"))
        )

    total = query.count()

    order_by = VerseOfDay.date.asc() if sort_order == SortOrder.ASC else VerseOfDay.date.desc()
    verses = query.order_by(order_by).offset(skip).limit(limit).all()

    return verses, total


def get_verse_of_day_by_id(db: Session, verse_id: UUID) -> Optional[VerseOfDay]:

    return db.query(VerseOfDay).options(
        joinedload(VerseOfDay.verse_metadata)
    ).filter(VerseOfDay.id == verse_id).first()


def get_verse_of_day_today(db: Session, today: date) -> Optional[VerseOfDay]:

    return db.query(VerseOfDay).options(
        joinedload(VerseOfDay.verse_metadata)
    ).filter(VerseOfDay.date == today).first()


def create_verse_of_day(db: Session, verse_of_day: VerseOfDay) -> VerseOfDay:

    db.add(verse_of_day)
    db.commit()
    db.refresh(verse_of_day)
    return verse_of_day


def create_verse_metadata(
    db: Session, 
    verse_of_day_id: UUID, 
    lang: str, 
    verse: str
) -> VerseMetadata:
    metadata = VerseMetadata(
        verse_of_day_id=verse_of_day_id,
        lang=lang,
        verse=verse
    )
    db.add(metadata)
    db.commit()
    db.refresh(metadata)
    return metadata


def create_verse_metadata_bulk(
    db: Session,
    verse_of_day_id: UUID,
    verses: Dict[str, str]
) -> List[VerseMetadata]:
    metadata_list = []
    for lang, verse in verses.items():
        metadata = VerseMetadata(
            verse_of_day_id=verse_of_day_id,
            lang=lang,
            verse=verse
        )
        db.add(metadata)
        metadata_list.append(metadata)
    
    db.commit()
    for m in metadata_list:
        db.refresh(m)
    return metadata_list


def get_verse_metadata_by_verse_of_day_id(
    db: Session, 
    verse_of_day_id: UUID
) -> List[VerseMetadata]:
    return db.query(VerseMetadata).filter(
        VerseMetadata.verse_of_day_id == verse_of_day_id
    ).all()


def get_verse_metadata_by_lang(
    db: Session,
    verse_of_day_id: UUID,
    lang: str
) -> Optional[VerseMetadata]:
    return db.query(VerseMetadata).filter(
        VerseMetadata.verse_of_day_id == verse_of_day_id,
        VerseMetadata.lang == lang
    ).first()


def get_group_metadata_by_group_id(
    db: Session,
    group_id: UUID
) -> List[AuthorGroupMetadata]:
    return db.query(AuthorGroupMetadata).filter(
        AuthorGroupMetadata.group_id == group_id
    ).all()


def get_page_by_id(db: Session, page_id: UUID) -> Optional[AuthorGroup]:
    """A live (not deleted) PAGE-type group, or None."""
    return db.query(AuthorGroup).filter(
        AuthorGroup.id == page_id,
        AuthorGroup.group_type == AuthorGroupType.PAGE,
        AuthorGroup.deleted_at.is_(None),
    ).first()


def update_verse_of_day(
    db: Session,
    verse_id: UUID,
    updates: Dict,
    updated_by: str
) -> Optional[VerseOfDay]:
    verse = db.query(VerseOfDay).filter(VerseOfDay.id == verse_id).first()
    
    if not verse:
        return None
    
    for key, value in updates.items():
        if hasattr(verse, key):
            setattr(verse, key, value)
    
    verse.updated_at = datetime.now(_datetime.timezone.utc)
    verse.updated_by = updated_by
    
    db.commit()
    db.refresh(verse)
    return verse


def delete_verse_metadata_by_verse_id(db: Session, verse_of_day_id: UUID) -> None:
    db.query(VerseMetadata).filter(
        VerseMetadata.verse_of_day_id == verse_of_day_id
    ).delete()
    db.commit()


def delete_verse_of_day(db: Session, verse_id: UUID) -> bool:
    verse = db.query(VerseOfDay).filter(VerseOfDay.id == verse_id).first()
    
    if not verse:
        return False
    
    db.delete(verse)
    db.commit()
    return True


def delete_verses_of_day_older_than(db: Session, cutoff_date: date) -> int:
    deleted_count = (
        db.query(VerseOfDay)
        .filter(VerseOfDay.date < cutoff_date)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted_count
