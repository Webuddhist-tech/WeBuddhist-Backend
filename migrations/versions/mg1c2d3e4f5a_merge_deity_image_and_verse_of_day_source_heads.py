"""merge deity_image and verse_of_day source heads

Revision ID: mg1c2d3e4f5a
Revises: dm1c2d3e4f5a, vs1a2b3c4d5e
Create Date: 2026-09-22 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'mg1c2d3e4f5a'
down_revision: Union[str, None] = ('dm1c2d3e4f5a', 'vs1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
