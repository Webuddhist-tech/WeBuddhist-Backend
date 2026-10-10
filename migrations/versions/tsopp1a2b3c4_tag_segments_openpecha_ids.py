"""store openpecha segment ids in tag_segments

Tag segments used to point at MongoDB segments (UUIDs). Segments now come
from OpenPecha, whose ids are nanoid strings, so the column becomes text.
Existing UUIDs are kept as their string form.

Revision ID: tsopp1a2b3c4
Revises: txrq1a2b3c4d5e
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "tsopp1a2b3c4"
down_revision: Union[str, None] = "txrq1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "tag_segments",
        "segment_id",
        type_=sa.String(255),
        existing_type=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        postgresql_using="segment_id::text",
    )


def downgrade() -> None:
    # OpenPecha ids can't become UUIDs; those rows can only be dropped.
    op.execute(
        "DELETE FROM tag_segments WHERE segment_id !~* "
        "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
    )
    op.alter_column(
        "tag_segments",
        "segment_id",
        type_=postgresql.UUID(as_uuid=True),
        existing_type=sa.String(255),
        existing_nullable=False,
        postgresql_using="segment_id::uuid",
    )
