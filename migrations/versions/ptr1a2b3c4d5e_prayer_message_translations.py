"""prayer request translations (source_language + chat_message_translations)

Revision ID: ptr1a2b3c4d5e
Revises: dvid1a2b3c4d5e
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists, index_exists, table_exists

revision: str = "ptr1a2b3c4d5e"
down_revision: Union[str, None] = "dvid1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("chat_messages") and not column_exists(
        "chat_messages", "source_language"
    ):
        op.add_column(
            "chat_messages",
            sa.Column(
                "source_language",
                postgresql.ENUM(
                    "EN",
                    "BO",
                    "ZH",
                    "HI",
                    "NE",
                    "MN",
                    "LA",
                    name="languagecode",
                    create_type=False,
                ),
                nullable=True,
            ),
        )

    if not table_exists("chat_message_translations"):
        op.create_table(
            "chat_message_translations",
            sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
            sa.Column("message_id", sa.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "target_language",
                postgresql.ENUM(
                    "EN",
                    "BO",
                    "ZH",
                    "HI",
                    "NE",
                    "MN",
                    "LA",
                    name="languagecode",
                    create_type=False,
                ),
                nullable=False,
            ),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=16),
                server_default="pending",
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "message_id",
                "target_language",
                name="uq_chat_message_translations_message_language",
            ),
        )
        op.create_index(
            "idx_chat_message_translations_message_id",
            "chat_message_translations",
            ["message_id"],
            unique=False,
        )
        op.create_index(
            "idx_chat_message_translations_pending",
            "chat_message_translations",
            ["updated_at"],
            unique=False,
            postgresql_where=sa.text("status IN ('pending', 'failed')"),
        )


def downgrade() -> None:
    if table_exists("chat_message_translations"):
        if index_exists(
            "chat_message_translations", "idx_chat_message_translations_pending"
        ):
            op.drop_index(
                "idx_chat_message_translations_pending",
                table_name="chat_message_translations",
            )
        if index_exists(
            "chat_message_translations", "idx_chat_message_translations_message_id"
        ):
            op.drop_index(
                "idx_chat_message_translations_message_id",
                table_name="chat_message_translations",
            )
        op.drop_table("chat_message_translations")

    if table_exists("chat_messages") and column_exists(
        "chat_messages", "source_language"
    ):
        op.drop_column("chat_messages", "source_language")
