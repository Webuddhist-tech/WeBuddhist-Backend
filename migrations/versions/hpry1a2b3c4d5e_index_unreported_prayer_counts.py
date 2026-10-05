"""index unreported prayer counts

The prayer dispatcher now sweeps for prayers the interval held and nobody
followed up on, every few seconds. A partial index keeps that to the handful
of rows still waiting to be reported.

Revision ID: hpry1a2b3c4d5e
Revises: ppdf1a2b3c4d5e
Create Date: 2026-10-02 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import index_exists

revision: str = "hpry1a2b3c4d5e"
down_revision: Union[str, None] = "ppdf1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "chat_message_prayer_counts"
INDEX = "idx_chat_message_prayer_counts_unreported"


def upgrade() -> None:
    if not index_exists(TABLE, INDEX):
        op.create_index(
            INDEX,
            TABLE,
            ["message_id"],
            postgresql_where=sa.text("unreported_count > 0"),
        )


def downgrade() -> None:
    if index_exists(TABLE, INDEX):
        op.drop_index(INDEX, table_name=TABLE)
