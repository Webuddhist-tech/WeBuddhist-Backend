"""Idempotent helpers to ensure the notification preference schema exists.

Production and local databases may have alembic_version past np1a2b3c4d5e
without that revision's DDL ever having run: the migration lived on develop
while deploy branches were stamped past it (merge/stamp drift). Migrations
that alter the notification enums or preference table call
ensure_notification_preference_tables() first.
"""
from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotency import enum_exists, index_exists, table_exists

# The values each enum is born with. Later migrations add members on top
# (PRAYER_RECEIVED via pr2b3c4d5e6f, EVENT via evt4c5d6e7f8a), so these stay
# as they were rather than tracking the current application enums.
NOTIFICATION_TYPE_VALUES = (
    "CHAT_MESSAGE",
    "GROUP_POST",
    "EVENT",
    "EVENT_REMINDER",
    "ACCUMULATION",
    "SERIES",
    "GROUP_INVITE",
    "GROUP_JOIN_REQUEST",
    "VERSE_OF_DAY",
    "ROUTINE_REMINDER",
)
NOTIFICATION_CHANNEL_VALUES = ("PUSH", "IN_APP", "EMAIL")
NOTIFICATION_SCOPE_VALUES = ("GLOBAL", "GROUP")

NOTIFICATION_TYPE_ENUM = postgresql.ENUM(
    *NOTIFICATION_TYPE_VALUES, name="notification_type", create_type=False
)
NOTIFICATION_CHANNEL_ENUM = postgresql.ENUM(
    *NOTIFICATION_CHANNEL_VALUES, name="notification_channel", create_type=False
)
NOTIFICATION_SCOPE_ENUM = postgresql.ENUM(
    *NOTIFICATION_SCOPE_VALUES, name="notification_scope", create_type=False
)


def create_enum(name: str, values: Sequence[str]) -> None:
    """Create an enum type if the database does not already have it."""
    if not enum_exists(name):
        rendered = ", ".join(f"'{value}'" for value in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({rendered})")


def ensure_notification_preference_tables() -> None:
    """Create the notification enums, table and indexes that are missing."""
    create_enum("notification_type", NOTIFICATION_TYPE_VALUES)
    create_enum("notification_channel", NOTIFICATION_CHANNEL_VALUES)
    create_enum("notification_scope", NOTIFICATION_SCOPE_VALUES)

    if not table_exists("user_notification_preferences"):
        _create_user_notification_preferences()

    _create_indexes()


def _create_user_notification_preferences() -> None:
    op.create_table(
        "user_notification_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("notification_type", NOTIFICATION_TYPE_ENUM, nullable=False),
        sa.Column(
            "channel",
            NOTIFICATION_CHANNEL_ENUM,
            nullable=False,
            server_default="PUSH",
        ),
        sa.Column(
            "scope_type",
            NOTIFICATION_SCOPE_ENUM,
            nullable=False,
            server_default="GLOBAL",
        ),
        sa.Column("scope_id", sa.UUID(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Written as an equivalence so new scope values need no constraint change
        sa.CheckConstraint(
            "(scope_type = 'GLOBAL') = (scope_id IS NULL)",
            name="ck_user_notif_pref_scope",
        ),
    )


def _create_indexes() -> None:
    # Postgres does not dedupe NULLs, so global and scoped rows need separate
    # partial unique indexes.
    if not index_exists("user_notification_preferences", "uq_user_notif_pref_global"):
        op.create_index(
            "uq_user_notif_pref_global",
            "user_notification_preferences",
            ["user_id", "notification_type", "channel"],
            unique=True,
            postgresql_where=sa.text("scope_id IS NULL"),
        )

    if not index_exists("user_notification_preferences", "uq_user_notif_pref_scoped"):
        op.create_index(
            "uq_user_notif_pref_scoped",
            "user_notification_preferences",
            ["user_id", "notification_type", "channel", "scope_type", "scope_id"],
            unique=True,
            postgresql_where=sa.text("scope_id IS NOT NULL"),
        )

    if not index_exists("user_notification_preferences", "idx_user_notif_pref_lookup"):
        op.create_index(
            "idx_user_notif_pref_lookup",
            "user_notification_preferences",
            ["notification_type", "channel", "user_id"],
            unique=False,
        )
