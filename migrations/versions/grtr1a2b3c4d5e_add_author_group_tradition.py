"""add author_groups.tradition_id

Each group (practice space) can be marked with one tradition from
tradition_list. Nullable: existing groups are left unset rather than guessed,
and Studio is not yet required to send one. Deleting a tradition clears it
from its groups instead of blocking the delete.

Revision ID: grtr1a2b3c4d5e
Revises: onbd1a2b3c4d5e
Create Date: 2026-10-05 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists, fk_exists, index_exists, table_exists

revision: str = "grtr1a2b3c4d5e"
down_revision: Union[str, None] = "onbd1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GROUPS = "author_groups"
COLUMN = "tradition_id"
FK_NAME = "fk_author_groups_tradition_id_tradition_list"
INDEX_NAME = "idx_author_groups_tradition_id"


def upgrade() -> None:
    if not table_exists(GROUPS) or not table_exists("tradition_list"):
        return

    if not column_exists(GROUPS, COLUMN):
        op.add_column(GROUPS, sa.Column(COLUMN, postgresql.UUID(as_uuid=True), nullable=True))

    if not fk_exists(GROUPS, FK_NAME):
        op.create_foreign_key(
            FK_NAME,
            GROUPS,
            "tradition_list",
            [COLUMN],
            ["id"],
            ondelete="SET NULL",
        )

    if not index_exists(GROUPS, INDEX_NAME):
        op.create_index(INDEX_NAME, GROUPS, [COLUMN])


def downgrade() -> None:
    if index_exists(GROUPS, INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name=GROUPS)
    if fk_exists(GROUPS, FK_NAME):
        op.drop_constraint(FK_NAME, GROUPS, type_="foreignkey")
    if column_exists(GROUPS, COLUMN):
        op.drop_column(GROUPS, COLUMN)
