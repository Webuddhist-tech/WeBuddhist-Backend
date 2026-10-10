from typing import Callable, List, Optional, Tuple

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.orm import Session

from pecha_api.accumulator.accumulator_models import Accumulator
from pecha_api.bookmarks.bookmark_enums import BookmarkType
from pecha_api.bookmarks.bookmark_models import Bookmark
from pecha_api.group_recitation_collection.models import GroupRecitationCollectionItem
from pecha_api.plans.tags.tag_model import tag_segments
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask
from pecha_api.plans.users.recitation.user_recitations_models import UserRecitations
from pecha_api.plans.users.recitation_collection.recitation_collection_models import (
    RecitationCollectionItem,
)
from pecha_api.routines.routines_enums import SessionType
from pecha_api.routines.routines_models import RoutineSession
from pecha_api.texts.text_images_models import TextImage


def _conflict_aware_update(
    db: Session,
    table,
    id_column: str,
    owner_columns: List[str],
    old_value,
    new_value,
    extra_where: Optional[Callable] = None,
) -> Tuple[int, List[dict]]:
    """Rename `id_column` from old_value to new_value on rows of `table`,
    skipping any row whose (owner_columns..., new_value) already exists
    elsewhere, which would otherwise violate a unique constraint."""
    id_col = table.c[id_column]
    owner_cols = [table.c[c] for c in owner_columns]
    other = table.alias()

    conflict_conditions = [other.c[c] == table.c[c] for c in owner_columns]
    conflict_conditions.append(other.c[id_column] == new_value)
    if extra_where is not None:
        conflict_conditions.append(extra_where(other))
    conflict_exists = exists(select(1).select_from(other).where(and_(*conflict_conditions)))

    base_where = [id_col == old_value]
    if extra_where is not None:
        base_where.append(extra_where(table))

    skipped_rows = db.execute(select(*owner_cols).where(and_(*base_where, conflict_exists))).all()
    skipped = [
        {owner_columns[i]: str(row[i]) for i in range(len(owner_columns))} for row in skipped_rows
    ]

    result = db.execute(
        update(table).where(and_(*base_where, ~conflict_exists)).values(**{id_column: new_value})
    )
    return result.rowcount, skipped


def remap_segment_ids(
    db: Session, old_segment_id: str, new_segment_id: str
) -> Tuple[dict, List[dict]]:
    updated: dict = {}
    skipped: List[dict] = []

    # segment_ids holds both internal Segment UUIDs and external pecha-style
    # ids as plain strings, so this replace runs unconditionally.
    result = db.execute(
        update(PlanSubTask)
        .where(PlanSubTask.segment_ids.any(old_segment_id))
        .values(
            segment_ids=func.array_replace(
                PlanSubTask.segment_ids,
                old_segment_id,
                new_segment_id,
            )
        )
    )
    updated["sub_tasks.segment_ids"] = result.rowcount

    # tag_segments.segment_id is a string too (Mongo UUIDs and OpenPecha ids).
    count, conflicts = _conflict_aware_update(
        db=db,
        table=tag_segments,
        id_column="segment_id",
        owner_columns=["tag_id", "language"],
        old_value=old_segment_id,
        new_value=new_segment_id,
    )
    updated["tag_segments"] = count
    skipped.extend(
        {"table": "tag_segments", "reason": "duplicate (tag_id, segment_id, language)", "detail": d}
        for d in conflicts
    )

    count, conflicts = _conflict_aware_update(
        db=db,
        table=Bookmark.__table__,
        id_column="source_id",
        owner_columns=["user_id"],
        old_value=old_segment_id,
        new_value=new_segment_id,
        extra_where=lambda t: t.c.type == BookmarkType.VERSE,
    )
    updated["bookmarks(VERSE)"] = count
    skipped.extend(
        {"table": "bookmarks", "reason": "duplicate (user_id, type, source_id)", "detail": d}
        for d in conflicts
    )

    return updated, skipped


def remap_text_ids(db: Session, old_text_id: str, new_text_id: str) -> Tuple[dict, List[dict]]:
    """Every text_id-holding column is a plain string now, so this replace
    runs unconditionally regardless of whether old/new_text_id are UUIDs."""
    updated: dict = {}
    skipped: List[dict] = []

    result = db.execute(
        update(Accumulator).where(Accumulator.text_id == old_text_id).values(text_id=new_text_id)
    )
    updated["accumulators.text_id"] = result.rowcount

    result = db.execute(
        update(PlanSubTask)
        .where(PlanSubTask.source_text_id == old_text_id)
        .values(source_text_id=new_text_id)
    )
    updated["sub_tasks.source_text_id"] = result.rowcount

    result = db.execute(
        update(TextImage).where(TextImage.text_id == old_text_id).values(text_id=new_text_id)
    )
    updated["text_images.text_id"] = result.rowcount

    result = db.execute(
        update(RoutineSession)
        .where(RoutineSession.session_type == SessionType.RECITATION)
        .where(RoutineSession.source_id == old_text_id)
        .values(source_id=new_text_id)
    )
    updated["routine_sessions.source_id"] = result.rowcount

    count, conflicts = _conflict_aware_update(
        db=db,
        table=UserRecitations.__table__,
        id_column="text_id",
        owner_columns=["user_id"],
        old_value=old_text_id,
        new_value=new_text_id,
    )
    updated["user_recitations"] = count
    skipped.extend(
        {"table": "user_recitations", "reason": "duplicate (user_id, text_id)", "detail": d}
        for d in conflicts
    )

    count, conflicts = _conflict_aware_update(
        db=db,
        table=RecitationCollectionItem.__table__,
        id_column="text_id",
        owner_columns=["recitation_collection_id"],
        old_value=old_text_id,
        new_value=new_text_id,
    )
    updated["recitation_collection_items"] = count
    skipped.extend(
        {
            "table": "recitation_collection_items",
            "reason": "duplicate (recitation_collection_id, text_id)",
            "detail": d,
        }
        for d in conflicts
    )

    # The unique index on group_recitation_collection_items only applies to
    # non-deleted rows, so soft-deleted rows can be renamed unconditionally.
    result = db.execute(
        update(GroupRecitationCollectionItem)
        .where(GroupRecitationCollectionItem.text_id == old_text_id)
        .where(GroupRecitationCollectionItem.deleted_at.isnot(None))
        .values(text_id=new_text_id)
    )
    deleted_row_count = result.rowcount

    count, conflicts = _conflict_aware_update(
        db=db,
        table=GroupRecitationCollectionItem.__table__,
        id_column="text_id",
        owner_columns=["group_recitation_collection_id"],
        old_value=old_text_id,
        new_value=new_text_id,
        extra_where=lambda t: t.c.deleted_at.is_(None),
    )
    updated["group_recitation_collection_items"] = count + deleted_row_count
    skipped.extend(
        {
            "table": "group_recitation_collection_items",
            "reason": "duplicate (group_recitation_collection_id, text_id)",
            "detail": d,
        }
        for d in conflicts
    )

    count, conflicts = _conflict_aware_update(
        db=db,
        table=Bookmark.__table__,
        id_column="source_id",
        owner_columns=["user_id"],
        old_value=old_text_id,
        new_value=new_text_id,
        extra_where=lambda t: t.c.type == BookmarkType.TEXT,
    )
    updated["bookmarks(TEXT)"] = count
    skipped.extend(
        {"table": "bookmarks", "reason": "duplicate (user_id, type, source_id)", "detail": d}
        for d in conflicts
    )

    return updated, skipped
