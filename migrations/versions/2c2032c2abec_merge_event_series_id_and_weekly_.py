"""merge event series_id and weekly recurrence heads

Revision ID: 2c2032c2abec
Revises: 2909ecf79e26, wk1a2b3c4d5e
Create Date: 2026-09-08 18:21:10.504001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c2032c2abec'
down_revision: Union[str, None] = ('2909ecf79e26', 'wk1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
