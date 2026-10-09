"""studio onboarding: author suspension marker and group join links

authors.suspended_at separates "suspended by a SuperAdmin" from "never
signed in to the Studio". Both used to be is_active = false. A Studio
sign-in now activates the author by itself, so it has to be able to tell
the two apart and never undo a suspension.

author_group_join_links holds shareable links that put whoever opens them
into a group with a set role, up to a use limit and an expiry.

Backfill: an inactive author last changed by someone else (updated_by is
only ever written by the SuperAdmin endpoints) is treated as suspended, so
an existing suspension is never undone by a sign-in.

Revision ID: onbd1a2b3c4d5e
Revises: fdbk1a2b3c4d5e
Create Date: 2026-10-04 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists, index_exists, table_exists

revision: str = "onbd1a2b3c4d5e"
down_revision: Union[str, None] = "fdbk1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AUTHORS = "authors"
JOIN_LINKS = "author_group_join_links"
JOIN_LINKS_GROUP_INDEX = "idx_author_group_join_links_group_id"
JOIN_LINKS_TOKEN_INDEX = "uq_author_group_join_links_token"

author_group_member_role_enum = postgresql.ENUM(
    "OWNER",
    "ADMIN",
    "AUTHOR",
    "VIEWER",
    name="author_group_member_role",
    create_type=False,
)


def upgrade() -> None:
    if not column_exists(AUTHORS, "suspended_at"):
        op.add_column(AUTHORS, sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
        op.execute(
            "UPDATE authors SET suspended_at = COALESCE(updated_at, now()) "
            "WHERE is_active = false AND updated_by IS NOT NULL "
            "AND updated_by <> COALESCE(email, '')"
        )

    if not table_exists(JOIN_LINKS):
        op.create_table(
            JOIN_LINKS,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "group_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("author_groups.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token", sa.String(length=64), nullable=False),
            sa.Column("role", author_group_member_role_enum, nullable=False),
            sa.Column("max_uses", sa.Integer(), nullable=True),
            sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
        )
    if not index_exists(JOIN_LINKS, JOIN_LINKS_TOKEN_INDEX):
        op.create_index(JOIN_LINKS_TOKEN_INDEX, JOIN_LINKS, ["token"], unique=True)
    if not index_exists(JOIN_LINKS, JOIN_LINKS_GROUP_INDEX):
        op.create_index(JOIN_LINKS_GROUP_INDEX, JOIN_LINKS, ["group_id"])


def downgrade() -> None:
    if table_exists(JOIN_LINKS):
        op.drop_table(JOIN_LINKS)
    if column_exists(AUTHORS, "suspended_at"):
        op.drop_column(AUTHORS, "suspended_at")
