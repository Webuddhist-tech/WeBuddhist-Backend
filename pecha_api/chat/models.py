from datetime import datetime
import datetime as dt
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base

from .enums import ChatMessageTypeEnum, ChatRoomMemberRoleEnum

FK_AUTHOR_GROUPS_ID = "author_groups.id"
FK_USERS_ID = "users.id"
FK_EVENTS_ID = "events.id"
FK_CHAT_ROOMS_ID = "chat_rooms.id"
FK_CHAT_MESSAGES_ID = "chat_messages.id"
CASCADE_DELETE_ORPHAN = "all, delete-orphan"
CREATED_AT_DESC = "created_at DESC"


class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_AUTHOR_GROUPS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_EVENTS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    sender_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    receiver_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    name = Column(String(255), nullable=False)
    img_url = Column(String(1000), nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    members = relationship(
        "ChatRoomMember",
        back_populates="room",
        cascade=CASCADE_DELETE_ORPHAN,
    )
    messages = relationship(
        "ChatMessage",
        back_populates="room",
        cascade=CASCADE_DELETE_ORPHAN,
    )

    __table_args__ = (
        # Three mutually exclusive shapes: a group's room, an event's room, or
        # a DM pair. Every row that satisfied the two-shape version still does.
        CheckConstraint(
            "(group_id IS NOT NULL AND event_id IS NULL AND sender_id IS NULL AND receiver_id IS NULL) OR "
            "(event_id IS NOT NULL AND group_id IS NULL AND sender_id IS NULL AND receiver_id IS NULL) OR "
            "(group_id IS NULL AND event_id IS NULL AND sender_id IS NOT NULL AND receiver_id IS NOT NULL "
            "AND sender_id <> receiver_id)",
            name="ck_chat_rooms_kind_shape",
        ),
        Index(
            "uq_chat_rooms_group_id",
            "group_id",
            unique=True,
            postgresql_where=sql_text("group_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_chat_rooms_event_id",
            "event_id",
            unique=True,
            postgresql_where=sql_text("event_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_chat_rooms_sender_receiver",
            "sender_id",
            "receiver_id",
            unique=True,
            postgresql_where=sql_text(
                "group_id IS NULL AND event_id IS NULL AND deleted_at IS NULL"
            ),
        ),
        Index("idx_chat_rooms_updated_at", sql_text("updated_at DESC")),
        Index("idx_chat_rooms_created_by", "created_by"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_CHAT_ROOMS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    sender_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    parent_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_CHAT_MESSAGES_ID, ondelete="SET NULL"),
        nullable=True,
    )
    body = Column(Text, nullable=False)
    message_type = Column(
        ChatMessageTypeEnum,
        nullable=False,
        default="TEXT",
        server_default="TEXT",
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    notification_sqs_message_id = Column(String(128), nullable=True)
    notification_dispatched_at = Column(DateTime(timezone=True), nullable=True)

    room = relationship("ChatRoom", back_populates="messages")
    sender = relationship("Users")
    parent = relationship("ChatMessage", remote_side="ChatMessage.id", foreign_keys=[parent_message_id])
    reactions = relationship(
        "ChatMessageReaction",
        back_populates="message",
        cascade=CASCADE_DELETE_ORPHAN,
    )
    prayers = relationship(
        "ChatMessagePrayer",
        back_populates="message",
        cascade=CASCADE_DELETE_ORPHAN,
    )

    __table_args__ = (
        Index("idx_chat_messages_room_created", "room_id", sql_text(CREATED_AT_DESC)),
        # Backs the "Prayer requests" tab: one room's prayer requests, newest first.
        Index(
            "idx_chat_messages_room_prayers",
            "room_id",
            sql_text(CREATED_AT_DESC),
            postgresql_where=sql_text(
                "message_type = 'PRAYER' AND deleted_at IS NULL"
            ),
        ),
        Index(
            "idx_chat_messages_room_active",
            "room_id",
            "created_at",
            postgresql_where=sql_text("deleted_at IS NULL"),
        ),
        Index(
            "idx_chat_messages_undispatched_notifications",
            "created_at",
            postgresql_where=sql_text(
                "deleted_at IS NULL AND notification_sqs_message_id IS NULL"
            ),
        ),
    )


class ChatRoomMember(Base):
    __tablename__ = "chat_room_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_CHAT_ROOMS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(ChatRoomMemberRoleEnum, nullable=False, default="MEMBER")
    last_read_at = Column(DateTime(timezone=True), nullable=True)
    joined_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    left_at = Column(DateTime(timezone=True), nullable=True)

    room = relationship("ChatRoom", back_populates="members")
    user = relationship("Users")

    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="uq_chat_room_members_room_user"),
        Index("idx_chat_room_members_room_id", "room_id"),
        Index("idx_chat_room_members_user_id", "user_id"),
    )


class ChatMessageReaction(Base):
    __tablename__ = "chat_message_reactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_CHAT_MESSAGES_ID, ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    emoji = Column(String(16), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )

    message = relationship("ChatMessage", back_populates="reactions")
    user = relationship("Users")

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            "emoji",
            name="uq_chat_message_reactions_message_user_emoji",
        ),
        Index("idx_chat_message_reactions_message_id", "message_id"),
    )


