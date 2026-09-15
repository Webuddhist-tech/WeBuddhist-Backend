"""make timer group_id optional and add image_url

Revision ID: tm1a2b3c4d5e
Revises: 5fb87118f326
Create Date: 2026-09-15 10:30:00.000000

User-created timers do not have to belong to a group. An optional cover
image is stored as an S3 key, matching audio_url.

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists

# revision identifiers, used by Alembic.
revision: str = "tm1a2b3c4d5e"
down_revision: Union[str, None] = "5fb87118f326"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "timers",
        "group_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    if not column_exists("timers", "image_url"):
        op.add_column(
            "timers",
            sa.Column("image_url", sa.String(length=1000), nullable=True),
        )


def downgrade() -> None:
    if column_exists("timers", "image_url"):
        op.drop_column("timers", "image_url")
    # Personal timers carry no group and cannot be represented once group_id is
    # NOT NULL again, so Postgres would reject the ALTER and strand the
    # rollback. Remove them first. This also removes their timer_history rows,
    # which cascade on timers.id -- lossy, but consistent with dropping
    # image_url above, and the only way this migration can be reversed.
    op.execute("DELETE FROM timers WHERE group_id IS NULL")
    op.alter_column(
        "timers",
        "group_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
