"""add live control settings

Revision ID: lvc1a2b3c4d5e
Revises: tsopp1a2b3c4
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotency import index_exists, table_exists

revision: str = "lvc1a2b3c4d5e"
down_revision: Union[str, None] = "tsopp1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _now():
    return sa.text("now()")


def upgrade() -> None:
    if not table_exists("live_edition_settings"):
        op.create_table(
            "live_edition_settings",
            sa.Column("edition_id", sa.String(length=64), nullable=False),
            sa.Column(
                "short_titles",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "repeated_segments",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "return_jumps",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.PrimaryKeyConstraint("edition_id"),
        )

    if not table_exists("event_live_settings"):
        op.create_table(
            "event_live_settings",
            sa.Column("event_id", sa.UUID(), nullable=False),
            sa.Column(
                "followed_languages",
                postgresql.ARRAY(sa.String(length=16)),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("fallback_language", sa.String(length=16), nullable=True),
            sa.Column(
                "record_play_times",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("lead_max_ms", sa.Integer(), nullable=False, server_default=sa.text("2000")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("event_id"),
        )

    if not table_exists("event_live_controllers"):
        op.create_table(
            "event_live_controllers",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("event_id", sa.UUID(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("token_hint", sa.String(length=8), nullable=False),
            sa.Column("default_text_id", sa.String(length=255), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_event_live_controllers_token_hash"),
        )
    if not index_exists("event_live_controllers", "idx_event_live_controllers_event"):
        op.create_index(
            "idx_event_live_controllers_event",
            "event_live_controllers",
            ["event_id"],
        )

    if not table_exists("event_live_section_orders"):
        op.create_table(
            "event_live_section_orders",
            sa.Column("event_id", sa.UUID(), nullable=False),
            sa.Column("edition_id", sa.String(length=64), nullable=False),
            sa.Column("section_ids", postgresql.ARRAY(sa.String(length=64)), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_now()),
            sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("event_id", "edition_id"),
        )


def downgrade() -> None:
    if table_exists("event_live_section_orders"):
        op.drop_table("event_live_section_orders")
    if index_exists("event_live_controllers", "idx_event_live_controllers_event"):
        op.drop_index("idx_event_live_controllers_event", table_name="event_live_controllers")
    if table_exists("event_live_controllers"):
        op.drop_table("event_live_controllers")
    if table_exists("event_live_settings"):
        op.drop_table("event_live_settings")
    if table_exists("live_edition_settings"):
        op.drop_table("live_edition_settings")
