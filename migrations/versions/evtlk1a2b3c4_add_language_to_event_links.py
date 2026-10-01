"""add_language_to_event_links

Revision ID: evtlk1a2b3c4
Revises: 0f3617ef0e23
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotency import column_exists, index_exists

revision: str = 'evtlk1a2b3c4'
down_revision: Union[str, None] = '0f3617ef0e23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LANGUAGECODE_VALUES = ("EN", "BO", "ZH", "HI", "NE", "MN", "LA")


def upgrade() -> None:
    if not column_exists("event_links", "language"):
        op.add_column(
            "event_links",
            sa.Column(
                "language",
                postgresql.ENUM(*LANGUAGECODE_VALUES, name="languagecode", create_type=False),
                nullable=True,
            ),
        )
        op.execute("UPDATE event_links SET language = 'EN'")
        op.alter_column("event_links", "language", nullable=False, server_default="EN")

    if not index_exists("event_links", "idx_event_links_event_language"):
        op.create_index(
            "idx_event_links_event_language",
            "event_links",
            ["event_id", "language"],
            unique=False,
        )


def downgrade() -> None:
    if index_exists("event_links", "idx_event_links_event_language"):
        op.drop_index("idx_event_links_event_language", table_name="event_links")
    if column_exists("event_links", "language"):
        op.drop_column("event_links", "language")
