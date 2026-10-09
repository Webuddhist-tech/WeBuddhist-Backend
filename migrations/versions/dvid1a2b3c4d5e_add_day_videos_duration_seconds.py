"""add day_videos.duration_seconds

YouTube length for a plan-day link, in whole seconds. Nullable so existing
rows and failed/live lookups stay valid until a later GET backfill.

Revision ID: dvid1a2b3c4d5e
Revises: mgr1a2b3c4d5e
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import column_exists, table_exists

revision: str = "dvid1a2b3c4d5e"
down_revision: Union[str, None] = "mgr1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "day_videos"
COLUMN = "duration_seconds"


def upgrade() -> None:
    if not table_exists(TABLE):
        return
    if not column_exists(TABLE, COLUMN):
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    if column_exists(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
