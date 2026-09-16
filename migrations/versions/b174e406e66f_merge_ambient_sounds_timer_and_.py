"""merge ambient sounds timer and accumulator prayer notification heads

Revision ID: b174e406e66f
Revises: 96d1c3054f20, 5fb87118f326
Create Date: 2026-09-16 14:47:11.713505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b174e406e66f'
down_revision: Union[str, None] = ('96d1c3054f20', '5fb87118f326')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
