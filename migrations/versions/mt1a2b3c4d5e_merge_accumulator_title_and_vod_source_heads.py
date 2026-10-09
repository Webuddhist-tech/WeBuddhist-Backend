"""merge group_accumulator title and verse_of_day source heads

Revision ID: mt1a2b3c4d5e
Revises: gat1b2c3d4e5, vs1a2b3c4d5e
Create Date: 2026-09-22 06:15:00.000000

Both branches fork from bo1c2d3e4f5a and touch unrelated tables, so there is
nothing to reconcile - this only gives Alembic a single head again.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'mt1a2b3c4d5e'
down_revision: Union[str, None] = ('gat1b2c3d4e5', 'vs1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
