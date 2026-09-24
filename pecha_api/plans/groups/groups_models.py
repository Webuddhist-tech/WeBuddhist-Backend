from _datetime import datetime
import _datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UUID,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base

from .groups_enums import (
    AuthorGroupMemberRoleEnum,
    AuthorGroupInviteStatusEnum,
    AuthorGroupJoinRequestStatusEnum,
    AuthorGroupStatusEnum,
    AuthorGroupTypeEnum,
)

FK_AUTHOR_GROUPS_ID = "author_groups.id"
CASCADE_DELETE_ORPHAN = "all, delete-orphan"


author_group_followers = Table(
    "author_group_followers",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        nullable=False,
    ),
    UniqueConstraint("group_id", "user_id", name="uq_author_group_followers_group_user"),
)


author_group_joins = Table(
    "author_group_joins",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        nullable=False,
    ),
    UniqueConstraint("group_id", "user_id", name="uq_author_group_joins_group_user"),
)


author_group_tags = Table(
    "author_group_tags",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    UniqueConstraint("group_id", "tag_id", name="uq_author_group_tags_group_tag"),
)


author_group_series = Table(
    "author_group_series",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "series_id",
        UUID(as_uuid=True),
        ForeignKey("series.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    UniqueConstraint("group_id", "series_id", name="uq_author_group_series_group_series"),
)


author_group_plans = Table(
    "author_group_plans",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "plan_id",
        UUID(as_uuid=True),
        ForeignKey("plans.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    UniqueConstraint("group_id", "plan_id", name="uq_author_group_plans_group_plan"),
)


class AuthorGroup(Base):
    __tablename__ = "author_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug = Column(String(255), nullable=False)
    group_type = Column(AuthorGroupTypeEnum, nullable=False, default="PAGE")
    is_public = Column(Boolean, nullable=False, default=True)
    status = Column(AuthorGroupStatusEnum, nullable=False, default="DRAFT")
    avatar_key = Column(String(1000), nullable=True)
    banner_key = Column(String(1000), nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False
    )
    created_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(255), nullable=True)

    metadata_entries = relationship(
        "AuthorGroupMetadata",
        back_populates="group",
        cascade=CASCADE_DELETE_ORPHAN,
    )
    members = relationship(
        "AuthorGroupMember",
        back_populates="group",
        cascade=CASCADE_DELETE_ORPHAN,
    )
    social_links = relationship(
        "AuthorGroupSocialLink",
        back_populates="group",
        cascade=CASCADE_DELETE_ORPHAN,
    )
    tags = relationship("Tag", secondary=author_group_tags, lazy="select")
    followers = relationship("Users", secondary=author_group_followers, lazy="select")
    joiners = relationship("Users", secondary=author_group_joins, lazy="select")

    __table_args__ = (
        Index(
            "idx_author_groups_slug",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class AuthorGroupMetadata(Base):
    __tablename__ = "author_group_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    language = Column(String(10), nullable=False)
    title = Column(String(255), nullable=False)
    sub_title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    description_long = Column(Text, nullable=True)

    group = relationship("AuthorGroup", back_populates="metadata_entries")

    __table_args__ = (
        UniqueConstraint("group_id", "language", name="uq_author_group_metadata_group_language"),
        Index("idx_author_group_metadata_group_language", "group_id", "language"),
    )


class AuthorGroupMember(Base):
    __tablename__ = "author_group_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    author_id = Column(
        UUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(AuthorGroupMemberRoleEnum, nullable=False, default="AUTHOR")
    created_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False
    )
    created_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255), nullable=True)

    group = relationship("AuthorGroup", back_populates="members")
    author = relationship("Author")

    __table_args__ = (
        UniqueConstraint("group_id", "author_id", name="uq_author_group_members_group_author"),
        Index("idx_author_group_members_group_author", "group_id", "author_id"),
        Index(
            "uq_author_group_members_one_owner_per_group",
            "group_id",
            unique=True,
            postgresql_where=text("role = 'OWNER'"),
        ),
    )


class AuthorGroupSocialLink(Base):
    __tablename__ = "author_group_social_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    platform = Column(String(50), nullable=False)
    url = Column(String(1000), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))

    group = relationship("AuthorGroup", back_populates="social_links")


class AuthorGroupInvite(Base):
    __tablename__ = "author_group_invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    target_email = Column(String(255), nullable=False)
    role = Column(AuthorGroupMemberRoleEnum, nullable=False, default="AUTHOR")
    status = Column(AuthorGroupInviteStatusEnum, nullable=False, default="PENDING")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False
    )
    created_by = Column(String(255), nullable=False)

    group = relationship("AuthorGroup")

    __table_args__ = (
        Index("idx_author_group_invites_target_email", "target_email"),
        Index("idx_author_group_invites_group_status", "group_id", "status"),
        Index("idx_author_group_invites_target_email_status", "target_email", "status"),
    )


class AuthorGroupJoinRequest(Base):
    """An app user's request to join a private COMMUNITY group, reviewed in Studio."""

    __tablename__ = "author_group_join_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message = Column(Text, nullable=True)
    status = Column(AuthorGroupJoinRequestStatusEnum, nullable=False, default="PENDING")
    reviewed_by = Column(
        UUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    notification_sqs_message_id = Column(String(128), nullable=True)
    notification_dispatched_at = Column(DateTime(timezone=True), nullable=True)
    decision_sqs_message_id = Column(String(128), nullable=True)
    decision_dispatched_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), nullable=True)

    group = relationship("AuthorGroup")
    user = relationship("Users")

    __table_args__ = (
        Index("idx_author_group_join_requests_group_status", "group_id", "status"),
        Index("idx_author_group_join_requests_user_status", "user_id", "status"),
        Index(
            "uq_author_group_join_requests_pending_group_user",
            "group_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )


class AuthorGroupBan(Base):
    """A time-boxed block on an app user rejoining a COMMUNITY group.

    Written by a group OWNER/ADMIN from Studio when they remove a joined user.
    A ban is active while `lifted_at` is null and `expires_at` is in the future;
    expired rows are left in place as an audit trail rather than being deleted,
    so the active-ban lookup always filters on both columns.
    """

    __tablename__ = "author_group_bans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    lifted_at = Column(DateTime(timezone=True), nullable=True)
    lifted_by = Column(
        UUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="SET NULL"),
        nullable=True,
    )

    group = relationship("AuthorGroup")
    user = relationship("Users", foreign_keys=[user_id])

    __table_args__ = (
        Index("idx_author_group_bans_group_user", "group_id", "user_id"),
        Index("idx_author_group_bans_group_expires", "group_id", "expires_at"),
        Index("idx_author_group_bans_user_expires", "user_id", "expires_at"),
    )
