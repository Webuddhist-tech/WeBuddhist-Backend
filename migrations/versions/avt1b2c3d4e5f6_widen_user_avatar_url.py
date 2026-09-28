"""widen users.avatar_url so an Auth0 profile image URL fits

Revision ID: avt1b2c3d4e5f6
Revises: loc1a2b3c4d5e
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "avt1b2c3d4e5f6"
down_revision: Union[str, None] = "loc1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(length=255),
        type_=sa.String(length=2048),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
