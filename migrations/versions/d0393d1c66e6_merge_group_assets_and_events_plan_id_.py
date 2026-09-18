"""merge group_assets and events plan_id index

Revision ID: d0393d1c66e6
Revises: bo1c2d3e4f5a, ga7b8c9d0e1f
Create Date: 2026-09-18 09:15:11.601090

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd0393d1c66e6'
down_revision: Union[str, None] = ('bo1c2d3e4f5a', 'ga7b8c9d0e1f')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
