from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import asc, delete, func, nulls_last, select
from sqlalchemy.orm import Session, selectinload

from pecha_api.plans.plans_enums import PlanStatus
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.tags.tag_model import Tag, plan_tags, tag_segments
from pecha_api.plans.tags.tag_metadata_model import TagMetadata


def _attach_segment_ids(db: Session, tags: List[Tag], language: str = "EN") -> None:
    if not tags:
        return
    segment_ids_map = get_segment_ids_map_for_tags(
        db=db,
        tag_ids=[tag.id for tag in tags],
        language=language,
    )
    for tag in tags:
        tag.segment_ids = segment_ids_map.get(tag.id, [])


def _tag_order_clauses():
    return (
        Tag.featured.desc(),
        nulls_last(asc(Tag.display_order)),
    )


def get_next_tag_display_order(db: Session) -> int:
    result = (
        db.query(func.max(Tag.display_order))
        .filter(Tag.deleted_at.is_(None))
        .scalar()
    )
    return (result or 0) + 1


def get_segment_ids_map_for_tags(
    db: Session,
    tag_ids: List[UUID],
    language: str = "EN",
) -> Dict[UUID, List[str]]:
    if not tag_ids:
        return {}
    rows = db.execute(
        select(tag_segments.c.tag_id, tag_segments.c.segment_id).where(
            tag_segments.c.tag_id.in_(tag_ids),
            tag_segments.c.language == language,
        )
    ).all()
    mapping: Dict[UUID, List[str]] = {tag_id: [] for tag_id in tag_ids}
    for tag_id, segment_id in rows:
        mapping[tag_id].append(segment_id)
    return mapping


def get_tag_by_id(
    db: Session,
    tag_id: UUID,
    include_deleted: bool = False,
    language: str = "EN",
) -> Optional[Tag]:
    query = db.query(Tag).options(
        selectinload(Tag.plans),
        selectinload(Tag.metadata_entries)
    ).filter(Tag.id == tag_id)
    if not include_deleted:
        query = query.filter(Tag.deleted_at.is_(None))
    tag = query.first()
    if tag:
        _attach_segment_ids(db=db, tags=[tag], language=language)
    return tag


def get_tag_by_name(db: Session, name: str, language: str = 'EN') -> Optional[Tag]:
    return (
        db.query(Tag)
        .join(TagMetadata, Tag.id == TagMetadata.tag_id)
        .filter(
            Tag.deleted_at.is_(None),
            func.lower(TagMetadata.name) == name.lower(),
            TagMetadata.language == language
        )
        .options(selectinload(Tag.metadata_entries))
        .first()
    )


def get_tags_paginated(
    db: Session,
    search: Optional[str],
    skip: int,
    limit: int,
    language: str = "EN",
) -> Tuple[List[Tag], int]:
    query = db.query(Tag).options(
        selectinload(Tag.plans),
        selectinload(Tag.metadata_entries)
    ).filter(Tag.deleted_at.is_(None))
    if search:
        query = query.join(TagMetadata, Tag.id == TagMetadata.tag_id).filter(
            TagMetadata.name.ilike(f"%{search}%")
        ).distinct()
    total = query.count()
    rows = (
        query.order_by(*_tag_order_clauses())
        .offset(skip)
        .limit(limit)
        .all()
    )
    _attach_segment_ids(db=db, tags=rows, language=language)
    return rows, total


def save_tag(db: Session, tag: Tag, commit: bool = True) -> Tag:
    db.add(tag)
    if commit:
        db.commit()
        db.refresh(tag)
    else:
        db.flush()
    return tag


def update_tag_row(db: Session, tag: Tag, commit: bool = True) -> Tag:
    if commit:
        db.commit()
        db.refresh(tag)
    else:
        db.flush()
    return tag


def soft_delete_tag(db: Session, tag: Tag, deleted_by: str) -> None:
    tag.deleted_at = datetime.now(timezone.utc)
    tag.deleted_by = deleted_by
    db.commit()


