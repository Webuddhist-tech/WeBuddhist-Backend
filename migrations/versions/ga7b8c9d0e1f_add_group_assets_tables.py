"""add group_assets and recitation item asset link tables

Revision ID: ga7b8c9d0e1f
Revises: am1b2c3d4e5f
Create Date: 2026-09-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.idempotency import enum_exists, index_exists, table_exists

revision: str = "ga7b8c9d0e1f"
down_revision: Union[str, None] = "am1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GROUP_ASSET_TYPE = "group_asset_type"


def upgrade() -> None:
    if not enum_exists(GROUP_ASSET_TYPE):
        postgresql.ENUM(
            "AUDIO",
            "IMAGE",
            "VIDEO",
            name=GROUP_ASSET_TYPE,
        ).create(op.get_bind())

    asset_type_enum = postgresql.ENUM(
        "AUDIO",
        "IMAGE",
        "VIDEO",
        name=GROUP_ASSET_TYPE,
        create_type=False,
    )

    if not table_exists("group_assets"):
        op.create_table(
            "group_assets",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("asset_type", asset_type_enum, nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("s3_key", sa.String(length=1000), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("mime_type", sa.String(length=64), nullable=True),
            sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(
                ["group_id"],
                ["author_groups.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not index_exists("group_assets", "idx_group_assets_group_type"):
        op.create_index(
            "idx_group_assets_group_type",
            "group_assets",
            ["group_id", "asset_type"],
            unique=False,
        )

    if not index_exists("group_assets", "uq_group_assets_group_s3_key"):
        op.create_index(
            "uq_group_assets_group_s3_key",
            "group_assets",
            ["group_id", "s3_key"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )

    if not table_exists("group_recitation_collection_item_assets"):
        op.create_table(
            "group_recitation_collection_item_assets",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("display_order", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.ForeignKeyConstraint(
                ["item_id"],
                ["group_recitation_collection_items.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["asset_id"],
                ["group_assets.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "item_id", "asset_id", name="uq_group_recitation_item_assets_item_asset"
            ),
            sa.UniqueConstraint(
                "item_id",
                "display_order",
                name="uq_group_recitation_item_assets_item_order",
            ),
        )

    if not index_exists(
        "group_recitation_collection_item_assets",
        "idx_group_recitation_item_assets_item_id",
    ):
        op.create_index(
            "idx_group_recitation_item_assets_item_id",
            "group_recitation_collection_item_assets",
            ["item_id"],
            unique=False,
        )

    if not index_exists(
        "group_recitation_collection_item_assets",
        "idx_group_recitation_item_assets_asset_id",
    ):
        op.create_index(
            "idx_group_recitation_item_assets_asset_id",
            "group_recitation_collection_item_assets",
            ["asset_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        "idx_group_recitation_item_assets_asset_id",
        table_name="group_recitation_collection_item_assets",
    )
    op.drop_index(
        "idx_group_recitation_item_assets_item_id",
        table_name="group_recitation_collection_item_assets",
    )
    op.drop_table("group_recitation_collection_item_assets")

    op.drop_index("uq_group_assets_group_s3_key", table_name="group_assets")
    op.drop_index("idx_group_assets_group_type", table_name="group_assets")
    op.drop_table("group_assets")

    postgresql.ENUM(name=GROUP_ASSET_TYPE).drop(op.get_bind())
