"""align chat_message_translations with prayer translation model

Legacy DBs may already have chat_message_translations with `language` and no
status/updated_at (table existed before ptr1, so create was skipped). This
migration brings those rows in line with ChatMessageTranslation.

Revision ID: ptr2b3c4d5e6f
Revises: ptr1a2b3c4d5e
Create Date: 2026-10-07 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists, index_exists, table_exists

revision: str = "ptr2b3c4d5e6f"
down_revision: Union[str, None] = "ptr1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "chat_message_translations"


def upgrade() -> None:
    if not table_exists(TABLE):
        return

    if column_exists(TABLE, "language") and not column_exists(TABLE, "target_language"):
        op.alter_column(TABLE, "language", new_column_name="target_language")

    if not column_exists(TABLE, "status"):
        op.add_column(
            TABLE,
            sa.Column(
                "status",
                sa.String(length=16),
                server_default="pending",
                nullable=False,
            ),
        )
        op.execute(
            sa.text(
                f"""
                UPDATE {TABLE}
                SET status = 'ready'
                WHERE body IS NOT NULL AND btrim(body) <> ''
                """
            )
        )

    if not column_exists(TABLE, "updated_at"):
        op.add_column(
            TABLE,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("timezone('utc', now())"),
                nullable=False,
            ),
        )

    # Model stores pending rows with null body; legacy table required NOT NULL.
    op.alter_column(TABLE, "body", existing_type=sa.Text(), nullable=True)

    if index_exists(TABLE, "idx_chat_message_translations_message_language"):
        op.drop_index(
            "idx_chat_message_translations_message_language",
            table_name=TABLE,
        )

    if not index_exists(TABLE, "idx_chat_message_translations_message_id"):
        op.create_index(
            "idx_chat_message_translations_message_id",
            TABLE,
            ["message_id"],
            unique=False,
        )

    if not index_exists(TABLE, "idx_chat_message_translations_pending"):
        op.create_index(
            "idx_chat_message_translations_pending",
            TABLE,
            ["updated_at"],
            unique=False,
            postgresql_where=sa.text("status IN ('pending', 'failed')"),
        )


def downgrade() -> None:
    if not table_exists(TABLE):
        return

    if index_exists(TABLE, "idx_chat_message_translations_pending"):
        op.drop_index(
            "idx_chat_message_translations_pending",
            table_name=TABLE,
        )

    if index_exists(TABLE, "idx_chat_message_translations_message_id"):
        op.drop_index(
            "idx_chat_message_translations_message_id",
            table_name=TABLE,
        )

    if column_exists(TABLE, "updated_at"):
        op.drop_column(TABLE, "updated_at")

    if column_exists(TABLE, "status"):
        op.drop_column(TABLE, "status")

    if column_exists(TABLE, "target_language") and not column_exists(TABLE, "language"):
        op.alter_column(TABLE, "target_language", new_column_name="language")

    if not index_exists(TABLE, "idx_chat_message_translations_message_language"):
        op.create_index(
            "idx_chat_message_translations_message_language",
            TABLE,
            ["message_id", "language"],
            unique=False,
        )

    op.alter_column(TABLE, "body", existing_type=sa.Text(), nullable=False)
