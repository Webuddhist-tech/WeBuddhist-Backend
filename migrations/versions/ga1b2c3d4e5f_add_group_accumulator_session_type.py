"""add GROUP_ACCUMULATOR session type to routine sessions

Revision ID: ga1b2c3d4e5f
Revises: np1a2b3c4d5e
Create Date: 2026-09-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

from migrations.idempotency import enum_value_exists

revision: str = "ga1b2c3d4e5f"
down_revision: Union[str, None] = "np1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if enum_value_exists("sessiontype", "GROUP_ACCUMULATOR"):
        return
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE sessiontype ADD VALUE IF NOT EXISTS 'GROUP_ACCUMULATOR'"
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM routine_sessions WHERE session_type = 'GROUP_ACCUMULATOR'"
    )
