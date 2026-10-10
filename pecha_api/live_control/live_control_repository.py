"""Reads and writes for live control settings.

None of these commit; callers own the transaction boundary."""

from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .live_control_models import (
    EventLiveController,
    EventLiveSectionOrder,
    EventLiveSettings,
    LiveEditionSettings,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Edition settings ------------------------------------------------------


def get_edition_settings(db: Session, edition_id: str) -> Optional[LiveEditionSettings]:
    return db.get(LiveEditionSettings, edition_id)


def get_edition_settings_many(
    db: Session, edition_ids: Iterable[str]
) -> Dict[str, LiveEditionSettings]:
    ids = list(dict.fromkeys(edition_ids))
    if not ids:
        return {}
    rows = db.execute(
        select(LiveEditionSettings).where(LiveEditionSettings.edition_id.in_(ids))
    ).scalars()
    return {row.edition_id: row for row in rows}


def upsert_edition_settings(
    db: Session,
    edition_id: str,
    lists: Dict[str, list],
    updated_by: Optional[str],
) -> None:
    """Writes the given lists whole; a list not in `lists` is left as it is."""
    values = {"edition_id": edition_id, "updated_at": _now(), "updated_by": updated_by, **lists}
    stmt = insert(LiveEditionSettings).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["edition_id"],
        set_={key: stmt.excluded[key] for key in values if key != "edition_id"},
    )
    db.execute(stmt)


# --- Event settings --------------------------------------------------------


def get_event_settings(db: Session, event_id: UUID) -> Optional[EventLiveSettings]:
    return db.get(EventLiveSettings, event_id)


def upsert_event_settings(
    db: Session, event_id: UUID, fields: Dict[str, object], updated_by: Optional[str]
) -> None:
    values = {"event_id": event_id, "updated_at": _now(), "updated_by": updated_by, **fields}
    stmt = insert(EventLiveSettings).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["event_id"],
        set_={key: stmt.excluded[key] for key in values if key != "event_id"},
    )
    db.execute(stmt)


# --- Controllers -----------------------------------------------------------


def list_controllers(db: Session, event_id: UUID) -> List[EventLiveController]:
    return list(
        db.execute(
            select(EventLiveController)
            .where(EventLiveController.event_id == event_id)
            .order_by(EventLiveController.created_at)
        ).scalars()
    )


def get_controller(db: Session, event_id: UUID, controller_id: UUID) -> Optional[EventLiveController]:
    controller = db.get(EventLiveController, controller_id)
    if controller is None or controller.event_id != event_id:
        return None
    return controller


def get_controller_by_token_hash(db: Session, token_hash: str) -> Optional[EventLiveController]:
    return db.execute(
        select(EventLiveController).where(EventLiveController.token_hash == token_hash)
    ).scalar_one_or_none()


def token_hash_taken(db: Session, token_hash: str) -> bool:
    return get_controller_by_token_hash(db, token_hash) is not None


def add_controller(db: Session, controller: EventLiveController) -> EventLiveController:
    db.add(controller)
    db.flush()
    return controller


# --- Section order ---------------------------------------------------------


def get_section_order(db: Session, event_id: UUID, edition_id: str) -> Optional[EventLiveSectionOrder]:
    return db.get(EventLiveSectionOrder, (event_id, edition_id))


def set_section_order(db: Session, event_id: UUID, edition_id: str, section_ids: List[str]) -> None:
    """An empty list removes the row: the table of contents' own order again."""
    existing = get_section_order(db, event_id, edition_id)
    if not section_ids:
        if existing is not None:
            db.delete(existing)
        return
    stmt = insert(EventLiveSectionOrder).values(
        event_id=event_id, edition_id=edition_id, section_ids=section_ids, updated_at=_now()
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["event_id", "edition_id"],
        set_={"section_ids": stmt.excluded.section_ids, "updated_at": stmt.excluded.updated_at},
    )
    db.execute(stmt)
