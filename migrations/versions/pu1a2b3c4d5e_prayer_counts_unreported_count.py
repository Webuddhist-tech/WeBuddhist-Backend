"""track unreported prayers per person instead of a total at push

Revision ID: pu1a2b3c4d5e
Revises: pr1a2b3c4d5e
Create Date: 2026-09-30 12:00:00.000000

Prayer-received pushes now summarise the prayers not yet reported to the
requester, tracked per person in `chat_message_prayer_counts.unreported_count`,
instead of diffing against `chat_prayer_notifications.total_at_push`. Existing
prayers start with nothing unreported: they were already covered by earlier
notifications, so the first push after deploy must not present them as new.

Reconcile reads `chat_prayer_notifications` now, so the partial index on
`chat_message_prayers` that pr1a2b3c4d5e restored is dropped again: new prayer
rows no longer record a dispatch, so every one of them would land in it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import column_exists, table_exists

revision: str = "pu1a2b3c4d5e"
down_revision: Union[str, None] = "pr1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("chat_message_prayer_counts") and not column_exists(
        "chat_message_prayer_counts", "unreported_count"
    ):
        op.add_column(
            "chat_message_prayer_counts",
            sa.Column(
                "unreported_count",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if column_exists("chat_prayer_notifications", "total_at_push"):
        op.drop_column("chat_prayer_notifications", "total_at_push")

    op.drop_index(
        "idx_chat_message_prayers_undispatched",
        table_name="chat_message_prayers",
        if_exists=True,
    )


def downgrade() -> None:
    op.create_index(
        "idx_chat_message_prayers_undispatched",
        "chat_message_prayers",
        ["created_at"],
        postgresql_where=sa.text("notification_sqs_message_id IS NULL"),
        if_not_exists=True,
    )

    if table_exists("chat_prayer_notifications") and not column_exists(
        "chat_prayer_notifications", "total_at_push"
    ):
        op.add_column(
            "chat_prayer_notifications",
            sa.Column(
                "total_at_push",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if column_exists("chat_message_prayer_counts", "unreported_count"):
        op.drop_column("chat_message_prayer_counts", "unreported_count")
