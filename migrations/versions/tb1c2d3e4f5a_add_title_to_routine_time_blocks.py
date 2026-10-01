"""add title to routine_time_blocks

Revision ID: tb1c2d3e4f5a
Revises: 0f3617ef0e23
Create Date: 2026-09-09 12:00:00.000000

Adds an optional user-provided ``title`` for each time block (practice name).

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import column_exists

# revision identifiers, used by Alembic.
revision: str = "tb1c2d3e4f5a"
down_revision: Union[str, None] = "0f3617ef0e23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("routine_time_blocks", "title"):
        op.add_column(
            "routine_time_blocks",
            sa.Column("title", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    if column_exists("routine_time_blocks", "title"):
        op.drop_column("routine_time_blocks", "title")
