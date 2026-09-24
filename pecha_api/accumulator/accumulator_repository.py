from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from typing import List, Tuple, Optional, Dict
from uuid import UUID
import _datetime
from _datetime import datetime
from fastapi import HTTPException
from starlette import status
from .accumulator_models import Accumulator
from .accumulator_metadata_model import AccumulatorMetadata
from .mala_image_model import MalaImage
from .accumulator_history_model import AccumulatorHistory
from .accumulator_enums import AccumulatorType
from .group_accumulator_models import GroupAccumulator
from .group_accumulator_history_model import GroupAccumulatorHistory
from .group_accumulator_join_model import group_accumulator_joins
from ..mantra.mantra_model import Mantra
from ..mantra.mantra_metadata_model import MantraMetadata


def mantra_exists(db: Session, mantra_id: UUID) -> bool:
    return db.query(Mantra.id).filter(Mantra.id == mantra_id).first() is not None


def get_mantra_mala_image_id(db: Session, mantra_id: UUID) -> Optional[UUID]:
    """Return the mantra's default mala image id, or None if the mantra has
    none set (or no mantra)."""
    return (
        db.query(Mantra.mala_image)
        .filter(Mantra.id == mantra_id)
        .scalar()
    )


def get_mala_image_by_id(db: Session, mala_image_id: UUID) -> Optional[MalaImage]:
    return db.query(MalaImage).filter(MalaImage.id == mala_image_id).first()


def add_accumulator(db: Session, accumulator: Accumulator) -> Accumulator:
    """Stage and flush the accumulator so its id is usable by dependent rows
    (e.g. history). Caller is responsible for the final commit."""
    db.add(accumulator)
    db.flush()
    return accumulator


def commit_accumulator(db: Session, accumulator: Accumulator) -> Accumulator:
    try:
        db.commit()
        db.refresh(accumulator)
        return accumulator
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)}
        )


def save_accumulator(db: Session, accumulator: Accumulator) -> Accumulator:
    add_accumulator(db, accumulator)
    return commit_accumulator(db, accumulator)


def get_accumulator_by_id(
    db: Session,
    accumulator_id: UUID,
    include_deleted: bool = False
) -> Optional[Accumulator]:
    query = db.query(Accumulator).filter(Accumulator.id == accumulator_id)
    if not include_deleted:
        query = query.filter(Accumulator.deleted_at.is_(None))
    return query.first()


def update_accumulator(db: Session, accumulator: Accumulator) -> Accumulator:
    try:
        db.commit()
        db.refresh(accumulator)
        return accumulator
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)}
        )


def delete_accumulator(db: Session, accumulator: Accumulator) -> None:
    """Soft-delete: mark deleted_at so the accumulator drops out of active
    lists while its history rows are preserved for the user's me/history page."""
    try:
        accumulator.deleted_at = datetime.now(_datetime.timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e)}
        )


def get_all_accumulators(
    db: Session,
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    show_recitations: bool = False,
) -> Tuple[List[Accumulator], int]:
    """Public list: only group-defined presets, never users' own accumulators.

    When `show_recitations` is False (default), presets with a non-null
    `text_id` are excluded so the list matches the pre-recitation catalog.

    When `search` is provided, results are limited to presets whose mantra
    metadata (mantra text, title, or pronunciation) or accumulator metadata
    (name/description) matches the term (case-insensitive substring).
    """
    query = (
        db.query(Accumulator)
        .filter(
            Accumulator.type == AccumulatorType.PRESET,
            Accumulator.deleted_at.is_(None),
        )
    )

    if not show_recitations:
        query = query.filter(Accumulator.text_id.is_(None))

    if search:
        term = f"%{search.strip()}%"
        matching_mantra_ids = (
            db.query(MantraMetadata.mantra_id)
            .filter(
                func.coalesce(MantraMetadata.mantra, "").ilike(term)
                | func.coalesce(MantraMetadata.title, "").ilike(term)
                | func.coalesce(MantraMetadata.pronunciation, "").ilike(term)
            )
        )
        matching_preset_ids = (
            db.query(AccumulatorMetadata.accumulator_id)
            .filter(
                func.coalesce(AccumulatorMetadata.name, "").ilike(term)
                | func.coalesce(AccumulatorMetadata.description, "").ilike(term)
            )
        )
        query = query.filter(
            Accumulator.mantra_id.in_(matching_mantra_ids)
            | Accumulator.id.in_(matching_preset_ids)
        )

    total = query.count()
    accumulators = query.order_by(Accumulator.created_at.desc()).offset(skip).limit(limit).all()

    return accumulators, total


