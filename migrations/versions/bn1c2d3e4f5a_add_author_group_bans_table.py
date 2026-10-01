"""add author_group_bans table

Revision ID: bn1c2d3e4f5a
Revises: am1b2c3d4e5f
Create Date: 2026-09-17 10:00:00.000000

Removing a joined user from a COMMUNITY group in Studio also blocks them from
rejoining for a while (7 days by default). That block needs to outlive the
``author_group_joins`` row it deletes, so it gets its own table rather than a
flag on the join.

Rows are never deleted: lifting a ban early stamps ``lifted_at`` and an expired
ban keeps its row, so the group's moderation history stays readable. The
active-ban lookup therefore filters on ``lifted_at IS NULL`` and
``expires_at > now()`` rather than on the row's existence.

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import index_exists, table_exists

# revision identifiers, used by Alembic.
revision: str = "bn1c2d3e4f5a"
down_revision: Union[str, None] = "am1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = (
    ("idx_author_group_bans_group_user", ["group_id", "user_id"]),
    ("idx_author_group_bans_group_expires", ["group_id", "expires_at"]),
    ("idx_author_group_bans_user_expires", ["user_id", "expires_at"]),
)


def upgrade() -> None:
    if not table_exists("author_group_bans"):
        op.create_table(
            "author_group_bans",
            sa.Column(
                "id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")
            ),
            sa.Column("group_id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lifted_by", sa.UUID(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("created_by", sa.UUID(), nullable=True),
            sa.ForeignKeyConstraint(["group_id"], ["author_groups.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["authors.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["lifted_by"], ["authors.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    for index_name, columns in INDEXES:
        if not index_exists("author_group_bans", index_name):
            op.create_index(index_name, "author_group_bans", columns, unique=False)


def downgrade() -> None:
    for index_name, _ in reversed(INDEXES):
        if index_exists("author_group_bans", index_name):
            op.drop_index(index_name, table_name="author_group_bans")
    if table_exists("author_group_bans"):
        op.drop_table("author_group_bans")
