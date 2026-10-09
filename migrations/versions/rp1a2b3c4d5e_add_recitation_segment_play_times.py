"""add recitation_segment_play_times

Revision ID: rp1a2b3c4d5e
Revises: ce1a2b3c4d5f
Create Date: 2026-09-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import table_exists

revision: str = "rp1a2b3c4d5e"
down_revision: Union[str, None] = "ce1a2b3c4d5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("recitation_segment_play_times"):
        op.create_table(
            "recitation_segment_play_times",
            sa.Column("text_id", sa.String(length=255), nullable=False),
            sa.Column("segment_id", sa.String(length=128), nullable=False),
            sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("total_duration_ms", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
            sa.Column("average_duration_ms", sa.Integer(), nullable=False),
            sa.Column("last_duration_ms", sa.Integer(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.PrimaryKeyConstraint("text_id", "segment_id"),
        )


def downgrade() -> None:
    if table_exists("recitation_segment_play_times"):
        op.drop_table("recitation_segment_play_times")
