"""merge timer audios and ambient sounds heads

Revision ID: 9f625e50ad83
Revises: 96d1c3054f20, pt1a2b3c4d5e
Create Date: 2026-09-16 13:58:12.052929

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f625e50ad83'
down_revision: Union[str, None] = ('96d1c3054f20', 'pt1a2b3c4d5e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
