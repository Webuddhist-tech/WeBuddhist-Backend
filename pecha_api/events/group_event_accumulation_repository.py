"""Sync event ↔ group accumulation junction rows with stable ids."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.accumulator.group_accumulator_models import GroupAccumulator

from .event_enums import EventAccumulationCountMode
from .group_event_accumulation_model import GroupEventAccumulation


@dataclass
class EventAccumulationSyncInput:
    group_accumulator_id: UUID
    event_format: str = "hybrid"
    display_order: int = 1
    count_mode: str = EventAccumulationCountMode.MANUAL_IN_PERSON.value
    id: Optional[UUID] = None
    client_key: Optional[str] = None
    parent_id: Optional[UUID] = None
    parent_client_key: Optional[str] = None


def list_accumulations_for_event(
    db: Session, event_id: UUID
) -> List[GroupEventAccumulation]:
    return (
        db.query(GroupEventAccumulation)
        .filter(GroupEventAccumulation.event_id == event_id)
        .order_by(GroupEventAccumulation.display_order.asc())
        .all()
    )


def list_accumulations_for_events(
    db: Session, event_ids: Sequence[UUID]
) -> Dict[UUID, List[GroupEventAccumulation]]:
    if not event_ids:
        return {}
    rows = (
        db.query(GroupEventAccumulation)
        .filter(GroupEventAccumulation.event_id.in_(event_ids))
        .order_by(
            GroupEventAccumulation.event_id.asc(),
            GroupEventAccumulation.display_order.asc(),
        )
        .all()
    )
    grouped: Dict[UUID, List[GroupEventAccumulation]] = {eid: [] for eid in event_ids}
    for row in rows:
        grouped.setdefault(row.event_id, []).append(row)
    return grouped


def get_accumulation_by_id(
    db: Session, *, event_id: UUID, accumulation_link_id: UUID
) -> Optional[GroupEventAccumulation]:
    return (
        db.query(GroupEventAccumulation)
        .filter(
            GroupEventAccumulation.id == accumulation_link_id,
            GroupEventAccumulation.event_id == event_id,
        )
        .first()
    )


def _validate_count_mode(value: str) -> None:
    try:
        EventAccumulationCountMode(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid count_mode '{value}'",
        ) from exc


def _validate_event_format(value: str) -> None:
    if value not in ("online", "offline", "hybrid"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event_format '{value}'",
        )


def _detect_cycles(parent_by_id: Dict[UUID, Optional[UUID]]) -> None:
    for node_id in parent_by_id:
        seen: Set[UUID] = set()
        current: Optional[UUID] = node_id
        while current is not None:
            if current in seen:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="EVENT_ACCUMULATION_CYCLE",
                )
            seen.add(current)
            current = parent_by_id.get(current)


def _validate_group_accumulator(
    db: Session, *, group_accumulator_id: UUID, group_id: UUID
) -> None:
    ga = (
        db.query(GroupAccumulator)
        .filter(
            GroupAccumulator.id == group_accumulator_id,
            GroupAccumulator.deleted_at.is_(None),
        )
        .first()
    )
    if ga is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Group accumulator '{group_accumulator_id}' not found",
        )
    if ga.group_id != group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Group accumulator '{group_accumulator_id}' does not belong "
                f"to the event's group"
            ),
        )


def sync_event_accumulations(
    db: Session,
    *,
    event_id: UUID,
    group_id: UUID,
    inputs: Sequence[EventAccumulationSyncInput],
) -> List[GroupEventAccumulation]:
    existing = list_accumulations_for_event(db, event_id)
    existing_by_id = {row.id: row for row in existing}
    existing_by_accumulator = {row.group_accumulator_id: row for row in existing}

    if not inputs:
        for row in existing:
            db.delete(row)
        db.flush()
        return []

    seen_ids: Set[UUID] = set()
    seen_accumulators: Set[UUID] = set()
    for item in inputs:
        _validate_event_format(item.event_format)
        _validate_count_mode(item.count_mode)
        _validate_group_accumulator(
            db, group_accumulator_id=item.group_accumulator_id, group_id=group_id
        )
        if item.id is not None:
            if item.id in seen_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Duplicate accumulation link id in request",
                )
            seen_ids.add(item.id)
            if item.id not in existing_by_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown accumulation link id '{item.id}' for this event",
                )
        if item.group_accumulator_id in seen_accumulators:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Duplicate group_accumulator_id in request",
            )
        seen_accumulators.add(item.group_accumulator_id)

    payload_ids: Set[UUID] = set()
    key_to_id: Dict[str, UUID] = {}
    id_to_row: Dict[UUID, GroupEventAccumulation] = {}
    resolved_parents: List[Tuple[UUID, EventAccumulationSyncInput]] = []

    for item in inputs:
        row: Optional[GroupEventAccumulation] = None
        if item.id is not None:
            row = existing_by_id[item.id]
        else:
            row = existing_by_accumulator.get(item.group_accumulator_id)

        if row is None:
            row = GroupEventAccumulation(
                id=uuid4(),
                event_id=event_id,
                group_accumulator_id=item.group_accumulator_id,
            )
            db.add(row)
        else:
            row.group_accumulator_id = item.group_accumulator_id

        row.event_format = item.event_format
        row.display_order = item.display_order
        row.count_mode = item.count_mode
        row.parent_id = None

        payload_ids.add(row.id)
        id_to_row[row.id] = row
        if item.client_key:
            key_to_id[item.client_key] = row.id
        resolved_parents.append((row.id, item))

    db.flush()

    parent_by_id: Dict[UUID, Optional[UUID]] = {}
    for row_id, item in resolved_parents:
        parent_id: Optional[UUID] = None
        if item.parent_client_key:
            parent_id = key_to_id.get(item.parent_client_key)
            if parent_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown parent_client_key '{item.parent_client_key}'",
                )
        elif item.parent_id is not None:
            if item.parent_id not in payload_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="parent_id must reference a link included in the same update",
                )
            parent_id = item.parent_id

        if parent_id == row_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Accumulation link cannot be its own parent",
            )
        parent_by_id[row_id] = parent_id

    _detect_cycles(parent_by_id)

    for row_id, parent_id in parent_by_id.items():
        id_to_row[row_id].parent_id = parent_id

    for row in existing:
        if row.id not in payload_ids:
            db.delete(row)

    db.flush()
    return list_accumulations_for_event(db, event_id)


def _set_legacy_manual_link_fields(link: GroupEventAccumulation, event_format: str) -> None:
    link.event_format = event_format
    link.count_mode = EventAccumulationCountMode.MANUAL_IN_PERSON.value


def _upsert_legacy_on_multi_link_event(
    db: Session,
    *,
    event_id: UUID,
    group_id: UUID,
    group_accumulator_id: UUID,
    event_format: str,
    existing: Sequence[GroupEventAccumulation],
    target: Optional[GroupEventAccumulation],
) -> None:
    if target is not None:
        _set_legacy_manual_link_fields(target, event_format)
        db.flush()
        return
    _validate_group_accumulator(
        db, group_accumulator_id=group_accumulator_id, group_id=group_id
    )
    _validate_event_format(event_format)
    db.add(
        GroupEventAccumulation(
            id=uuid4(),
            event_id=event_id,
            group_accumulator_id=group_accumulator_id,
            event_format=event_format,
            display_order=max(link.display_order for link in existing) + 1,
            count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
        )
    )
    db.flush()


def upsert_legacy_single_accumulation(
    db: Session,
    *,
    event_id: UUID,
    group_id: UUID,
    group_accumulator_id: UUID,
    event_format: str,
) -> None:
    """When CMS sends only group_accumulator_id, sync one junction row without
    removing other links on multi-accumulation events."""
    existing = list_accumulations_for_event(db, event_id)
    target = next((r for r in existing if r.group_accumulator_id == group_accumulator_id), None)

    if len(existing) > 1:
        _upsert_legacy_on_multi_link_event(
            db,
            event_id=event_id,
            group_id=group_id,
            group_accumulator_id=group_accumulator_id,
            event_format=event_format,
            existing=existing,
            target=target,
        )
        return

    if target is None and len(existing) == 1:
        target = existing[0]
    sync_event_accumulations(
        db,
        event_id=event_id,
        group_id=group_id,
        inputs=[
            EventAccumulationSyncInput(
                id=target.id if target else None,
                group_accumulator_id=group_accumulator_id,
                event_format=event_format,
                display_order=1,
                count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
            )
        ],
    )


def resolve_primary_group_accumulator_id(
    links: Sequence[GroupEventAccumulation],
) -> Optional[UUID]:
    if not links:
        return None
    roots = [link for link in links if link.parent_id is None]
    pool = roots if roots else list(links)
    manual_roots = [
        link
        for link in pool
        if link.count_mode == EventAccumulationCountMode.MANUAL_IN_PERSON.value
    ]
    candidates = manual_roots if manual_roots else pool
    chosen = min(candidates, key=lambda link: (link.display_order, str(link.id)))
    return chosen.group_accumulator_id
