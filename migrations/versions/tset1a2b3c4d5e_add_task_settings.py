"""add task settings

Reader defaults per task (commentary / translation panel, optional text id)
and the live flag, with at most one live task per day.

Revision ID: tset1a2b3c4d5e
Revises: vdcl1a2b3c4d5e
Create Date: 2026-10-01 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import column_exists, index_exists

revision: str = "tset1a2b3c4d5e"
down_revision: Union[str, None] = "vdcl1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "tasks"
LIVE_INDEX = "uq_tasks_one_live_per_day"

FLAG_COLUMNS = ("is_commentary_open", "is_translation_open", "is_live")
TEXT_ID_COLUMNS = ("commentary_text_id", "translation_text_id")


def upgrade() -> None:
    for name in FLAG_COLUMNS:
        if not column_exists(TABLE, name):
            op.add_column(
                TABLE,
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false")),
            )
    for name in TEXT_ID_COLUMNS:
        if not column_exists(TABLE, name):
            op.add_column(TABLE, sa.Column(name, sa.String(length=255), nullable=True))

    if not index_exists(TABLE, LIVE_INDEX):
        op.create_index(
            LIVE_INDEX,
            TABLE,
            ["plan_item_id"],
            unique=True,
            postgresql_where=sa.text("is_live AND deleted_at IS NULL"),
        )


def downgrade() -> None:
    if index_exists(TABLE, LIVE_INDEX):
        op.drop_index(LIVE_INDEX, table_name=TABLE)
    for name in (*TEXT_ID_COLUMNS, *FLAG_COLUMNS):
        if column_exists(TABLE, name):
            op.drop_column(TABLE, name)
