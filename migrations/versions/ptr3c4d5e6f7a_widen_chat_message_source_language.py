"""store prayer source_language as ISO 639-1 string (any language)

Revision ID: ptr3c4d5e6f7a
Revises: ptr2b3c4d5e6f
Create Date: 2026-10-08 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists, table_exists

revision: str = "ptr3c4d5e6f7a"
down_revision: Union[str, None] = "ptr2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "chat_messages"
COLUMN = "source_language"


def _source_language_is_enum(bind) -> bool:
    row = bind.execute(
        text(
            """
            SELECT data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
            """
        ),
        {"table": TABLE, "column": COLUMN},
    ).first()
    if row is None:
        return False
    data_type, udt_name = row[0], row[1]
    return data_type == "USER-DEFINED" and udt_name == "languagecode"


def upgrade() -> None:
    if not table_exists(TABLE) or not column_exists(TABLE, COLUMN):
        return
    bind = op.get_bind()
    if not _source_language_is_enum(bind):
        return
    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=postgresql.ENUM(
            "EN",
            "BO",
            "ZH",
            "HI",
            "NE",
            "MN",
            "LA",
            name="languagecode",
            create_type=False,
        ),
        type_=sa.String(length=2),
        postgresql_using=f"{COLUMN}::text",
        existing_nullable=True,
    )


def downgrade() -> None:
    if not table_exists(TABLE) or not column_exists(TABLE, COLUMN):
        return
    bind = op.get_bind()
    if _source_language_is_enum(bind):
        return
    op.execute(
        text(
            f"""
            UPDATE {TABLE}
            SET {COLUMN} = NULL
            WHERE {COLUMN} IS NOT NULL
              AND {COLUMN} NOT IN ('EN', 'BO', 'ZH', 'HI', 'NE', 'MN', 'LA')
            """
        )
    )
    op.alter_column(
        TABLE,
        COLUMN,
        existing_type=sa.String(length=2),
        type_=postgresql.ENUM(
            "EN",
            "BO",
            "ZH",
            "HI",
            "NE",
            "MN",
            "LA",
            name="languagecode",
            create_type=False,
        ),
        postgresql_using=f"{COLUMN}::languagecode",
        existing_nullable=True,
    )
