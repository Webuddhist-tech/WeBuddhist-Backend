from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Boolean, UUID, Text, Index, text
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base
from pecha_api.plans.platform_enums import PlatformRoleEnum
from uuid import uuid4
import _datetime
from _datetime import datetime

class Author(Base):
    __tablename__ = "authors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    first_name = Column(String(200), nullable=False)
    last_name = Column(String(200), nullable=False)
    bio = Column(Text, nullable=True)
    image_url = Column(String(1000), nullable=True)
    email = Column(String(255), nullable=True, unique=True, index=True)
    phone_number = Column(String(16), nullable=True, unique=True, index=True)
    password = Column(String(255), nullable=True)
    # Links this Author to its owner's website (Users) account. Set only
    # through a verified linking flow (e.g. accepting a group invite while
    # authenticated as the User whose verified email matches the invite),
    # never inferred from a token's own email/phone claims - see
    # validate_and_extract_author_details for why that distinction matters.
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False)
    platform_role = Column(PlatformRoleEnum, nullable=False, default="CREATOR")
    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc),nullable=False)
    created_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255))
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(String(255))

    # Relationship with author social media accounts
    social_media_accounts = relationship("AuthorSocialMediaAccount", back_populates="author", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_authors_verified", "is_verified", postgresql_where=text("is_verified = TRUE")),
    )

class AuthorPasswordReset(Base):
    __tablename__ = "author_password_resets"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, ForeignKey("authors.email", ondelete="CASCADE"), nullable=False)
    reset_token = Column(String(255), nullable=False, unique=True, index=True)
    token_expiry = Column(DateTime(timezone=True), nullable=False)


class AuthorSocialMediaAccount(Base):
    __tablename__ = "author_social_media_accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    author_id = Column(UUID(as_uuid=True), ForeignKey('authors.id', ondelete='CASCADE'), nullable=False)
    platform_name = Column(String(100), nullable=False)
    profile_url = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    
    # Relationship back to author
    author = relationship("Author", back_populates="social_media_accounts")