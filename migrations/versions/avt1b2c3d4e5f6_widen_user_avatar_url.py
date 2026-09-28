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
    # Anything stored since the widening may be longer than the column is
    # about to be, and Postgres refuses the ALTER rather than truncating, so
    # the rollback would fail on exactly the rows the widening was for.
    # Clearing is the honest repair: half a URL is a broken image, while an
    # empty avatar is a state the app already renders, and the next social
    # login writes the picture back.
    op.execute(
        "UPDATE users SET avatar_url = NULL "
        "WHERE avatar_url IS NOT NULL AND length(avatar_url) > 255"
    )
    op.alter_column(
        "users",
        "avatar_url",
        existing_type=sa.String(length=2048),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
