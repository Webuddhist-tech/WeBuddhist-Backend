"""add text requests

Studio authors asking for texts (chants) the library does not have yet,
with attachments in S3, a status, an admin reply and the edition linked
once the text is added.

Revision ID: txrq1a2b3c4d5e
Revises: cadm1a2b3c4d5e
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import index_exists, table_exists

revision: str = "txrq1a2b3c4d5e"
down_revision: Union[str, None] = "cadm1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "text_requests"
STATUS_INDEX = "idx_text_requests_status_created_at"
REQUESTER_INDEX = "idx_text_requests_requester"


def upgrade() -> None:
    if not table_exists(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "requester_author_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("authors.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "group_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("author_groups.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "collection_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("group_recitation_collections.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column(
                "attachments",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="PENDING",
            ),
            sa.Column("reply", sa.Text(), nullable=True),
            sa.Column("text_id", sa.String(length=255), nullable=True),
            sa.Column(
                "responder_author_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("authors.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not index_exists(TABLE, STATUS_INDEX):
        op.create_index(STATUS_INDEX, TABLE, ["status", "created_at"])
    if not index_exists(TABLE, REQUESTER_INDEX):
        op.create_index(REQUESTER_INDEX, TABLE, ["requester_author_id", "created_at"])


def downgrade() -> None:
    if table_exists(TABLE):
        op.drop_table(TABLE)
