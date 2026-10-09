"""merge accumulator-title and deity-image heads

Revision ID: mx1a2b3c4d5e
Revises: mt1a2b3c4d5e, mg1c2d3e4f5a
Create Date: 2026-09-22 07:10:00.000000

Two branches merged the same vs1a2b3c4d5e fork at different points:
mt1a2b3c4d5e joined it to gat1b2c3d4e5, mg1c2d3e4f5a to dm1c2d3e4f5a (which
sits above gat1b2c3d4e5). Both are deployed to different databases, so neither
can be deleted - this joins them instead.

A database stamped at either one reaches this revision by applying whatever it
is missing from the other branch, so dm1c2d3e4f5a still runs where it has not
already.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'mx1a2b3c4d5e'
down_revision: Union[str, None] = ('mt1a2b3c4d5e', 'mg1c2d3e4f5a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
