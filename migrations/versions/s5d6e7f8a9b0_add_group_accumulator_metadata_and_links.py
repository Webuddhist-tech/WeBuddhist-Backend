"""add group_accumulator_metadata and group_accumulator_links

Revision ID: s5d6e7f8a9b0
Revises: r4c5d6e7f8a9
Create Date: 2026-09-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "s5d6e7f8a9b0"
down_revision: Union[str, None] = "r4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reuses the existing languagecode enum.
    op.create_table(
        "group_accumulator_metadata",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("group_accumulator_id", sa.UUID(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "language",
            postgresql.ENUM(name="languagecode", create_type=False),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["group_accumulator_id"], ["group_accumulators.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_accumulator_id",
            "language",
            name="uq_group_accumulator_metadata_language",
        ),
    )
    op.create_index(
        "idx_group_accumulator_metadata_group_accumulator_id",
        "group_accumulator_metadata",
        ["group_accumulator_id"],
        unique=False,
    )

    group_accumulator_link_type = postgresql.ENUM(
        "YOUTUBE", "LINK", name="group_accumulator_link_type"
    )
    group_accumulator_link_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "group_accumulator_links",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("group_accumulator_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "link_type",
            postgresql.ENUM(
                "YOUTUBE", "LINK", name="group_accumulator_link_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("video_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["group_accumulator_id"], ["group_accumulators.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_group_accumulator_links_group_accumulator_id",
        "group_accumulator_links",
        ["group_accumulator_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_group_accumulator_links_group_accumulator_id",
        table_name="group_accumulator_links",
    )
    op.drop_table("group_accumulator_links")
    postgresql.ENUM(name="group_accumulator_link_type").drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        "idx_group_accumulator_metadata_group_accumulator_id",
        table_name="group_accumulator_metadata",
    )
    op.drop_table("group_accumulator_metadata")
