"""Visibility rule for plans that are merged into an event.

A plan an event points at (``events.plan_id``) is event content: it is reached
through the event, which hands clients its ``plan_id``. It must not surface on
its own in the public plan browse/discovery listings, so the plan stays
fetchable by id while disappearing from every "here are the plans" surface.
"""

from sqlalchemy import column, exists, select, table

from pecha_api.plans.plans_models import Plan
from pecha_api.plans.series.series_model import Series

# A lightweight table construct rather than an import of
# ``pecha_api.events.Event``: ``pecha_api.events.__init__`` pulls in the event
# service, which imports back into ``pecha_api.plans`` -- importing the model
# here would close that cycle.
_events = table("events", column("plan_id"))


def plan_not_linked_to_event():
    """SQL filter: no event points at this plan."""
    return ~exists(
        select(1).where(_events.c.plan_id == Plan.id).correlate(Plan)
    )


def series_without_event_linked_plan():
    """SQL filter: none of the series' (non-deleted) plans is merged into an event."""
    return ~exists(
        select(1)
        .select_from(Plan)
        .join(_events, _events.c.plan_id == Plan.id)
        .where(Plan.series_id == Series.id, Plan.deleted_at.is_(None))
        .correlate(Series)
    )
