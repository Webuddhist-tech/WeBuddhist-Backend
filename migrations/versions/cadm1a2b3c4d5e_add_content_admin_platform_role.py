"""add CONTENT_ADMIN to platform_role

Revision ID: cadm1a2b3c4d5e
Revises: ytls1a2b3c4d5e
Create Date: 2026-10-10 00:00:00.000000

A fourth platform role: a creator who also manages the app-wide content
catalogues (verse of the day, poems, text audio, ...) without the super
admin's view of every plan and space.
"""
from typing import Sequence, Union

from alembic import op

from migrations.idempotency import enum_exists, enum_value_exists

revision: str = "cadm1a2b3c4d5e"
down_revision: Union[str, None] = "ytls1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not enum_exists("platform_role"):
        return
    if enum_value_exists("platform_role", "CONTENT_ADMIN"):
        return
    # ADD VALUE cannot run inside a transaction block
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE platform_role ADD VALUE IF NOT EXISTS 'CONTENT_ADMIN'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value, so it stays. Before rolling the
    # code back, move any CONTENT_ADMIN authors to another role: code that
    # predates the role cannot read it.
    pass
