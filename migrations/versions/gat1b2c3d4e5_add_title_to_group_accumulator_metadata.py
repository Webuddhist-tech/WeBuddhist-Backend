"""add title to group_accumulator_metadata

Revision ID: gat1b2c3d4e5
Revises: d0393d1c66e6
Create Date: 2026-09-21 10:00:00.000000

Per-language titles for group accumulators, alongside the per-language About
text that already lives here. ``group_accumulators.title`` stays as the default
title so the public responses and the other modules reading that column are
unaffected; existing rows are backfilled from it.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import column_exists

# revision identifiers, used by Alembic.
revision: str = "gat1b2c3d4e5"
down_revision: Union[str, None] = "d0393d1c66e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if column_exists("group_accumulator_metadata", "title"):
        return

    op.add_column(
        "group_accumulator_metadata",
        sa.Column("title", sa.String(), nullable=True),
    )

    # Every existing language showed the same single title, so start there.
    op.execute(
        """
        UPDATE group_accumulator_metadata AS m
        SET title = g.title
        FROM group_accumulators AS g
        WHERE m.group_accumulator_id = g.id
          AND m.title IS NULL
          AND g.title IS NOT NULL
        """
    )


def downgrade() -> None:
    if column_exists("group_accumulator_metadata", "title"):
        op.drop_column("group_accumulator_metadata", "title")
