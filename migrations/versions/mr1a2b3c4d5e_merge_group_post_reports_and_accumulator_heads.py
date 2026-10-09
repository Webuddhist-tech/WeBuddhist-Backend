"""merge group_post_reports and accumulator-title/deity-image heads

Revision ID: mr1a2b3c4d5e
Revises: mx1a2b3c4d5e, gpr1a2b3c4d5
Create Date: 2026-09-22 09:00:00.000000

gpr1a2b3c4d5 forks from gat1b2c3d4e5, the same point the mt1a2b3c4d5e chain
merged upward from, so the group_post_reports work was left as a second head
when mx1a2b3c4d5e rejoined the other branches. The two sides touch unrelated
tables - group_post_reports against mantra/verse_of_day/group_accumulator
columns - so there is nothing to reconcile; this only gives Alembic a single
head again.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'mr1a2b3c4d5e'
down_revision: Union[str, None] = ('mx1a2b3c4d5e', 'gpr1a2b3c4d5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
