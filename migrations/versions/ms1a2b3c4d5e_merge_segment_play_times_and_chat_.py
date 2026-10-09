"""merge segment play times and chat prayer index heads

Revision ID: ms1a2b3c4d5e
Revises: pr1a2b3c4d5e, rp1a2b3c4d5e
Create Date: 2026-09-30 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "ms1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = ("pr1a2b3c4d5e", "rp1a2b3c4d5e")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
