"""Plans merged into an event must not surface in the public listing APIs.

- ``GET /series`` and ``GET /series/featured`` drop a series when an event
  links it directly or links any of its plans.
- ``GET /author/groups/practices`` drops those series and event-linked
  standalone plans.
- ``GET /author/groups/feeds`` drops events that link a plan or a series.

The queries are compiled rather than executed: the gates are a SQL concern, and
compiling them needs no database.
"""

import uuid
from typing import Callable, Iterator, List, Optional, Tuple

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Query, Session

import pecha_api.app  # noqa: F401  -- registers every mapper
from pecha_api.events.event_repository import get_events, get_recurring_events
from pecha_api.plans.groups.groups_repository import (
    get_series_for_group_ids,
    get_standalone_plans_for_group_ids,
)
from pecha_api.plans.series.series_repository import (
    get_random_featured_published_series,
    get_series_paginated,
)

PLAN_EVENT_GATE = "events.plan_id = plans.id"
SERIES_EVENT_GATE = "events.series_id = series.id"
EVENT_PLAN_GATE = "events.plan_id IS NULL"
EVENT_SERIES_GATE = "events.series_id IS NULL"


class _CapturingQuery(Query):
    """Records the SQL of every query the repository runs, then short-circuits."""

    captured: List[str] = []

    def _capture(self) -> None:
        sql = str(self.statement.compile(dialect=postgresql.dialect()))
        _CapturingQuery.captured.append(sql.replace("\n", " "))

    def all(self) -> list:
        self._capture()
        return []

    def first(self) -> Optional[object]:
        self._capture()
        return None

    def scalar(self) -> int:
        self._capture()
        return 0

    def count(self) -> int:
        self._capture()
        return 0


@pytest.fixture
def db() -> Iterator[Session]:
    _CapturingQuery.captured = []
    # Unbound: nothing is executed, the statements are only compiled.
    session = Session(query_cls=_CapturingQuery)
    yield session
    session.close()


def _sql(db: Session) -> str:
    assert _CapturingQuery.captured, "repository built no query"
    return " ".join(_CapturingQuery.captured)


@pytest.mark.parametrize(
    "name,run,gates",
    [
        (
            "GET /series",
            lambda db: get_series_paginated(
                db=db, search=None, skip=0, limit=10, exclude_event_linked=True
            ),
            (PLAN_EVENT_GATE, SERIES_EVENT_GATE),
        ),
        (
            "GET /series/featured",
            lambda db: get_random_featured_published_series(db=db),
            (PLAN_EVENT_GATE, SERIES_EVENT_GATE),
        ),
        (
            "GET /author/groups/practices series",
            lambda db: get_series_for_group_ids(db=db, group_ids=[uuid.uuid4()], limit=20),
            (PLAN_EVENT_GATE, SERIES_EVENT_GATE),
        ),
        (
            "GET /author/groups/practices plans",
            lambda db: get_standalone_plans_for_group_ids(
                db=db, group_ids=[uuid.uuid4()], limit=20
            ),
            (PLAN_EVENT_GATE,),
        ),
    ],
)
def test_public_series_and_practice_listings_exclude_event_linked_content(
    db: Session,
    name: str,
    run: Callable[[Session], object],
    gates: Tuple[str, ...],
) -> None:
    run(db)

    for sql in _CapturingQuery.captured:
        for gate in gates:
            assert gate in sql, f"{name} is missing {gate!r}: {sql}"


def test_cms_series_listing_keeps_event_linked_series(db: Session) -> None:
    get_series_paginated(db=db, search=None, skip=0, limit=10)

    sql = _sql(db)
    assert "events.plan_id" not in sql
    assert "events.series_id" not in sql


def test_feed_events_exclude_plan_or_series_linked_events(db: Session) -> None:
    get_events(
        db=db,
        restrict_group_ids=[uuid.uuid4()],
        limit=20,
        should_sort_newest_first=True,
        exclude_plan_or_series_linked=True,
    )

    # Both the count and the page query carry the gate, so the total matches.
    assert len(_CapturingQuery.captured) == 2
    for sql in _CapturingQuery.captured:
        assert EVENT_PLAN_GATE in sql
        assert EVENT_SERIES_GATE in sql


def test_feed_recurring_events_exclude_plan_or_series_linked_events(db: Session) -> None:
    get_recurring_events(
        db=db, restrict_group_ids=[uuid.uuid4()], exclude_plan_or_series_linked=True
    )

    sql = _sql(db)
    assert EVENT_PLAN_GATE in sql
    assert EVENT_SERIES_GATE in sql


def test_event_listings_keep_plan_or_series_linked_events_by_default(db: Session) -> None:
    get_events(db=db, restrict_group_ids=[uuid.uuid4()])
    get_recurring_events(db=db, restrict_group_ids=[uuid.uuid4()])

    sql = _sql(db)
    assert EVENT_PLAN_GATE not in sql
    assert EVENT_SERIES_GATE not in sql
