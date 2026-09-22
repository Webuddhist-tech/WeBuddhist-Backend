"""add deity_image to mantra

Revision ID: dm1c2d3e4f5a
Revises: gat1b2c3d4e5
Create Date: 2026-09-22 00:00:00.000000

Stores the S3 key of the "original" size of the mantra's deity image (e.g.
Chenrezig for Om Mani Padme Hung) — a plain nullable column, not a catalog
FK like ``mala_image``, since the deity image is one per mantra and never
user-selected.

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import column_exists

# revision identifiers, used by Alembic.
revision: str = "dm1c2d3e4f5a"
down_revision: Union[str, None] = "gat1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("mantra", "deity_image"):
        op.add_column("mantra", sa.Column("deity_image", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    if column_exists("mantra", "deity_image"):
        op.drop_column("mantra", "deity_image")
