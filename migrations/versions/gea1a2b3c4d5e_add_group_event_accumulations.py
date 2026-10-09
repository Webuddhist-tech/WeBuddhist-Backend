"""add group_event_accumulations junction table

Revision ID: gea1a2b3c4d5e
Revises: prq1a2b3c4d5e
Create Date: 2026-10-09 00:00:00.000000

Links events to multiple group accumulations with per-link format, order,
and count mode. Backfills one row per legacy events.group_accumulator_id.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import table_exists

revision: str = "gea1a2b3c4d5e"
down_revision: Union[str, None] = "prq1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("group_event_accumulations"):
        return

    op.create_table(
        "group_event_accumulations",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("group_accumulator_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("event_format", sa.String(length=10), nullable=False, server_default="hybrid"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "count_mode",
            sa.String(length=32),
            nullable=False,
            server_default="manual_in_person",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["group_accumulator_id"],
            ["group_accumulators.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["group_event_accumulations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_id",
            "group_accumulator_id",
            name="uq_group_event_accumulations_event_accumulator",
        ),
    )
    op.create_index(
        "idx_group_event_accumulations_event_id",
        "group_event_accumulations",
        ["event_id"],
    )
    op.create_index(
        "idx_group_event_accumulations_group_accumulator_id",
        "group_event_accumulations",
        ["group_accumulator_id"],
    )
    op.create_index(
        "idx_group_event_accumulations_parent_id",
        "group_event_accumulations",
        ["parent_id"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO group_event_accumulations (
                id,
                event_id,
                group_accumulator_id,
                parent_id,
                event_format,
                display_order,
                count_mode,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                e.id,
                e.group_accumulator_id,
                NULL,
                e.event_format,
                1,
                'manual_in_person',
                e.created_at,
                COALESCE(e.updated_at, e.created_at)
            FROM events e
            WHERE e.group_accumulator_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    if not table_exists("group_event_accumulations"):
        return
    op.drop_index(
        "idx_group_event_accumulations_parent_id",
        table_name="group_event_accumulations",
    )
    op.drop_index(
        "idx_group_event_accumulations_group_accumulator_id",
        table_name="group_event_accumulations",
    )
    op.drop_index(
        "idx_group_event_accumulations_event_id",
        table_name="group_event_accumulations",
    )
    op.drop_table("group_event_accumulations")
