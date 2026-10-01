"""add_series_id_and_group_accumulator_id_to_events

Revision ID: 2909ecf79e26
Revises: 293794bf9f09
Create Date: 2026-09-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2909ecf79e26"
down_revision: Union[str, None] = "293794bf9f09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("series_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_series_id",
        "events",
        "series",
        ["series_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_events_series_id", "events", ["series_id"])

    op.add_column(
        "events",
        sa.Column("group_accumulator_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_group_accumulator_id",
        "events",
        "group_accumulators",
        ["group_accumulator_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_events_group_accumulator_id", "events", ["group_accumulator_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_events_group_accumulator_id", table_name="events")
    op.drop_constraint("fk_events_group_accumulator_id", "events", type_="foreignkey")
    op.drop_column("events", "group_accumulator_id")

    op.drop_index("idx_events_series_id", table_name="events")
    op.drop_constraint("fk_events_series_id", "events", type_="foreignkey")
    op.drop_column("events", "series_id")