def get_preset_by_id(db: Session, preset_id: UUID) -> Optional[Accumulator]:
    """Fetch an active preset row (type=PRESET) by id, or None."""
    return (
        db.query(Accumulator)
        .filter(
            Accumulator.id == preset_id,
            Accumulator.type == AccumulatorType.PRESET,
            Accumulator.deleted_at.is_(None),
        )
        .first()
    )


def get_user_accumulator_by_parent(
    db: Session,
    user_id: UUID,
    parent_id: UUID,
) -> Optional[Accumulator]:
    """Fetch the user's active accumulator created from a given preset
    (parent_id), or None. A user has at most one active accumulator per preset."""
    return (
        db.query(Accumulator)
        .filter(
            Accumulator.user_id == user_id,
            Accumulator.parent_id == parent_id,
            Accumulator.deleted_at.is_(None),
        )
        .first()
    )


def get_user_accumulators(
    db: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20
) -> Tuple[List[Accumulator], int]:

    query = (
        db.query(Accumulator)
        .filter(Accumulator.user_id == user_id, Accumulator.deleted_at.is_(None))
    )

    total = query.count()
    accumulators = query.order_by(Accumulator.created_at.desc()).offset(skip).limit(limit).all()

    return accumulators, total


def get_user_total_count(db: Session, user_id: UUID) -> int:
    """Total accumulated count across all of the user's accumulators (all types)."""
    total = (
        db.query(func.sum(AccumulatorHistory.count))
        .filter(AccumulatorHistory.user_id == user_id)
        .scalar()
    )
    return total or 0


def add_history_row(db: Session, accumulator_id: UUID, user_id: UUID, count: int) -> None:
    """Stage a history row recording a positive count delta. Caller commits."""
    db.add(
        AccumulatorHistory(
            accumulator_id=accumulator_id,
            user_id=user_id,
            count=count
        )
    )


def get_user_total_counted_by_parent(
    db: Session,
    user_id: UUID,
    parent_id: UUID,
) -> int:
    """Sum of all history counts across every accumulator the user has had
    for this preset, including soft-deleted instances."""
    total = (
        db.query(func.sum(AccumulatorHistory.count))
        .join(Accumulator, AccumulatorHistory.accumulator_id == Accumulator.id)
        .filter(
            Accumulator.user_id == user_id,
            Accumulator.parent_id == parent_id,
            AccumulatorHistory.user_id == user_id,
        )
        .scalar()
    )
    return total or 0


def get_accumulator_with_history(
    db: Session,
    user_id: UUID,
    parent_id: UUID,
) -> Optional[Tuple[Accumulator, int, List[AccumulatorHistory]]]:
    """Fetch the user's active accumulator created from a given preset
    (parent_id), along with their lifetime total counted for that preset and
    ordered session rows for the active accumulator.
    Returns None if the user has no accumulator for that preset."""
    accumulator = get_user_accumulator_by_parent(db, user_id, parent_id)
    if not accumulator:
        return None

    accumulator_id = accumulator.id
    total_counted = get_user_total_counted_by_parent(db, user_id, parent_id)

    sessions = (
        db.query(AccumulatorHistory)
        .filter(
            AccumulatorHistory.accumulator_id == accumulator_id,
            AccumulatorHistory.user_id == user_id
        )
        .order_by(AccumulatorHistory.created_at.desc())
        .all()
    )

    return accumulator, total_counted, sessions


