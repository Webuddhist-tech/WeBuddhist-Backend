from sqlalchemy import Column, Integer, String, DateTime, Boolean, UUID, ForeignKey
from ..db.database import Base
from _datetime import datetime
from uuid import uuid4
import _datetime
from sqlalchemy.orm import relationship


class Users(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    auth0_id = Column(String(255), unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    phone_number = Column(String(16), unique=True, index=True, nullable=True)
    firstname = Column(String(255), nullable=False)
    lastname = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    registration_source = Column(String(25), nullable=False)
    title = Column(String(255),nullable=True)
    organization = Column(String(255),nullable=True)
    location = Column(String(255),nullable=True)
    education = Column(String(255),nullable=True)
    about_me = Column(String,nullable=True)
    avatar_url = Column(String(2048),nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, server_default="FALSE", default=False,nullable=False)
    has_seen_onboarding = Column(Boolean, server_default="FALSE", default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.now(_datetime.timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(_datetime.timezone.utc))
    # Backend tokens issued at or before this are rejected (see user_resolution).
    tokens_valid_after = Column(DateTime(timezone=True), nullable=True)

    # Define the relationship between users and social media accounts
    social_media_accounts = relationship("SocialMediaAccount", back_populates="user", cascade="all, delete-orphan")


class SocialMediaAccount(Base):
    __tablename__ = "social_media_accounts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    platform_name = Column(String(100), nullable=False)
    profile_url = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.now(_datetime.timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(_datetime.timezone.utc))
    user = relationship("Users", back_populates="social_media_accounts")

class PasswordReset(Base):
    __tablename__ = "password_resets"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, ForeignKey("users.email", ondelete="CASCADE"), nullable=False)
    reset_token = Column(String(255), nullable=False, unique=True, index=True)
    token_expiry = Column(DateTime(timezone=True), nullable=False)
