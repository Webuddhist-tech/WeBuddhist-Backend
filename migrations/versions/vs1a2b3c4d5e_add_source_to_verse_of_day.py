"""add source to verse_of_day

Revision ID: vs1a2b3c4d5e
Revises: bo1c2d3e4f5a
Create Date: 2026-09-17 14:10:00.000000

Optional human-readable scripture abbreviation for Verse of the Day.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import column_exists

revision: str = "vs1a2b3c4d5e"
down_revision: Union[str, None] = "bo1c2d3e4f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("verse_of_day", "source"):
        op.add_column(
            "verse_of_day",
            sa.Column("source", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    if column_exists("verse_of_day", "source"):
        op.drop_column("verse_of_day", "source")
