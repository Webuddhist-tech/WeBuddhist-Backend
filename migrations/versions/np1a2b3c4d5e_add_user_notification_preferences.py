"""add user_notification_preferences table

Revision ID: np1a2b3c4d5e
Revises: tb1c2d3e4f5a
Create Date: 2026-09-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

from migrations.idempotency import enum_exists, index_exists, table_exists
from migrations.notification_preference_schema import (
    ensure_notification_preference_tables,
)

# revision identifiers, used by Alembic.
revision: str = "np1a2b3c4d5e"
down_revision: Union[str, None] = "tb1c2d3e4f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    ensure_notification_preference_tables()


def downgrade() -> None:
    for index_name in (
        "idx_user_notif_pref_lookup",
        "uq_user_notif_pref_scoped",
        "uq_user_notif_pref_global",
    ):
        if index_exists("user_notification_preferences", index_name):
            op.drop_index(index_name, table_name="user_notification_preferences")

    if table_exists("user_notification_preferences"):
        op.drop_table("user_notification_preferences")

    for enum_name in ("notification_scope", "notification_channel", "notification_type"):
        if enum_exists(enum_name):
            op.execute(f"DROP TYPE {enum_name}")
