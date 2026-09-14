"""add PRAYER_RECEIVED to notification_type

Revision ID: pr2b3c4d5e6f
Revises: ev1a2b3c4d5e
Create Date: 2026-09-11 10:05:00.000000

Separate from the prayer tables migration: ALTER TYPE ... ADD VALUE cannot run
inside a transaction block, and the new value cannot be used by the same
transaction that adds it.

"""
from typing import Sequence, Union

from alembic import op

from migrations.idempotency import enum_exists, enum_value_exists

# revision identifiers, used by Alembic.
revision: str = "pr2b3c4d5e6f"
down_revision: Union[str, None] = "ev1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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
    "PRAYER_RECEIVED",
)


def upgrade() -> None:
    if not enum_exists("notification_type"):
        # Environments stamped past np1a2b3c4d5e without executing it never got
        # the type; create it here with the full value set instead of altering.
        rendered = ", ".join(f"'{value}'" for value in NOTIFICATION_TYPE_VALUES)
        op.execute(f"CREATE TYPE notification_type AS ENUM ({rendered})")
        return
    if enum_value_exists("notification_type", "PRAYER_RECEIVED"):
        return
    # ADD VALUE cannot run inside a transaction block
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'PRAYER_RECEIVED'"
        )


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value. Leaving it in place keeps any
    # preference rows users have already saved for this type.
    pass
