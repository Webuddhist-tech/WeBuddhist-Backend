"""merge event links and notification preferences heads

Revision ID: 52f201975a03
Revises: evtlk1a2b3c4, np1a2b3c4d5e
Create Date: 2026-09-10 11:16:41.942217

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '52f201975a03'
down_revision: Union[str, None] = ('evtlk1a2b3c4', 'np1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
