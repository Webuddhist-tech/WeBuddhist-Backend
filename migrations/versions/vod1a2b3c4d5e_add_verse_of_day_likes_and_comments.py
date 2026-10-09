"""add verse_of_day likes and comments

Revision ID: vod1a2b3c4d5e
Revises: ce1a2b3c4d5f
Create Date: 2026-09-29 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import index_exists, table_exists

revision: str = "vod1a2b3c4d5e"
down_revision: Union[str, None] = "ce1a2b3c4d5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("verse_of_day_likes"):
        op.create_table(
            "verse_of_day_likes",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("verse_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["verse_id"], ["verse_of_day.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "verse_id", "user_id", name="uq_verse_of_day_likes_verse_user"
            ),
        )

    for name, columns in (
        ("idx_verse_of_day_likes_verse_id", ["verse_id"]),
        ("idx_verse_of_day_likes_user_id", ["user_id"]),
    ):
        if not index_exists("verse_of_day_likes", name):
            op.create_index(name, "verse_of_day_likes", columns, unique=False)

    if not table_exists("verse_of_day_comments"):
        op.create_table(
            "verse_of_day_comments",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("verse_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["verse_id"], ["verse_of_day.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, columns in (
        ("idx_verse_of_day_comments_verse_id", ["verse_id"]),
        ("idx_verse_of_day_comments_user_id", ["user_id"]),
        (
            "idx_verse_of_day_comments_feed",
            ["verse_id", "created_at", "id"],
        ),
    ):
        if not index_exists("verse_of_day_comments", name):
            op.create_index(name, "verse_of_day_comments", columns, unique=False)


def downgrade() -> None:
    if table_exists("verse_of_day_comments"):
        for name in (
            "idx_verse_of_day_comments_feed",
            "idx_verse_of_day_comments_user_id",
            "idx_verse_of_day_comments_verse_id",
        ):
            if index_exists("verse_of_day_comments", name):
                op.drop_index(name, table_name="verse_of_day_comments")
        op.drop_table("verse_of_day_comments")

    if table_exists("verse_of_day_likes"):
        for name in (
            "idx_verse_of_day_likes_user_id",
            "idx_verse_of_day_likes_verse_id",
        ):
            if index_exists("verse_of_day_likes", name):
                op.drop_index(name, table_name="verse_of_day_likes")
        op.drop_table("verse_of_day_likes")
