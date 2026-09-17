"""Plans merged into an event must not surface in the public listing APIs.

- ``GET /series`` and ``GET /series/featured`` drop a series when any of its
  plans is linked to an event.
- ``GET /author/groups/practices`` drops those series and event-linked
  standalone plans.
- ``GET /author/groups/feeds`` drops events that link a plan.

The queries are compiled rather than executed: the gates are a SQL concern, and
compiling them needs no database.
"""

import uuid

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
EVENT_PLAN_GATE = "events.plan_id IS NULL"


class _CapturingQuery(Query):
    """Records the SQL of every query the repository runs, then short-circuits."""

    captured: list = []

    def _capture(self):
        sql = str(self.statement.compile(dialect=postgresql.dialect()))
        _CapturingQuery.captured.append(sql.replace("\n", " "))

    def all(self):
        self._capture()
        return []

    def first(self):
        self._capture()
        return None

    def scalar(self):
        self._capture()
        return 0

    def count(self):
        self._capture()
        return 0


@pytest.fixture
def db():
    _CapturingQuery.captured = []
    # Unbound: nothing is executed, the statements are only compiled.
    session = Session(query_cls=_CapturingQuery)
    yield session
    session.close()


def _sql(db) -> str:
    assert _CapturingQuery.captured, "repository built no query"
    return " ".join(_CapturingQuery.captured)


@pytest.mark.parametrize(
    "name,run",
    [
        (
            "GET /series",
            lambda db: get_series_paginated(
                db=db, search=None, skip=0, limit=10, exclude_event_linked=True
            ),
        ),
        ("GET /series/featured", lambda db: get_random_featured_published_series(db=db)),
        (
            "GET /author/groups/practices series",
            lambda db: get_series_for_group_ids(db=db, group_ids=[uuid.uuid4()], limit=20),
        ),
        (
            "GET /author/groups/practices plans",
            lambda db: get_standalone_plans_for_group_ids(
                db=db, group_ids=[uuid.uuid4()], limit=20
            ),
        ),
    ],
)
def test_public_series_and_practice_listings_exclude_event_linked_plans(db, name, run):
    run(db)

    for sql in _CapturingQuery.captured:
        assert PLAN_EVENT_GATE in sql, f"{name} is missing the event gate: {sql}"


def test_cms_series_listing_keeps_event_linked_series(db):
    get_series_paginated(db=db, search=None, skip=0, limit=10)

    assert "events.plan_id" not in _sql(db)


def test_feed_events_exclude_plan_linked_events(db):
    get_events(
        db=db,
        restrict_group_ids=[uuid.uuid4()],
        limit=20,
        should_sort_newest_first=True,
        exclude_plan_linked=True,
    )

    # Both the count and the page query carry the gate, so the total matches.
    assert len(_CapturingQuery.captured) == 2
    for sql in _CapturingQuery.captured:
        assert EVENT_PLAN_GATE in sql


def test_feed_recurring_events_exclude_plan_linked_events(db):
    get_recurring_events(db=db, restrict_group_ids=[uuid.uuid4()], exclude_plan_linked=True)

    assert EVENT_PLAN_GATE in _sql(db)


def test_event_listings_keep_plan_linked_events_by_default(db):
    get_events(db=db, restrict_group_ids=[uuid.uuid4()])
    get_recurring_events(db=db, restrict_group_ids=[uuid.uuid4()])

    assert EVENT_PLAN_GATE not in _sql(db)
