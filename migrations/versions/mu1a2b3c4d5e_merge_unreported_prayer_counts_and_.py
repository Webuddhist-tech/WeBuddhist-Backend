"""merge unreported prayer counts and segment play times heads

Revision ID: mu1a2b3c4d5e
Revises: ms1a2b3c4d5e, pu1a2b3c4d5e
Create Date: 2026-09-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "mu1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = ("ms1a2b3c4d5e", "pu1a2b3c4d5e")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
