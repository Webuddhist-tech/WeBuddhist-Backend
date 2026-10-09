"""add PRAYER_REQUEST to notification_type

Revision ID: prq1a2b3c4d5e
Revises: ptr3c4d5e6f7a
Create Date: 2026-10-08 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

from migrations.idempotency import enum_exists, enum_value_exists

revision: str = "prq1a2b3c4d5e"
down_revision: Union[str, None] = "ptr3c4d5e6f7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not enum_exists("notification_type"):
        return
    if enum_value_exists("notification_type", "PRAYER_REQUEST"):
        return
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'PRAYER_REQUEST'"
        )


def downgrade() -> None:
    pass
