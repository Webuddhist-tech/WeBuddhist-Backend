"""add event_youtube_live_sync

Revision ID: ytls1a2b3c4d5e
Revises: tva1a2b3c4d5e
Create Date: 2026-10-10 00:00:00.000000

Schedules an admin sets up in Studio for individual events: at the chosen
times of day, the group's live YouTube stream is added to that event.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import index_exists, table_exists

revision: str = "ytls1a2b3c4d5e"
down_revision: Union[str, None] = "tva1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "event_youtube_live_sync"
GROUP_INDEX = "idx_event_youtube_live_sync_group_id"


def upgrade() -> None:
    if not table_exists(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "event_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("events.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column(
                "group_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("author_groups.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("run_times", sa.JSON(), nullable=False),
            sa.Column("timezone", sa.String(64), nullable=True),
            sa.Column("last_slot_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_run_error", sa.String(500), nullable=True),
            sa.Column("last_run_added", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_by", sa.String(255), nullable=True),
        )
    if not index_exists(TABLE, GROUP_INDEX):
        op.create_index(GROUP_INDEX, TABLE, ["group_id"])


def downgrade() -> None:
    if table_exists(TABLE):
        op.drop_table(TABLE)
