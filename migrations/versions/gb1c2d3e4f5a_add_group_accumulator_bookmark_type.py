"""add GROUP_ACCUMULATOR to bookmark_type

Revision ID: gb1c2d3e4f5a
Revises: ga1b2c3d4e5f
Create Date: 2026-09-10 10:30:00.000000

Allows users to bookmark group accumulations, alongside the existing
TEXT/PLAN/SERIES/ACCUMULATOR/TIMER/VERSE/collection bookmark types.

"""
from typing import Sequence, Union

from alembic import op

from migrations.idempotency import enum_exists, enum_value_exists

# revision identifiers, used by Alembic.
revision: str = "gb1c2d3e4f5a"
down_revision: Union[str, None] = "ga1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not enum_exists("bookmark_type"):
        # Environments stamped past the creating revision without executing it
        # never got the type; create it here with the full value set.
        op.execute(
            "CREATE TYPE bookmark_type AS ENUM "
            "('TEXT', 'PLAN', 'SERIES', 'ACCUMULATOR', 'TIMER', 'VERSE', "
            "'RECITATION_COLLECTION', 'GROUP_RECITATION_COLLECTION', "
            "'GROUP_ACCUMULATOR')"
        )
        return
    if enum_value_exists("bookmark_type", "GROUP_ACCUMULATOR"):
        return
    # ADD VALUE cannot run inside a transaction block
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE bookmark_type ADD VALUE IF NOT EXISTS 'GROUP_ACCUMULATOR'"
        )


def downgrade() -> None:
    # Note: PostgreSQL doesn't support removing enum values directly.
    # For safety, we leave the enum value in place during downgrade and keep
    # any GROUP_ACCUMULATOR bookmarks users have created.
    pass
