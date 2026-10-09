"""Database-backed checks for event-linked group accumulator listing rules."""

from datetime import datetime, timedelta, timezone
from typing import Iterator
from uuid import UUID, uuid4

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
from pecha_api.events.event_metadata_model import EventMetadata
from pecha_api.events.event_model import Event
from pecha_api.events.group_event_accumulation_model import GroupEventAccumulation
from pecha_api.plans.groups.groups_enums import AuthorGroupStatus
from pecha_api.plans.groups.groups_models import AuthorGroup, AuthorGroupMetadata, author_group_joins
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
            EventMetadata.__table__,
            GroupEventAccumulation.__table__,
            AuthorGroup.__table__,
            AuthorGroupMetadata.__table__,
            author_group_joins,
        ],
    )
    # Only the columns the linked-content publication check reads. The real
    # tables carry Postgres-only indexes that SQLite cannot create.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE plans (id CHAR(32) PRIMARY KEY, status VARCHAR, "
            "deleted_at DATETIME, series_id CHAR(32))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE series (id CHAR(32) PRIMARY KEY, status VARCHAR, deleted_at DATETIME)"
        )
    return sessionmaker(bind=engine)


def _add_group_accumulator(
    db: Session, group_id: UUID, *, title: str
) -> GroupAccumulator:
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
    group_id: UUID,
    group_accumulator_id: UUID,
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


