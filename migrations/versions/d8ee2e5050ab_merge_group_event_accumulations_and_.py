"""merge group event accumulations and tokens_valid_after heads

Revision ID: d8ee2e5050ab
Revises: gea1a2b3c4d5e, tva1a2b3c4d5e
Create Date: 2026-10-09 14:02:53.690256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8ee2e5050ab'
down_revision: Union[str, None] = ('gea1a2b3c4d5e', 'tva1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