def get_user_accumulator_history(
    db: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20
) -> Tuple[List[Tuple[Accumulator, int, List[AccumulatorHistory]]], int]:

    accumulator_ids_with_history = (
        db.query(AccumulatorHistory.accumulator_id)
        .filter(AccumulatorHistory.user_id == user_id)
        .distinct()
        .subquery()
    )

    total = db.query(Accumulator).filter(Accumulator.id.in_(accumulator_ids_with_history)).count()

    accumulators = (
        db.query(Accumulator)
        .filter(Accumulator.id.in_(accumulator_ids_with_history))
        .order_by(Accumulator.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    if not accumulators:
        return [], 0

    accumulator_ids = [accumulator.id for accumulator in accumulators]

    totals_query = (
        db.query(
            AccumulatorHistory.accumulator_id,
            func.sum(AccumulatorHistory.count).label('total_count')
        )
        .filter(
            AccumulatorHistory.accumulator_id.in_(accumulator_ids),
            AccumulatorHistory.user_id == user_id
        )
        .group_by(AccumulatorHistory.accumulator_id)
        .all()
    )
    totals_map = {row.accumulator_id: row.total_count or 0 for row in totals_query}

    all_sessions = (
        db.query(AccumulatorHistory)
        .filter(
            AccumulatorHistory.accumulator_id.in_(accumulator_ids),
            AccumulatorHistory.user_id == user_id
        )
        .order_by(AccumulatorHistory.created_at.desc())
        .all()
    )

    sessions_map: Dict[UUID, List[AccumulatorHistory]] = {}
    for session in all_sessions:
        if session.accumulator_id not in sessions_map:
            sessions_map[session.accumulator_id] = []
        sessions_map[session.accumulator_id].append(session)

    result = []
    for accumulator in accumulators:
        total_count = totals_map.get(accumulator.id, 0)
        sessions = sessions_map.get(accumulator.id, [])
        result.append((accumulator, total_count, sessions))

    return result, total


class GroupAccumulatorWithUserCount:
    """Data class for group accumulator with user's total count."""
    def __init__(
        self,
        group_accumulator: GroupAccumulator,
        user_total_count: int,
        is_joined: bool = False,
    ):
        self.group_accumulator = group_accumulator
        self.user_total_count = user_total_count
        self.is_joined = is_joined


def get_groups_by_accumulator_id(
    db: Session,
    accumulator_id: UUID,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20,
    joined_only: bool = False,
) -> Tuple[List[GroupAccumulatorWithUserCount], int]:
    """Get all groups using a specific accumulator with the user's total count for each.

    When joined_only is True, return only group accumulators the user has joined.
    """
    from pecha_api.plans.shared.event_linkage import (
        group_accumulator_not_linked_to_event,
    )

    query = db.query(GroupAccumulator).filter(
        GroupAccumulator.accumulator_id == accumulator_id,
        GroupAccumulator.deleted_at.is_(None),
        group_accumulator_not_linked_to_event(),
    )

    if joined_only:
        query = query.join(
            group_accumulator_joins,
            (GroupAccumulator.id == group_accumulator_joins.c.group_accumulator_id)
            & (group_accumulator_joins.c.user_id == user_id),
        )

    total = query.count()
    group_accumulators = query.order_by(GroupAccumulator.created_at.desc()).offset(skip).limit(limit).all()
    
    if not group_accumulators:
        return [], 0
    
    group_accumulator_ids = [ga.id for ga in group_accumulators]
    
    # Get user's total count for each group accumulator
    user_counts_query = (
        db.query(
            GroupAccumulatorHistory.group_accumulator_id,
            func.sum(GroupAccumulatorHistory.count).label('total_count')
        )
        .filter(
            GroupAccumulatorHistory.group_accumulator_id.in_(group_accumulator_ids),
            GroupAccumulatorHistory.user_id == user_id
        )
        .group_by(GroupAccumulatorHistory.group_accumulator_id)
        .all()
    )
    
    user_counts_map = {row.group_accumulator_id: int(row.total_count or 0) for row in user_counts_query}

    from pecha_api.group_accumulator.group_accumulator_repository import (
        get_joined_group_accumulator_ids_by_user,
    )

    joined_ids = set(
        get_joined_group_accumulator_ids_by_user(
            db=db,
            user_id=user_id,
            group_accumulator_ids=group_accumulator_ids,
        )
    )

    result = [
        GroupAccumulatorWithUserCount(
            group_accumulator=ga,
            user_total_count=user_counts_map.get(ga.id, 0),
            is_joined=ga.id in joined_ids,
        )
        for ga in group_accumulators
    ]
    
    return result, total
