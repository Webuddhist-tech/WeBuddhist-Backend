"""merge notification preferences and group accumulator bookmark heads

Revision ID: a2e952bd8fa8
Revises: 52f201975a03, gb1c2d3e4f5a
Create Date: 2026-09-10 14:47:00.987372

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2e952bd8fa8'
down_revision: Union[str, None] = ('52f201975a03', 'gb1c2d3e4f5a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
