"""add location_metadata table for localized location names

Revision ID: loc1a2b3c4d5e
Revises: evt4c5d6e7f8a
Create Date: 2026-09-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotency import index_exists, table_exists

# revision identifiers, used by Alembic.
revision: str = "loc1a2b3c4d5e"
down_revision: Union[str, None] = "evt4c5d6e7f8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One row per language a location has a name in. `locations.name` stays
    # the canonical name and the fallback, so nothing here is required.
    if not table_exists("location_metadata"):
        op.create_table(
            "location_metadata",
            sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
            sa.Column("location_id", sa.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column(
                "language",
                # The type is already in place from the event metadata tables.
                postgresql.ENUM(
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
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["location_id"], ["locations.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "location_id",
                "language",
                name="uq_location_metadata_location_language",
            ),
        )

    if not index_exists("location_metadata", "idx_location_metadata_location_language"):
        op.create_index(
            "idx_location_metadata_location_language",
            "location_metadata",
            ["location_id", "language"],
        )


def downgrade() -> None:
    if index_exists("location_metadata", "idx_location_metadata_location_language"):
        op.drop_index(
            "idx_location_metadata_location_language",
            table_name="location_metadata",
        )
    if table_exists("location_metadata"):
        op.drop_table("location_metadata")
