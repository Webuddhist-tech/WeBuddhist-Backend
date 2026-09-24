"""Visibility rule for plans, series, and group accumulators merged into an event.

A plan, series, or group accumulation an event points at
(``events.plan_id`` / ``events.series_id`` / ``events.group_accumulator_id``)
is event content: it is reached through the event, which hands clients its id.
It must not surface on its own in the public browse/discovery listings, so it
stays fetchable by id while disappearing from every "here are the plans"
surface.
"""

from sqlalchemy import ColumnElement, and_, column, exists, select, table

from pecha_api.plans.plans_models import Plan
from pecha_api.plans.series.series_model import Series

# A lightweight table construct rather than an import of
# ``pecha_api.events.Event``: ``pecha_api.events.__init__`` pulls in the event
# service, which imports back into ``pecha_api.plans`` -- importing the model
# here would close that cycle.
_events = table(
    "events",
    column("plan_id"),
    column("series_id"),
    column("group_accumulator_id"),
    column("group_id"),
)

def plan_not_linked_to_event() -> ColumnElement[bool]:
    """SQL filter: no event points at this plan."""
    return ~exists(
        select(1).where(_events.c.plan_id == Plan.id).correlate(Plan)
    )


def series_not_linked_to_event() -> ColumnElement[bool]:
    """SQL filter: no event points at this series, nor at any of its
    (non-deleted) plans."""
    return and_(
        ~exists(
            select(1).where(_events.c.series_id == Series.id).correlate(Series)
        ),
        ~exists(
            select(1)
            .select_from(Plan)
            .join(_events, _events.c.plan_id == Plan.id)
            .where(Plan.series_id == Series.id, Plan.deleted_at.is_(None))
            .correlate(Series)
        ),
    )


def group_accumulator_not_linked_to_event() -> ColumnElement[bool]:
    """SQL filter: no event in the same group points at this group accumulation."""
    # Import here: ``pecha_api.accumulator`` package ``__init__`` is heavy and
    # would close an import cycle if loaded at module import time.
    from pecha_api.accumulator.group_accumulator_models import GroupAccumulator

    return ~exists(
        select(1)
        .where(
            _events.c.group_accumulator_id == GroupAccumulator.id,
            _events.c.group_id == GroupAccumulator.group_id,
        )
        .correlate(GroupAccumulator)
    )
