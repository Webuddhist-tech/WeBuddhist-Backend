"""merge group accumulator about-links and subtask reference heads

Revision ID: cb4020e30a41
Revises: s5d6e7f8a9b0, sr1a2b3c4d5e
Create Date: 2026-09-14 09:30:24.414602

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb4020e30a41'
down_revision: Union[str, None] = ('s5d6e7f8a9b0', 'sr1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
