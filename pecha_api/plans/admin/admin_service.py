from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.plans.admin.admin_repository import count_super_admins, list_authors_admin, save_author
from pecha_api.plans.admin.admin_response_models import (
    AdminAuthorActivateResponse,
    AdminAuthorDetailDTO,
    AdminAuthorListItemDTO,
    AdminAuthorListResponse,
    AdminAuthorPlatformRoleUpdate,
)
from pecha_api.plans.auth.plan_auth_enums import AuthorStatus
from pecha_api.plans.auth.studio_access_service import account_status, on_author_activated_by_admin
from pecha_api.plans.authors.plan_authors_repository import get_author_by_id
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.platform_enums import PlatformRole
from pecha_api.plans.shared.permissions import (
    get_platform_role,
    is_super_admin,
    require_super_admin,
    require_super_admin_or_reviewer,
)
from pecha_api.uploads.S3_utils import generate_presigned_access_url


def _author_to_list_item(author) -> AdminAuthorListItemDTO:
    role = get_platform_role(author)
    return AdminAuthorListItemDTO(
        id=author.id,
        firstname=author.first_name,
        lastname=author.last_name,
        email=author.email,
        phone_number=author.phone_number,
        is_verified=bool(author.is_verified),
        is_active=bool(author.is_active),
        platform_role=role,
        created_at=author.created_at.isoformat() if author.created_at else None,
        account_status=account_status(author),
    )


def _isoformat(value) -> Optional[str]:
    return value.isoformat() if value else None


def _author_to_detail(author) -> AdminAuthorDetailDTO:
    image_url = None
    if author.image_url:
        image_url = generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=author.image_url,
        )
    return AdminAuthorDetailDTO(
        id=author.id,
        firstname=author.first_name,
        lastname=author.last_name,
        email=author.email,
        phone_number=author.phone_number,
        is_verified=bool(author.is_verified),
        is_active=bool(author.is_active),
        platform_role=get_platform_role(author),
        bio=author.bio,
        image_url=image_url,
        account_status=account_status(author),
        suspended_at=_isoformat(author.suspended_at),
    )


def _guard_last_super_admin(db, author, new_role: Optional[PlatformRole] = None) -> None:
    if get_platform_role(author) != PlatformRole.SUPER_ADMIN:
        return
    if new_role == PlatformRole.SUPER_ADMIN:
        return
    if count_super_admins(db=db) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot demote or deactivate the last SuperAdmin",
        )


def list_admin_authors(
    token: str,
    skip: int,
    limit: int,
    is_verified: Optional[bool] = None,
    is_active: Optional[bool] = None,
    platform_role: Optional[PlatformRole] = None,
    search: Optional[str] = None,
    account_status_filter: Optional[AuthorStatus] = None,
) -> AdminAuthorListResponse:
    author = validate_and_extract_author_details(token=token)
    require_super_admin_or_reviewer(author)
    with SessionLocal() as db:
        rows, total = list_authors_admin(
            db=db,
            skip=skip,
            limit=limit,
            is_verified=is_verified,
            is_active=is_active,
            platform_role=platform_role,
            search=search,
            account_status=account_status_filter,
        )
    return AdminAuthorListResponse(
        authors=[_author_to_list_item(row) for row in rows],
        skip=skip,
        limit=limit,
        total=total,
    )


def get_admin_author_detail(token: str, author_id: UUID) -> AdminAuthorDetailDTO:
    caller = validate_and_extract_author_details(token=token)
    require_super_admin_or_reviewer(caller)
    with SessionLocal() as db:
        author = get_author_by_id(db=db, author_id=author_id)
    return _author_to_detail(author)


def activate_author(token: str, author_id: UUID) -> AdminAuthorActivateResponse:
    caller = validate_and_extract_author_details(token=token)
    require_super_admin(caller)
    with SessionLocal() as db:
        author = get_author_by_id(db=db, author_id=author_id)
        was_active = bool(author.is_active)
        was_suspended = author.suspended_at is not None
        author.is_active = True
        author.suspended_at = None
        author.updated_by = caller.email
        saved = save_author(db=db, author=author)
        if not was_active:
            on_author_activated_by_admin(db, saved, was_suspended=was_suspended)
        return AdminAuthorActivateResponse(id=saved.id, is_active=bool(saved.is_active))


def suspend_author(token: str, author_id: UUID) -> AdminAuthorActivateResponse:
    caller = validate_and_extract_author_details(token=token)
    require_super_admin(caller)
    with SessionLocal() as db:
        author = get_author_by_id(db=db, author_id=author_id)
        _guard_last_super_admin(db=db, author=author)
        author.is_active = False
        # Marks this as a suspension, so signing in again (which activates
        # everyone else) can't switch the author back on.
        author.suspended_at = datetime.now(timezone.utc)
        author.updated_by = caller.email
        saved = save_author(db=db, author=author)
    return AdminAuthorActivateResponse(id=saved.id, is_active=bool(saved.is_active))


def update_author_platform_role(
    token: str,
    author_id: UUID,
    body: AdminAuthorPlatformRoleUpdate,
) -> AdminAuthorDetailDTO:
    caller = validate_and_extract_author_details(token=token)
    require_super_admin(caller)
    with SessionLocal() as db:
        author = get_author_by_id(db=db, author_id=author_id)
        _guard_last_super_admin(db=db, author=author, new_role=body.platform_role)
        author.platform_role = body.platform_role.value
        author.updated_by = caller.email
        saved = save_author(db=db, author=author)
    return _author_to_detail(saved)

