"""add EVENT notification scope and per-event notifications_enabled switch

Revision ID: evt4c5d6e7f8a
Revises: evt3b4c5d6e7f
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import column_exists, enum_value_exists, table_exists
from migrations.notification_preference_schema import (
    ensure_notification_preference_tables,
)

# revision identifiers, used by Alembic.
revision: str = "evt4c5d6e7f8a"
down_revision: Union[str, None] = "evt3b4c5d6e7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Databases stamped past np1a2b3c4d5e without its DDL ever running have no
    # notification_scope type to alter, and no preference table for the scoped
    # rows to land in. Build whatever is missing before touching the enum.
    ensure_notification_preference_tables()

    # A per-event mute is a scoped preference row, so the scope enum needs the
    # new member. ALTER TYPE ... ADD VALUE cannot run inside a transaction on
    # older PostgreSQL, and the value cannot be *used* in the transaction that
    # adds it on any version - nothing here uses it, and runtime writes come
    # in later transactions.
    if not enum_value_exists("notification_scope", "EVENT"):
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE notification_scope ADD VALUE 'EVENT'")

    # The organizer's own switch, distinct from any individual's mute: off
    # silences reminders, the event-created push, and manual sends alike.
    if table_exists("events") and not column_exists("events", "notifications_enabled"):
        op.add_column(
            "events",
            sa.Column(
                "notifications_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )


def downgrade() -> None:
    if column_exists("events", "notifications_enabled"):
        op.drop_column("events", "notifications_enabled")
    # The enum member is left in place: PostgreSQL cannot drop one, and
    # recreating the type would require rewriting every column that uses it.
