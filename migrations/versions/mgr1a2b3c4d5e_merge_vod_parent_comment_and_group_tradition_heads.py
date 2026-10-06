"""merge vod parent_comment_id and author group tradition heads

Revision ID: mgr1a2b3c4d5e
Revises: vodpc1a2b3c4d5e, grtr1a2b3c4d5e
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "mgr1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = ("vodpc1a2b3c4d5e", "grtr1a2b3c4d5e")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
