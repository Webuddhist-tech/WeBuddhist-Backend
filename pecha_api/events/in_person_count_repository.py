from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from pecha_api.accumulator.group_accumulator_history_model import GroupAccumulatorHistory
from pecha_api.users.users_models import Users


def user_exists(db: Session, user_id: UUID) -> bool:
    return db.query(Users.id).filter(Users.id == user_id).first() is not None


def _rows(db: Session, group_accumulator_id: UUID, user_id: UUID):
    return db.query(GroupAccumulatorHistory).filter(
        GroupAccumulatorHistory.group_accumulator_id == group_accumulator_id,
        GroupAccumulatorHistory.user_id == user_id,
    )


def list_in_person_counts(
    db: Session,
    *,
    group_accumulator_id: UUID,
    user_id: UUID,
    skip: int,
    limit: int,
) -> Tuple[List[GroupAccumulatorHistory], int, int]:
    """One page of the user's rows, newest first, how many rows there are and
    the sum of their counts."""
    query = _rows(db, group_accumulator_id, user_id)
    total = query.count()
    total_count = (
        db.query(func.sum(GroupAccumulatorHistory.count))
        .filter(
            GroupAccumulatorHistory.group_accumulator_id == group_accumulator_id,
            GroupAccumulatorHistory.user_id == user_id,
        )
        .scalar()
    )
    rows = (
        query.order_by(GroupAccumulatorHistory.created_at.desc(), GroupAccumulatorHistory.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows, total, int(total_count or 0)


def get_in_person_count(
    db: Session, *, history_id: UUID, group_accumulator_id: UUID, user_id: UUID
) -> Optional[GroupAccumulatorHistory]:
    return _rows(db, group_accumulator_id, user_id).filter(GroupAccumulatorHistory.id == history_id).first()


def find_in_person_count_in_range(
    db: Session,
    *,
    group_accumulator_id: UUID,
    user_id: UUID,
    start_utc: datetime,
    end_utc: datetime,
    exclude_id: Optional[UUID] = None,
) -> Optional[GroupAccumulatorHistory]:
    query = _rows(db, group_accumulator_id, user_id).filter(
        GroupAccumulatorHistory.created_at >= start_utc,
        GroupAccumulatorHistory.created_at < end_utc,
    )
    if exclude_id is not None:
        query = query.filter(GroupAccumulatorHistory.id != exclude_id)
    return query.first()


def add_in_person_count(
    db: Session, *, group_accumulator_id: UUID, user_id: UUID, count: int, created_at: datetime
) -> GroupAccumulatorHistory:
    # No participation session: the in-person account never joins, so its
    # counts add to the group's total without listing it as a member.
    row = GroupAccumulatorHistory(
        group_accumulator_id=group_accumulator_id,
        user_id=user_id,
        count=count,
        user_group_accumulator_id=None,
        created_at=created_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def save_in_person_count(db: Session, row: GroupAccumulatorHistory) -> GroupAccumulatorHistory:
    db.commit()
    db.refresh(row)
    return row


def delete_in_person_count(db: Session, row: GroupAccumulatorHistory) -> None:
    db.delete(row)
    db.commit()
