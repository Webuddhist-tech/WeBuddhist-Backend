"""merge prayer counts and verse of day heads

Revision ID: mv1a2b3c4d5e
Revises: pc1a2b3c4d5e, vod1a2b3c4d5e
Create Date: 2026-09-30 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "mv1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = ("pc1a2b3c4d5e", "vod1a2b3c4d5e")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
