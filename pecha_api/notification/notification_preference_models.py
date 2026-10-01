from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    UUID,
)

from pecha_api.db.database import Base
from pecha_api.notification.notification_preference_enums import (
    NotificationChannelEnum,
    NotificationScopeEnum,
    NotificationTypeEnum,
)


class UserNotificationPreference(Base):
    """A single preference the user has changed. No row means allowed."""

    __tablename__ = "user_notification_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    notification_type = Column(NotificationTypeEnum, nullable=False)
    channel = Column(NotificationChannelEnum, nullable=False, server_default="PUSH")
    scope_type = Column(NotificationScopeEnum, nullable=False, server_default="GLOBAL")
    scope_id = Column(UUID(as_uuid=True), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    muted_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # Postgres does not dedupe NULLs, so global and scoped rows need
        # separate partial unique indexes.
        Index(
            "uq_user_notif_pref_global",
            "user_id",
            "notification_type",
            "channel",
            unique=True,
            postgresql_where=(scope_id.is_(None)),
        ),
        Index(
            "uq_user_notif_pref_scoped",
            "user_id",
            "notification_type",
            "channel",
            "scope_type",
            "scope_id",
            unique=True,
            postgresql_where=(scope_id.isnot(None)),
        ),
        Index(
            "idx_user_notif_pref_lookup",
            "notification_type",
            "channel",
            "user_id",
        ),
        # Written as an equivalence so new scope values need no constraint change.
        CheckConstraint(
            "(scope_type = 'GLOBAL') = (scope_id IS NULL)",
            name="ck_user_notif_pref_scope",
        ),
    )
