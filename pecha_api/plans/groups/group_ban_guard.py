"""The rejoin check for a user removed from a group.

This lives apart from `groups_service` on purpose. The accumulator join path
needs the same check, and `groups_service` already imports from
`group_accumulator_service`, so calling into it from there would close an import
cycle. This module depends on the repository only.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.plans.groups.groups_repository import get_active_group_ban


def _as_aware_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def get_group_ban_expiry(
    db: Session,
    *,
    group_id: UUID,
    user_id: UUID,
) -> Optional[datetime]:
    """When the user's ban on this group lifts, or None if they are not banned."""
    ban = get_active_group_ban(db=db, group_id=group_id, user_id=user_id)
    return _as_aware_utc(ban.expires_at) if ban else None


def assert_user_not_banned_from_group(
    db: Session,
    *,
    group_id: UUID,
    user_id: UUID,
) -> None:
    """Block a removed user from coming back before their ban expires.

    Called from every path that can put a user back into `author_group_joins`:
    joining directly, requesting to join a private group, and joining one of the
    group's accumulators (which joins the parent group as a side effect).
    """
    expires_at = get_group_ban_expiry(db=db, group_id=group_id, user_id=user_id)
    if expires_at is None:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "GROUP_BANNED",
            "message": (
                "You were removed from this group and cannot rejoin until "
                f"{expires_at.strftime('%d %b %Y')}"
            ),
            "expires_at": expires_at.isoformat(),
        },
    )
