"""keep live controller tokens encrypted, so Studio can copy them again

Revision ID: lvc2b3c4d5e6f
Revises: lvc1a2b3c4d5e
Create Date: 2026-10-10 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import column_exists

revision: str = "lvc2b3c4d5e6f"
down_revision: Union[str, None] = "lvc1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not column_exists("event_live_controllers", "token_encrypted"):
        op.add_column(
            "event_live_controllers",
            sa.Column("token_encrypted", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if column_exists("event_live_controllers", "token_encrypted"):
        op.drop_column("event_live_controllers", "token_encrypted")
