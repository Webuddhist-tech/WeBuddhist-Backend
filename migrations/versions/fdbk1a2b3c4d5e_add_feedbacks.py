"""add feedbacks

In-app feedback submitted through POST /feedback. The row is the record;
the Discord post that follows it is only a notification.

Revision ID: fdbk1a2b3c4d5e
Revises: hpry1a2b3c4d5e
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import index_exists, table_exists

revision: str = "fdbk1a2b3c4d5e"
down_revision: Union[str, None] = "hpry1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "feedbacks"
USER_INDEX = "idx_feedbacks_user_id"
CREATED_AT_INDEX = "idx_feedbacks_created_at"


def upgrade() -> None:
    if not table_exists(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("image_keys", postgresql.ARRAY(sa.String(length=512)), nullable=True),
            sa.Column("platform", sa.String(length=255), nullable=True),
            sa.Column("app_version", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not index_exists(TABLE, USER_INDEX):
        op.create_index(USER_INDEX, TABLE, ["user_id"])
    if not index_exists(TABLE, CREATED_AT_INDEX):
        op.create_index(CREATED_AT_INDEX, TABLE, ["created_at"])


def downgrade() -> None:
    if table_exists(TABLE):
        op.drop_table(TABLE)
