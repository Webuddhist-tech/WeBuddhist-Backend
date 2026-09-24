"""Database-backed checks for event-linked group accumulator listing rules."""

from datetime import datetime, timezone
from typing import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pecha_api.accumulator.accumulator_models import Accumulator
from pecha_api.accumulator.group_accumulator_history_model import GroupAccumulatorHistory
from pecha_api.accumulator.group_accumulator_join_model import group_accumulator_joins
from pecha_api.accumulator.group_accumulator_link_model import GroupAccumulatorLink
from pecha_api.accumulator.group_accumulator_metadata_model import GroupAccumulatorMetadata
from pecha_api.accumulator.group_accumulator_models import GroupAccumulator
from pecha_api.db.database import Base
from pecha_api.events.event_model import Event
from pecha_api.group_accumulator.group_accumulator_repository import (
    get_group_accumulators,
    get_group_accumulators_for_group_ids,
)
from pecha_api.accumulator.accumulator_repository import get_groups_by_accumulator_id
from pecha_api.plans.tasks.plan_tasks_models import PlanTask  # noqa: F401
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask  # noqa: F401


def _sessionmaker() -> sessionmaker:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Accumulator.__table__,
            GroupAccumulator.__table__,
            GroupAccumulatorMetadata.__table__,
            GroupAccumulatorLink.__table__,
            GroupAccumulatorHistory.__table__,
            group_accumulator_joins,
            Event.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _add_group_accumulator(db: Session, group_id, *, title: str) -> GroupAccumulator:
    row = GroupAccumulator(
        id=uuid4(),
        group_id=group_id,
        title=title,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return row


def _add_event(
    db: Session,
    *,
    group_id,
    group_accumulator_id,
) -> Event:
    now = datetime.now(timezone.utc)
    event = Event(
        id=uuid4(),
        group_id=group_id,
        group_accumulator_id=group_accumulator_id,
        start_date=now,
        end_date=now,
        created_by="author@example.com",
    )
    db.add(event)
    db.commit()
    return event


@pytest.fixture
def listing_db() -> Iterator[Session]:
    db = _sessionmaker()()
    yield db
    db.close()


def test_public_listing_excludes_same_group_event_linked_accumulator(
    listing_db: Session,
) -> None:
    group_id = uuid4()
    linked = _add_group_accumulator(listing_db, group_id, title="Event-only")
    standalone = _add_group_accumulator(listing_db, group_id, title="Browse")
    _add_event(
        listing_db,
        group_id=group_id,
        group_accumulator_id=linked.id,
    )

    public_rows, public_total = get_group_accumulators(
        listing_db,
        group_id=group_id,
        exclude_event_linked=True,
    )
    all_rows, all_total = get_group_accumulators(
        listing_db,
        group_id=group_id,
        exclude_event_linked=False,
    )
    feed_rows, feed_total = get_group_accumulators_for_group_ids(
        listing_db,
        group_ids=[group_id],
        limit=20,
    )

    assert public_total == 1
    assert [row.id for row in public_rows] == [standalone.id]
    assert all_total == 2
    assert {row.id for row in all_rows} == {linked.id, standalone.id}
    assert feed_total == 1
    assert [row.id for row in feed_rows] == [standalone.id]


def test_cross_group_event_link_does_not_hide_accumulator(listing_db: Session) -> None:
    owner_group = uuid4()
    other_group = uuid4()
    accumulation = _add_group_accumulator(
        listing_db, owner_group, title="Still browsable"
    )
    _add_event(
        listing_db,
        group_id=other_group,
        group_accumulator_id=accumulation.id,
    )

    rows, total = get_group_accumulators(
        listing_db,
        group_id=owner_group,
        exclude_event_linked=True,
    )

    assert total == 1
    assert rows[0].id == accumulation.id


def test_accumulator_groups_route_hides_same_group_event_linked(
    listing_db: Session,
) -> None:
    preset_id = uuid4()
    group_id = uuid4()
    linked = GroupAccumulator(
        id=uuid4(),
        group_id=group_id,
        accumulator_id=preset_id,
        title="Linked",
        created_at=datetime.now(timezone.utc),
    )
    visible = GroupAccumulator(
        id=uuid4(),
        group_id=group_id,
        accumulator_id=preset_id,
        title="Visible",
        created_at=datetime.now(timezone.utc),
    )
    listing_db.add_all([linked, visible])
    listing_db.commit()
    _add_event(
        listing_db,
        group_id=group_id,
        group_accumulator_id=linked.id,
    )

    rows, total = get_groups_by_accumulator_id(
        db=listing_db,
        accumulator_id=preset_id,
        user_id=uuid4(),
        skip=0,
        limit=20,
    )

    assert total == 1
    assert rows[0].group_accumulator.id == visible.id
