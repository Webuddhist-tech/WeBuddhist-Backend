"""add verse_of_day comment likes

Revision ID: vdcl1a2b3c4d5e
Revises: ei1a2b3c4d5e
Create Date: 2026-10-01 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import index_exists, table_exists

revision: str = "vdcl1a2b3c4d5e"
down_revision: Union[str, None] = "ei1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("verse_of_day_comment_likes"):
        op.create_table(
            "verse_of_day_comment_likes",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("comment_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["comment_id"],
                ["verse_of_day_comments.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "comment_id",
                "user_id",
                name="uq_verse_of_day_comment_likes_comment_user",
            ),
        )

    for name, columns in (
        ("idx_verse_of_day_comment_likes_comment_id", ["comment_id"]),
        ("idx_verse_of_day_comment_likes_user_id", ["user_id"]),
        (
            "idx_verse_of_day_comment_likes_comment_created",
            ["comment_id", "created_at", "id"],
        ),
    ):
        if not index_exists("verse_of_day_comment_likes", name):
            op.create_index(
                name, "verse_of_day_comment_likes", columns, unique=False
            )


def downgrade() -> None:
    if table_exists("verse_of_day_comment_likes"):
        for name in (
            "idx_verse_of_day_comment_likes_comment_created",
            "idx_verse_of_day_comment_likes_user_id",
            "idx_verse_of_day_comment_likes_comment_id",
        ):
            if index_exists("verse_of_day_comment_likes", name):
                op.drop_index(name, table_name="verse_of_day_comment_likes")
        op.drop_table("verse_of_day_comment_likes")