class ChatMessagePrayer(Base):
    """One person praying for one prayer request.

    Deliberately separate from ChatMessageReaction: a prayer is an intention
    record, counted and listed on its own terms, not an emoji whose meaning
    could change.
    """

    __tablename__ = "chat_message_prayers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_CHAT_MESSAGES_ID, ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    notification_sqs_message_id = Column(String(128), nullable=True)
    notification_dispatched_at = Column(DateTime(timezone=True), nullable=True)

    message = relationship("ChatMessage", back_populates="prayers")
    user = relationship("Users")

    __table_args__ = (
        # One prayer per person per request; what makes the batch endpoint idempotent.
        UniqueConstraint(
            "message_id",
            "user_id",
            name="uq_chat_message_prayers_message_user",
        ),
        Index("idx_chat_message_prayers_message_id", "message_id"),
        Index(
            "idx_chat_message_prayers_user_created",
            "user_id",
            sql_text(CREATED_AT_DESC),
        ),
        Index(
            "idx_chat_message_prayers_undispatched",
            "created_at",
            postgresql_where=sql_text("notification_sqs_message_id IS NULL"),
        ),
    )


class ChatMessageReport(Base):
    __tablename__ = "chat_message_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # MANUAL reports point at a stored message; AUTOMATIC (system) reports are
    # filed for rejected messages that were never stored, so message_id and
    # reporter_id are absent and message_text/room_id carry the context instead.
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_CHAT_MESSAGES_ID, ondelete="CASCADE"),
        nullable=True,
    )
    reporter_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    reported_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_CHAT_ROOMS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    source = Column(String(16), nullable=False, default="MANUAL", server_default="MANUAL")
    message_text = Column(Text, nullable=True)
    reason = Column(String(32), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    message = relationship("ChatMessage", foreign_keys=[message_id])
    reporter = relationship("Users", foreign_keys=[reporter_id])
    reported_user = relationship("Users", foreign_keys=[reported_user_id])
    room = relationship("ChatRoom", foreign_keys=[room_id])

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "reporter_id",
            name="uq_chat_message_reports_message_reporter",
        ),
        CheckConstraint(
            "(source = 'MANUAL' AND message_id IS NOT NULL AND reporter_id IS NOT NULL) OR "
            "(source = 'AUTOMATIC' AND reported_user_id IS NOT NULL)",
            name="ck_chat_message_reports_source_shape",
        ),
        Index("idx_chat_message_reports_message_id", "message_id"),
        Index("idx_chat_message_reports_reported_user", "reported_user_id"),
        # One open automatic report per (room, user, text): the service dedupes
        # with a lookup first, but only this index makes concurrent identical
        # submissions safe. md5() keeps arbitrarily long texts within btree
        # index limits.
        Index(
            "uq_chat_message_reports_auto_unresolved",
            "room_id",
            "reported_user_id",
            sql_text("md5(message_text)"),
            unique=True,
            postgresql_where=sql_text("source = 'AUTOMATIC' AND resolved_at IS NULL"),
        ),
        Index(
            "idx_chat_message_reports_unresolved",
            "created_at",
            postgresql_where=sql_text("resolved_at IS NULL"),
        ),
    )
