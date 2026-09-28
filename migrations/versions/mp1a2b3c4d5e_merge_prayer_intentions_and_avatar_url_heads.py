"""merge prayer intentions and avatar url heads

Revision ID: mp1a2b3c4d5e
Revises: pi1a2b3c4d5e, avt1b2c3d4e5f6
Create Date: 2026-09-28 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "mp1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = ("pi1a2b3c4d5e", "avt1b2c3d4e5f6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