def get_tags_by_ids(db: Session, tag_ids: List[UUID]) -> List[Tag]:
    if not tag_ids:
        return []
    return (
        db.query(Tag)
        .filter(Tag.id.in_(tag_ids), Tag.deleted_at.is_(None))
        .all()
    )


def set_tag_plans(db: Session, tag: Tag, plan_ids: List[UUID], commit: bool = True) -> Tag:
    plans = db.query(Plan).filter(Plan.id.in_(plan_ids), Plan.deleted_at.is_(None)).all() if plan_ids else []
    tag.plans = plans
    if commit:
        db.commit()
        db.refresh(tag)
    else:
        db.flush()
    return tag


def set_tag_segments(
    db: Session,
    tag: Tag,
    segment_ids: List[str],
    language: str = "EN",
    commit: bool = True,
) -> Tag:
    unique_segment_ids = list(dict.fromkeys(segment_ids))
    db.execute(
        delete(tag_segments).where(
            tag_segments.c.tag_id == tag.id,
            tag_segments.c.language == language,
        )
    )
    if unique_segment_ids:
        rows = [
            {
                "tag_id": tag.id,
                "segment_id": segment_id,
                "language": language,
            }
            for segment_id in unique_segment_ids
        ]
        db.execute(tag_segments.insert(), rows)
    if commit:
        db.commit()
        db.refresh(tag)
    else:
        db.flush()
    tag.segment_ids = unique_segment_ids
    return tag


def set_plan_tags(db: Session, plan: Plan, tag_ids: Optional[List[UUID]]) -> Plan:
    if tag_ids is None:
        return plan
    tags = get_tags_by_ids(db=db, tag_ids=tag_ids)
    plan.tag_list = tags
    db.commit()
    db.refresh(plan)
    return plan


def get_published_tags_for_language(db: Session, language: str) -> List[Tag]:
    return (
        db.query(Tag)
        .options(selectinload(Tag.metadata_entries))
        .join(plan_tags, plan_tags.c.tag_id == Tag.id)
        .join(Plan, Plan.id == plan_tags.c.plan_id)
        .filter(
            Tag.deleted_at.is_(None),
            Plan.deleted_at.is_(None),
            Plan.status == PlanStatus.PUBLISHED,
            Plan.language == language,
        )
        .distinct()
        .order_by(*_tag_order_clauses())
        .all()
    )


def get_all_tags_paginated(
    db: Session,
    featured: Optional[bool],
    search: Optional[str],
    skip: int,
    limit: int,
) -> Tuple[List[Tag], int]:
    query = db.query(Tag).options(selectinload(Tag.metadata_entries)).filter(Tag.deleted_at.is_(None))
    if featured is not None:
        query = query.filter(Tag.featured == featured)
    if search:
        query = query.join(TagMetadata, Tag.id == TagMetadata.tag_id).filter(
            TagMetadata.name.ilike(f"%{search}%")
        ).distinct()

    total = query.count()
    rows = (
        query.order_by(*_tag_order_clauses())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows, total


def save_tag_metadata(db: Session, tag_metadata: TagMetadata, commit: bool = True) -> TagMetadata:
    db.add(tag_metadata)
    if commit:
        db.commit()
        db.refresh(tag_metadata)
    else:
        db.flush()
    return tag_metadata


def delete_tag_metadata_by_tag_id(db: Session, tag_id: UUID, commit: bool = True) -> None:
    db.execute(delete(TagMetadata).where(TagMetadata.tag_id == tag_id))
    if commit:
        db.commit()


def get_tag_metadata_by_tag_and_language(db: Session, tag_id: UUID, language: str) -> Optional[TagMetadata]:
    return (
        db.query(TagMetadata)
        .filter(TagMetadata.tag_id == tag_id, TagMetadata.language == language)
        .first()
    )
