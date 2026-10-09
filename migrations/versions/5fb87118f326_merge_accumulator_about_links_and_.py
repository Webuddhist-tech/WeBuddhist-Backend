"""merge accumulator about-links and prayer notification heads

Revision ID: 5fb87118f326
Revises: cb4020e30a41, pr2b3c4d5e6f
Create Date: 2026-09-14 09:43:03.413221

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fb87118f326'
down_revision: Union[str, None] = ('cb4020e30a41', 'pr2b3c4d5e6f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