def test_joined_only_includes_event_linked_group_accumulator(
    listing_db: Session,
) -> None:
    preset_id = uuid4()
    group_id = uuid4()
    user_id = uuid4()
    linked = GroupAccumulator(
        id=uuid4(),
        group_id=group_id,
        accumulator_id=preset_id,
        title="Joined event accumulation",
        created_at=datetime.now(timezone.utc),
    )
    listing_db.add(linked)
    listing_db.commit()
    _add_event(
        listing_db,
        group_id=group_id,
        group_accumulator_id=linked.id,
    )
    listing_db.execute(
        group_accumulator_joins.insert().values(
            group_accumulator_id=linked.id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    listing_db.commit()

    discovery_rows, discovery_total = get_groups_by_accumulator_id(
        db=listing_db,
        accumulator_id=preset_id,
        user_id=user_id,
        joined_only=False,
    )
    joined_rows, joined_total = get_groups_by_accumulator_id(
        db=listing_db,
        accumulator_id=preset_id,
        user_id=user_id,
        joined_only=True,
    )

    assert discovery_total == 0
    assert discovery_rows == []
    assert joined_total == 1
    assert joined_rows[0].group_accumulator.id == linked.id


def _add_history(
    db: Session, *, group_accumulator_id: UUID, user_id: UUID, count: int
) -> None:
    db.add(
        GroupAccumulatorHistory(
            id=uuid4(),
            group_accumulator_id=group_accumulator_id,
            user_id=user_id,
            count=count,
        )
    )
    db.commit()


def test_groups_by_accumulator_returns_user_and_group_totals(
    listing_db: Session,
) -> None:
    preset_id = uuid4()
    user_id = uuid4()
    other_user_id = uuid4()
    with_history = GroupAccumulator(
        id=uuid4(),
        group_id=uuid4(),
        accumulator_id=preset_id,
        title="Has history",
        created_at=datetime.now(timezone.utc),
    )
    others_only = GroupAccumulator(
        id=uuid4(),
        group_id=uuid4(),
        accumulator_id=preset_id,
        title="Only other members",
        created_at=datetime.now(timezone.utc),
    )
    no_history = GroupAccumulator(
        id=uuid4(),
        group_id=uuid4(),
        accumulator_id=preset_id,
        title="No history",
        created_at=datetime.now(timezone.utc),
    )
    listing_db.add_all([with_history, others_only, no_history])
    listing_db.commit()

    _add_history(listing_db, group_accumulator_id=with_history.id, user_id=user_id, count=100)
    _add_history(listing_db, group_accumulator_id=with_history.id, user_id=user_id, count=8)
    _add_history(listing_db, group_accumulator_id=with_history.id, user_id=other_user_id, count=500)
    _add_history(listing_db, group_accumulator_id=others_only.id, user_id=other_user_id, count=21)

    rows, total = get_groups_by_accumulator_id(
        db=listing_db,
        accumulator_id=preset_id,
        user_id=user_id,
    )

    by_id = {row.group_accumulator.id: row for row in rows}
    assert total == 3
    assert by_id[with_history.id].user_total_count == 108
    assert by_id[with_history.id].group_total_count == 608
    assert by_id[others_only.id].user_total_count == 0
    assert by_id[others_only.id].group_total_count == 21
    assert by_id[no_history.id].user_total_count == 0
    assert by_id[no_history.id].group_total_count == 0


def _add_group(
    db: Session,
    *,
    slug: str,
    titles: dict,
    status: AuthorGroupStatus = AuthorGroupStatus.PUBLISHED,
    is_public: bool = True,
) -> AuthorGroup:
    group = AuthorGroup(
        id=uuid4(), slug=slug, status=status, is_public=is_public, created_by="author@example.com"
    )
    db.add(group)
    for language, title in titles.items():
        db.add(AuthorGroupMetadata(id=uuid4(), group_id=group.id, language=language, title=title))
    db.commit()
    return group


def _add_event_metadata(db: Session, *, event_id: UUID, names: dict) -> None:
    for language, name in names.items():
        db.add(EventMetadata(id=uuid4(), event_id=event_id, language=language, name=name))
    db.commit()


def _join(db: Session, *, group_accumulator_id: UUID, user_id: UUID) -> None:
    db.execute(
        group_accumulator_joins.insert().values(
            group_accumulator_id=group_accumulator_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def test_accumulator_groups_service_returns_group_name_and_event_title(
    listing_db: Session,
) -> None:
    from unittest.mock import MagicMock, patch

    from pecha_api.accumulator.accumulator_service import get_accumulator_groups_service

    preset_id = uuid4()
    user_id = uuid4()
    sangha = _add_group(listing_db, slug="sangha-circle", titles={"EN": "Sangha Circle", "BO": "དགེ་འདུན"})
    untitled = _add_group(listing_db, slug="untitled-group", titles={})
    other = _add_group(listing_db, slug="other-group", titles={"EN": "Other Group"})
    draft = _add_group(
        listing_db, slug="draft-group", titles={"EN": "Draft Group"}, status=AuthorGroupStatus.DRAFT
    )

    event_linked = GroupAccumulator(
        id=uuid4(),
        group_id=sangha.id,
        accumulator_id=preset_id,
        title="Retreat accumulation",
        created_at=datetime.now(timezone.utc),
    )
    standalone = GroupAccumulator(
        id=uuid4(),
        group_id=untitled.id,
        accumulator_id=preset_id,
        title="Standalone accumulation",
        created_at=datetime.now(timezone.utc),
    )
    in_draft_group = GroupAccumulator(
        id=uuid4(),
        group_id=draft.id,
        accumulator_id=preset_id,
        title="Draft accumulation",
        created_at=datetime.now(timezone.utc),
    )
    listing_db.add_all([event_linked, standalone, in_draft_group])
    listing_db.commit()
    for ga in (event_linked, standalone, in_draft_group):
        _join(listing_db, group_accumulator_id=ga.id, user_id=user_id)

    # Only the most recently created linked event is used.
    earlier = _add_event(listing_db, group_id=sangha.id, group_accumulator_id=event_linked.id)
    earlier.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    _add_event_metadata(listing_db, event_id=earlier.id, names={"EN": "Last year's retreat"})
    retreat = _add_event(listing_db, group_id=sangha.id, group_accumulator_id=event_linked.id)
    retreat.created_at = datetime.now(timezone.utc)
    listing_db.commit()
    _add_event_metadata(listing_db, event_id=retreat.id, names={"EN": "Saga Dawa Retreat", "BO": "ས་ག་ཟླ་བ"})
    draft_event = _add_event(listing_db, group_id=draft.id, group_accumulator_id=in_draft_group.id)
    _add_event_metadata(listing_db, event_id=draft_event.id, names={"EN": "Draft event"})
    # An event in another group does not link this group accumulator.
    foreign = _add_event(listing_db, group_id=other.id, group_accumulator_id=standalone.id)
    _add_event_metadata(listing_db, event_id=foreign.id, names={"EN": "Other group event"})

    def run(language):
        with patch(
            "pecha_api.accumulator.accumulator_service.SessionLocal",
            return_value=MagicMock(__enter__=MagicMock(return_value=listing_db), __exit__=MagicMock(return_value=False)),
        ), patch(
            "pecha_api.accumulator.accumulator_service.validate_and_extract_user_details",
            return_value=MagicMock(id=user_id),
        ), patch(
            "pecha_api.accumulator.accumulator_service.get_accumulator_by_id",
            return_value=MagicMock(),
        ):
            response = get_accumulator_groups_service(
                token="token",
                accumulator_id=preset_id,
                joined_only=True,
                language=language,
            )
        return {group.group_accumulator_id: group for group in response.groups}

    default = run(None)
    assert default[event_linked.id].group_name == "Sangha Circle"
    assert default[event_linked.id].event_title == "Saga Dawa Retreat"
    assert default[standalone.id].group_name == "untitled-group"
    assert default[standalone.id].event_title is None
    # Unpublished groups never reach the app, so their names stay hidden.
    assert default[in_draft_group.id].group_name is None
    assert default[in_draft_group.id].event_title is None

    tibetan = run("bo")
    assert tibetan[event_linked.id].group_name == "དགེ་འདུན"
    assert tibetan[event_linked.id].event_title == "ས་ག་ཟླ་བ"

    # No Chinese metadata: falls back to English.
    chinese = run("zh")
    assert chinese[event_linked.id].group_name == "Sangha Circle"
    assert chinese[event_linked.id].event_title == "Saga Dawa Retreat"


def _groups_service_response(
    listing_db: Session, preset_id: UUID, user_id: UUID, joined_only: bool = False
):
    from unittest.mock import MagicMock, patch

    from pecha_api.accumulator.accumulator_service import get_accumulator_groups_service

    with patch(
        "pecha_api.accumulator.accumulator_service.SessionLocal",
        return_value=MagicMock(__enter__=MagicMock(return_value=listing_db), __exit__=MagicMock(return_value=False)),
    ), patch(
        "pecha_api.accumulator.accumulator_service.validate_and_extract_user_details",
        return_value=MagicMock(id=user_id),
    ), patch(
        "pecha_api.accumulator.accumulator_service.get_accumulator_by_id",
        return_value=MagicMock(),
    ):
        response = get_accumulator_groups_service(
            token="token", accumulator_id=preset_id, joined_only=joined_only
        )
    return {group.group_accumulator_id: group for group in response.groups}


def test_private_group_name_hidden_until_the_user_joins_the_group(
    listing_db: Session,
) -> None:
    preset_id = uuid4()
    user_id = uuid4()
    private = _add_group(listing_db, slug="private-circle", titles={"EN": "Private Circle"}, is_public=False)
    row = GroupAccumulator(
        id=uuid4(), group_id=private.id, accumulator_id=preset_id,
        title="Private accumulation", created_at=datetime.now(timezone.utc),
    )
    listing_db.add(row)
    listing_db.commit()

    outsider_view = _groups_service_response(listing_db, preset_id, user_id)
    assert outsider_view[row.id].group_name is None

    listing_db.execute(
        author_group_joins.insert().values(
            group_id=private.id, user_id=user_id, created_at=datetime.now(timezone.utc)
        )
    )
    listing_db.commit()

    member_view = _groups_service_response(listing_db, preset_id, user_id)
    assert member_view[row.id].group_name == "Private Circle"


def test_event_title_skips_events_linked_to_unpublished_plans(listing_db: Session) -> None:
    preset_id = uuid4()
    user_id = uuid4()
    group = _add_group(listing_db, slug="open-circle", titles={"EN": "Open Circle"})
    row = GroupAccumulator(
        id=uuid4(), group_id=group.id, accumulator_id=preset_id,
        title="Linked accumulation", created_at=datetime.now(timezone.utc),
    )
    listing_db.add(row)
    listing_db.commit()
    _join(listing_db, group_accumulator_id=row.id, user_id=user_id)

    published = _add_event(listing_db, group_id=group.id, group_accumulator_id=row.id)
    published.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    _add_event_metadata(listing_db, event_id=published.id, names={"EN": "Visible event"})

    draft_plan_id = uuid4()
    listing_db.execute(
        __import__("sqlalchemy").text("INSERT INTO plans (id, status) VALUES (:id, 'DRAFT')"),
        {"id": draft_plan_id.hex},
    )
    newest = _add_event(listing_db, group_id=group.id, group_accumulator_id=row.id)
    newest.plan_id = draft_plan_id
    newest.created_at = datetime.now(timezone.utc)
    listing_db.commit()
    _add_event_metadata(listing_db, event_id=newest.id, names={"EN": "Hidden draft event"})

    response = _groups_service_response(listing_db, preset_id, user_id, joined_only=True)

    assert response[row.id].event_title == "Visible event"
