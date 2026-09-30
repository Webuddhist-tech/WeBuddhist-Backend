"""restore chat_message_prayers undispatched index

Revision ID: pr1a2b3c4d5e
Revises: mv1a2b3c4d5e
Create Date: 2026-09-30 11:00:00.000000

Reconcile still scans chat_message_prayers for rows missing an SQS message id.
An earlier pc1 revision dropped idx_chat_message_prayers_undispatched before
application code switched to chat_prayer_notifications; recreate it for DBs
that already ran that drop.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import index_exists, table_exists

revision: str = "pr1a2b3c4d5e"
down_revision: Union[str, None] = "mv1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("chat_message_prayers") and not index_exists(
        "chat_message_prayers", "idx_chat_message_prayers_undispatched"
    ):
        op.create_index(
            "idx_chat_message_prayers_undispatched",
            "chat_message_prayers",
            ["created_at"],
            postgresql_where=sa.text("notification_sqs_message_id IS NULL"),
        )


def downgrade() -> None:
    op.drop_index(
        "idx_chat_message_prayers_undispatched",
        table_name="chat_message_prayers",
        if_exists=True,
    )
