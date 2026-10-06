"""add parent_comment_id to verse_of_day_comments

Revision ID: vodpc1a2b3c4d5e
Revises: onbd1a2b3c4d5e
Create Date: 2026-10-05 15:40:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import column_exists, fk_exists, index_exists, table_exists

revision: str = "vodpc1a2b3c4d5e"
down_revision: Union[str, None] = "onbd1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "verse_of_day_comments"
COLUMN = "parent_comment_id"
FK_NAME = "verse_of_day_comments_parent_comment_id_fkey"
INDEX_NAME = "idx_verse_of_day_comments_parent_comment_id"


def upgrade() -> None:
    if not table_exists(TABLE):
        return

    if not column_exists(TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.UUID(), nullable=True),
        )

    if not fk_exists(TABLE, FK_NAME):
        op.create_foreign_key(
            FK_NAME,
            TABLE,
            TABLE,
            [COLUMN],
            ["id"],
            ondelete="CASCADE",
        )

    if not index_exists(TABLE, INDEX_NAME):
        op.create_index(
            INDEX_NAME,
            TABLE,
            [COLUMN],
            unique=False,
        )


def downgrade() -> None:
    if not table_exists(TABLE):
        return

    if index_exists(TABLE, INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name=TABLE)

    if fk_exists(TABLE, FK_NAME):
        op.drop_constraint(FK_NAME, TABLE, type_="foreignkey")

    if column_exists(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
