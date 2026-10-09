import enum

from sqlalchemy import Enum


class PlatformRole(enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    REVIEWER = "REVIEWER"
    CREATOR = "CREATOR"
    # A creator who also manages the app-wide content catalogues (verse of the
    # day, poems, text audio, tags, ...). Like a creator, they see only the
    # plans and spaces they belong to; they do not get the super admin's
    # view of all of them, nor its user/moderation administration.
    CONTENT_ADMIN = "CONTENT_ADMIN"


PlatformRoleEnum = Enum(PlatformRole, name="platform_role")
