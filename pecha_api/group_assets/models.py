from datetime import datetime
import datetime as dt
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base

from .enums import GroupAssetTypeEnum

FK_AUTHOR_GROUPS_ID = "author_groups.id"
FK_GROUP_ASSETS_ID = "group_assets.id"
FK_GROUP_RECITATION_COLLECTION_ITEMS_ID = "group_recitation_collection_items.id"


class GroupAsset(Base):
    """A file owned by a group. Uploaded once, linked from anywhere in the group.

    This is the library half of the model: an asset outlives any single
    attachment, so it is an entity in its own right rather than a column on
    whatever happens to reference it first.
    """

    __tablename__ = "group_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    asset_type = Column(GroupAssetTypeEnum, nullable=False)
    title = Column(String(255), nullable=False)
    s3_key = Column(String(1000), nullable=False)
    file_name = Column(String(255), nullable=False)
    mime_type = Column(String(64), nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=True,
    )
    # Soft delete: links point here, so rows must not vanish underneath them.
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(String(255), nullable=False)
    updated_by = Column(String(255), nullable=True)

    __table_args__ = (
        Index("idx_group_assets_group_type", "group_id", "asset_type"),
        Index(
            "uq_group_assets_group_s3_key",
            "group_id",
            "s3_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class GroupRecitationCollectionItemAsset(Base):
    """Ordered link from a recitation collection item to a group asset.

    No deleted_at: a link is a fact about current state and the whole set is
    replaced atomically. The asset it points at holds the history.
    """

    __tablename__ = "group_recitation_collection_item_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_GROUP_RECITATION_COLLECTION_ITEMS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    # RESTRICT is a backstop, not the mechanism: assets are soft-deleted, and the
    # usage check in the delete service is what normally guards this.
    asset_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_GROUP_ASSETS_ID, ondelete="RESTRICT"),
        nullable=False,
    )
    display_order = Column(Integer, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    created_by = Column(String(255), nullable=False)

    asset = relationship("GroupAsset")

    __table_args__ = (
        UniqueConstraint(
            "item_id", "asset_id", name="uq_group_recitation_item_assets_item_asset"
        ),
        UniqueConstraint(
            "item_id", "display_order", name="uq_group_recitation_item_assets_item_order"
        ),
        Index("idx_group_recitation_item_assets_item_id", "item_id"),
        # "What uses this asset?" on the delete path.
        Index("idx_group_recitation_item_assets_asset_id", "asset_id"),
    )
