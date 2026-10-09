"""add group_post_reports

Revision ID: gpr1a2b3c4d5
Revises: gat1b2c3d4e5
Create Date: 2026-09-22 08:00:00.000000

Moderation reports for a group's posts and comments, parallel to
chat_message_reports. post_id is set even for a COMMENT report so a group's
queue can be built by joining through group_posts.group_id.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import index_exists, table_exists

# revision identifiers, used by Alembic.
revision: str = "gpr1a2b3c4d5"
down_revision: Union[str, None] = "gat1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not table_exists("group_post_reports"):
        op.create_table(
            "group_post_reports",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("post_id", sa.UUID(), nullable=False),
            sa.Column("comment_id", sa.UUID(), nullable=True),
            sa.Column("reporter_id", sa.UUID(), nullable=False),
            sa.Column("reported_user_id", sa.UUID(), nullable=True),
            sa.Column("target_type", sa.String(length=16), nullable=False),
            sa.Column("content_text", sa.Text(), nullable=True),
            sa.Column("reason", sa.String(length=32), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["post_id"], ["group_posts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["comment_id"], ["group_post_comments.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["reported_user_id"], ["users.id"], ondelete="CASCADE"
            ),
            sa.CheckConstraint(
                "(target_type = 'POST' AND comment_id IS NULL) OR "
                "(target_type = 'COMMENT' AND comment_id IS NOT NULL)",
                name="ck_group_post_reports_target_shape",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    for name, columns in (
        ("idx_group_post_reports_post_id", ["post_id"]),
        ("idx_group_post_reports_comment_id", ["comment_id"]),
        ("idx_group_post_reports_created_at", ["created_at"]),
    ):
        if not index_exists("group_post_reports", name):
            op.create_index(name, "group_post_reports", columns)

    # Partial, not plain UNIQUE: Postgres exempts NULL from a unique index, so
    # (post_id, NULL, reporter_id) would never collide with itself and one
    # reporter could file unlimited reports against the same post.
    if not index_exists("group_post_reports", "uq_group_post_reports_post_reporter"):
        op.create_index(
            "uq_group_post_reports_post_reporter",
            "group_post_reports",
            ["post_id", "reporter_id"],
            unique=True,
            postgresql_where=sa.text("comment_id IS NULL"),
        )
    if not index_exists("group_post_reports", "uq_group_post_reports_comment_reporter"):
        op.create_index(
            "uq_group_post_reports_comment_reporter",
            "group_post_reports",
            ["comment_id", "reporter_id"],
            unique=True,
            postgresql_where=sa.text("comment_id IS NOT NULL"),
        )


def downgrade() -> None:
    if table_exists("group_post_reports"):
        op.drop_table("group_post_reports")
