"""add reference content types and reference_id to sub_tasks

Revision ID: sr1a2b3c4d5e
Revises: r4c5d6e7f8a9
Create Date: 2026-09-11 10:00:00.000000

Lets a plan subtask point at another piece of WeBuddhist content instead of
carrying the content inline: a group accumulation, a group recitation
collection, an event or a group post. The target id lives in
sub_tasks.reference_id and the content_type says which table it belongs to.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists, enum_value_exists, index_exists

# revision identifiers, used by Alembic.
revision: str = "sr1a2b3c4d5e"
down_revision: Union[str, None] = "r4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_CONTENT_TYPES = (
    "GROUP_ACCUMULATION",
    "GROUP_COLLECTION",
    "EVENT",
    "POST",
)


def upgrade() -> None:
    missing = [
        value
        for value in NEW_CONTENT_TYPES
        if not enum_value_exists("contenttype", value)
    ]
    if missing:
        # ADD VALUE cannot run inside a transaction block.
        with op.get_context().autocommit_block():
            for value in missing:
                op.execute(
                    f"ALTER TYPE contenttype ADD VALUE IF NOT EXISTS '{value}'"
                )

    if not column_exists("sub_tasks", "reference_id"):
        op.add_column(
            "sub_tasks",
            sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    if not index_exists("sub_tasks", "idx_sub_tasks_reference_id"):
        op.create_index(
            "idx_sub_tasks_reference_id",
            "sub_tasks",
            ["reference_id"],
        )


def downgrade() -> None:
    if index_exists("sub_tasks", "idx_sub_tasks_reference_id"):
        op.drop_index("idx_sub_tasks_reference_id", table_name="sub_tasks")
    if column_exists("sub_tasks", "reference_id"):
        op.drop_column("sub_tasks", "reference_id")
    # PostgreSQL cannot drop enum values; the added content types stay in place.
