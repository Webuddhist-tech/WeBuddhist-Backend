"""add index on events.plan_id

Revision ID: bo1c2d3e4f5a
Revises: bn1c2d3e4f5a
Create Date: 2026-09-17 12:00:00.000000

Public listings (series, featured series, group practices) hide plans that an
event is merged with via ``NOT EXISTS (SELECT 1 FROM events WHERE
events.plan_id = ...)``. ``events.series_id`` is already indexed; this gives the
plan side the same lookup instead of a scan of ``events`` per candidate row.

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from migrations.idempotency import index_exists

# revision identifiers, used by Alembic.
revision: str = "bo1c2d3e4f5a"
down_revision: Union[str, None] = "bn1c2d3e4f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not index_exists("events", "idx_events_plan_id"):
        op.create_index("idx_events_plan_id", "events", ["plan_id"], unique=False)


def downgrade() -> None:
    if index_exists("events", "idx_events_plan_id"):
        op.drop_index("idx_events_plan_id", table_name="events")
