from typing import Optional, Set
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
from pecha_api.plans.groups.groups_models import AuthorGroupMember
from pecha_api.plans.groups.groups_repository import get_group_member
from pecha_api.plans.platform_enums import PlatformRole
from pecha_api.plans.plans_enums import PlanStatus

_CONTENT_PUBLISHED_READ_ONLY = "CONTENT_PUBLISHED_READ_ONLY"
_STATUS_CHANGE_FORBIDDEN = "STATUS_CHANGE_FORBIDDEN"
_NO_GROUP_MEMBERSHIP = "NO_GROUP_MEMBERSHIP"
_AUTHOR_NOT_ACTIVE = "AUTHOR_NOT_ACTIVE"
_FORBIDDEN = "FORBIDDEN"

_CONTENT_CREATE_ROLES = {
    AuthorGroupMemberRole.OWNER,
    AuthorGroupMemberRole.ADMIN,
    AuthorGroupMemberRole.AUTHOR,
}
_CONTENT_EDIT_ROLES = _CONTENT_CREATE_ROLES
_STATUS_CHANGE_ROLES = {AuthorGroupMemberRole.OWNER, AuthorGroupMemberRole.ADMIN}
_TRANSFER_REQUEST_ROLES = _STATUS_CHANGE_ROLES
_TRANSFER_RESPOND_ROLES = _STATUS_CHANGE_ROLES
_READ_ROLES = {
    AuthorGroupMemberRole.OWNER,
    AuthorGroupMemberRole.ADMIN,
    AuthorGroupMemberRole.AUTHOR,
    AuthorGroupMemberRole.VIEWER,
}


def _role_value(role) -> str:
    if hasattr(role, "value"):
        return role.value
    return str(role)


def get_platform_role(author: Author) -> PlatformRole:
    raw = getattr(author, "platform_role", None)
    if raw is None:
        return PlatformRole.CREATOR
    if isinstance(raw, PlatformRole):
        return raw
    return PlatformRole(_role_value(raw))


def is_super_admin(author: Author) -> bool:
    return get_platform_role(author) == PlatformRole.SUPER_ADMIN


def is_reviewer(author: Author) -> bool:
    return get_platform_role(author) == PlatformRole.REVIEWER


def is_platform_read_only(author: Author) -> bool:
    return is_reviewer(author)


def require_active_author(author: Author) -> None:
    if not author.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_AUTHOR_NOT_ACTIVE,
        )


def require_super_admin(author: Author) -> None:
    if not is_super_admin(author):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN)


def require_super_admin_or_reviewer(author: Author) -> None:
    role = get_platform_role(author)
    if role not in {PlatformRole.SUPER_ADMIN, PlatformRole.REVIEWER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN)


def require_cms_write_access(author: Author) -> None:
    if is_platform_read_only(author):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_FORBIDDEN)


def _normalize_member_role(member: Optional[AuthorGroupMember]) -> Optional[AuthorGroupMemberRole]:
    if member is None:
        return None
    raw = member.role
    if isinstance(raw, AuthorGroupMemberRole):
        return raw
    return AuthorGroupMemberRole(_role_value(raw))


def get_member_role(
    db: Session,
    group_id: UUID,
    author_id: UUID,
) -> Optional[AuthorGroupMemberRole]:
    member = get_group_member(db=db, group_id=group_id, author_id=author_id)
    return _normalize_member_role(member)


def require_group_member(
    db: Session,
    group_id: UUID,
    author: Author,
    allowed_roles: Set[AuthorGroupMemberRole],
) -> AuthorGroupMemberRole:
    if is_super_admin(author):
        return AuthorGroupMemberRole.OWNER
    member_role = get_member_role(db=db, group_id=group_id, author_id=author.id)
    if member_role is None or member_role not in allowed_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_NO_GROUP_MEMBERSHIP)
    return member_role


def require_can_read_group_content(
    db: Session,
    group_id: UUID,
    author: Author,
) -> None:
    if is_super_admin(author) or is_reviewer(author):
        return
    require_group_member(db=db, group_id=group_id, author=author, allowed_roles=_READ_ROLES)


def require_can_create_content(
    db: Session,
    group_id: UUID,
    author: Author,
) -> None:
    require_cms_write_access(author)
    require_group_member(db=db, group_id=group_id, author=author, allowed_roles=_CONTENT_CREATE_ROLES)


def _normalize_plan_status(status_value) -> PlanStatus:
    if isinstance(status_value, PlanStatus):
        return status_value
    if hasattr(status_value, "value"):
        return PlanStatus(status_value.value)
    return PlanStatus(status_value)


def can_create_group_content(member_role: Optional[AuthorGroupMemberRole]) -> bool:
    """Same role set require_can_create_content enforces (OWNER/ADMIN/AUTHOR)
    - exposed as a plain predicate for callers that report permissions
    rather than gate an action (e.g. GET /users/me/permission/{group_id})."""
    return member_role in _CONTENT_CREATE_ROLES


def can_edit_content(member_role: AuthorGroupMemberRole, content_status) -> bool:
    status_enum = _normalize_plan_status(content_status)
    if member_role in _STATUS_CHANGE_ROLES:
        return True
    if member_role == AuthorGroupMemberRole.AUTHOR:
        return status_enum == PlanStatus.DRAFT
    return False


def require_can_edit_content(
    db: Session,
    group_id: UUID,
    author: Author,
    content_status,
) -> AuthorGroupMemberRole:
    require_cms_write_access(author)
    if is_super_admin(author):
        return AuthorGroupMemberRole.OWNER
    member_role = require_group_member(
        db=db,
        group_id=group_id,
        author=author,
        allowed_roles=_CONTENT_EDIT_ROLES,
    )
    if not can_edit_content(member_role=member_role, content_status=content_status):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_CONTENT_PUBLISHED_READ_ONLY,
        )
    return member_role


def require_can_change_status(
    db: Session,
    group_id: UUID,
    author: Author,
) -> None:
    require_cms_write_access(author)
    if is_super_admin(author):
        return
    require_group_member(
        db=db,
        group_id=group_id,
        author=author,
        allowed_roles=_STATUS_CHANGE_ROLES,
    )


def require_can_request_transfer(
    db: Session,
    from_group_id: UUID,
    author: Author,
) -> None:
    require_cms_write_access(author)
    if is_super_admin(author):
        return
    require_group_member(
        db=db,
        group_id=from_group_id,
        author=author,
        allowed_roles=_TRANSFER_REQUEST_ROLES,
    )


def require_can_respond_transfer(
    db: Session,
    to_group_id: UUID,
    author: Author,
) -> None:
    require_cms_write_access(author)
    if is_super_admin(author):
        return
    require_group_member(
        db=db,
        group_id=to_group_id,
        author=author,
        allowed_roles=_TRANSFER_RESPOND_ROLES,
    )


def author_has_any_group(db: Session, author_id: UUID) -> bool:
    return (
        db.query(AuthorGroupMember.id)
        .filter(AuthorGroupMember.author_id == author_id)
        .first()
        is not None
    )


def build_author_access_context(db: Session, author: Author) -> dict:
    has_group = author_has_any_group(db=db, author_id=author.id)
    role = get_platform_role(author)
    can_create_content = (
        bool(author.is_active)
        and has_group
        and role in {PlatformRole.CREATOR, PlatformRole.SUPER_ADMIN}
    )
    return {
        "platform_role": role,
        "is_verified": bool(author.is_verified),
        "is_active": bool(author.is_active),
        "has_group": has_group,
        "can_create_content": can_create_content,
    }
