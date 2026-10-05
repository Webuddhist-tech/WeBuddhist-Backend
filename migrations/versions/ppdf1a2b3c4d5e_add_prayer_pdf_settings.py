"""add prayer pdf settings

Wording and layout of the printable prayer-request PDF, one row per group
(its template) and optionally one per event (an override).

Revision ID: ppdf1a2b3c4d5e
Revises: tset1a2b3c4d5e
Create Date: 2026-10-02 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import index_exists, table_exists

revision: str = "ppdf1a2b3c4d5e"
down_revision: Union[str, None] = "tset1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "prayer_pdf_settings"
GROUP_INDEX = "uq_prayer_pdf_settings_group"
EVENT_INDEX = "uq_prayer_pdf_settings_event"


def upgrade() -> None:
    if not table_exists(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "group_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("author_groups.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "event_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("events.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("title_bo", sa.String(length=255), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("title_zh", sa.String(length=255), nullable=True),
            sa.Column("subtitle_bo", sa.Text(), nullable=True),
            sa.Column("subtitle", sa.Text(), nullable=True),
            sa.Column("subtitle_zh", sa.Text(), nullable=True),
            sa.Column("day_one", sa.Date(), nullable=True),
            sa.Column("closing_bo", sa.Text(), nullable=True),
            sa.Column("closing_mantra", sa.Text(), nullable=True),
            sa.Column("closing_zh", sa.Text(), nullable=True),
            sa.Column("closing_en", sa.Text(), nullable=True),
            sa.Column("closing_emoji", sa.String(length=64), nullable=True),
            sa.Column("skip_messages", sa.Text(), nullable=True),
            sa.Column(
                "timezone",
                sa.String(length=64),
                nullable=False,
                server_default=sa.text("'Asia/Kolkata'"),
            ),
            sa.Column(
                "page_size",
                sa.String(length=8),
                nullable=False,
                server_default=sa.text("'A3'"),
            ),
            sa.Column("columns", sa.Integer(), nullable=False, server_default=sa.text("5")),
            sa.Column(
                "primary_color",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'#7a1f1f'"),
            ),
            sa.Column(
                "secondary_color",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'#b8872b'"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.CheckConstraint("columns BETWEEN 2 AND 6", name="ck_prayer_pdf_settings_columns"),
        )

    if not index_exists(TABLE, GROUP_INDEX):
        op.create_index(
            GROUP_INDEX,
            TABLE,
            ["group_id"],
            unique=True,
            postgresql_where=sa.text("event_id IS NULL"),
        )
    if not index_exists(TABLE, EVENT_INDEX):
        op.create_index(
            EVENT_INDEX,
            TABLE,
            ["event_id"],
            unique=True,
            postgresql_where=sa.text("event_id IS NOT NULL"),
        )


def downgrade() -> None:
    if table_exists(TABLE):
        op.drop_table(TABLE)
