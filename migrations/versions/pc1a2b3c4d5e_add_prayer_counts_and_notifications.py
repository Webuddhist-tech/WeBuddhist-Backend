"""add prayer counts and prayer notifications

Revision ID: pc1a2b3c4d5e
Revises: ce1a2b3c4d5f
Create Date: 2026-09-30 00:00:00.000000

Lets a member pray for the same request more than once. Per-person totals live
in `chat_message_prayer_counts`; `chat_message_prayers` stays the "is praying"
record. Every existing prayer is backfilled as a count of one.

Prayer-received pushes move off the per-prayer dispatch columns and onto
`chat_prayer_notifications`, one row per push, each carrying a summary of the
prayers since the previous push for that request.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import table_exists

# revision identifiers, used by Alembic.
revision: str = "pc1a2b3c4d5e"
down_revision: Union[str, None] = "ce1a2b3c4d5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- chat_message_prayer_counts ---------------------------------------
    if not table_exists("chat_message_prayer_counts"):
        op.create_table(
            "chat_message_prayer_counts",
            sa.Column(
                "id",
                sa.UUID(),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("message_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("prayer_count", sa.BigInteger(), nullable=False),
            sa.Column(
                "first_prayed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "last_prayed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "message_id",
                "user_id",
                name="uq_chat_message_prayer_counts_message_user",
            ),
            sa.CheckConstraint(
                "prayer_count >= 1", name="ck_chat_message_prayer_counts_positive"
            ),
        )
        op.create_index(
            "idx_chat_message_prayer_counts_message_last",
            "chat_message_prayer_counts",
            ["message_id", sa.text("last_prayed_at DESC")],
        )

    op.execute(
        """
        INSERT INTO chat_message_prayer_counts
            (id, message_id, user_id, prayer_count, first_prayed_at, last_prayed_at)
        SELECT gen_random_uuid(), message_id, user_id, 1, created_at, created_at
        FROM chat_message_prayers
        ON CONFLICT (message_id, user_id) DO NOTHING
        """
    )

    # --- chat_prayer_notifications ----------------------------------------
    if not table_exists("chat_prayer_notifications"):
        op.create_table(
            "chat_prayer_notifications",
            sa.Column(
                "id",
                sa.UUID(),
                nullable=False,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("message_id", sa.UUID(), nullable=False),
            sa.Column("people_count", sa.Integer(), nullable=False),
            sa.Column("prayer_total", sa.BigInteger(), nullable=False),
            sa.Column("latest_user_id", sa.UUID(), nullable=True),
            sa.Column("total_at_push", sa.BigInteger(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("notification_sqs_message_id", sa.String(length=128), nullable=True),
            sa.Column(
                "notification_dispatched_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.ForeignKeyConstraint(
                ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["latest_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "idx_chat_prayer_notifications_message_created",
            "chat_prayer_notifications",
            ["message_id", sa.text("created_at DESC")],
        )
        op.create_index(
            "idx_chat_prayer_notifications_undispatched",
            "chat_prayer_notifications",
            ["created_at"],
            postgresql_where=sa.text("notification_sqs_message_id IS NULL"),
        )

    # New prayer rows no longer record a dispatch, so every one of them would
    # land in this partial index; reconcile now reads chat_prayer_notifications.
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
    if table_exists("chat_prayer_notifications"):
        op.drop_table("chat_prayer_notifications")
    if table_exists("chat_message_prayer_counts"):
        op.drop_table("chat_message_prayer_counts")
