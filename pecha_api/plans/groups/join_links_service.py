"""Shareable group join links (author_group_join_links).

A group OWNER/ADMIN creates a link with a role, an expiry and an optional use
limit and shares it however they like. Whoever opens it and signs in to the
Studio joins the group with that role. Unlike email invites a link isn't tied
to one address, so it also reaches phone-only authors and lets a manager
onboard a whole class or sangha at once.

Activation of pending authors on redemption is handled by
studio_access_service, which is the one place that decides who gets in.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.config import get, get_int
from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
from pecha_api.plans.groups.groups_models import AuthorGroupJoinLink, AuthorGroupMember
from pecha_api.plans.groups.groups_repository import get_group_by_id, get_group_member
from pecha_api.plans.groups.groups_response_models import (
    CreateGroupJoinLinkRequest,
    GroupJoinLinkDTO,
    GroupJoinLinkListResponse,
    GroupJoinLinkPreviewDTO,
    GroupJoinLinkRedeemResponse,
)
from pecha_api.plans.groups.groups_service import (
    _assert_can_manage_group_invites,
    _assert_invite_role_allowed,
    _group_title_from_metadata,
    _to_role_value,
)
from pecha_api.plans.groups.join_links_repository import (
    add_member_via_join_link,
    create_join_link,
    get_join_link_by_id,
    get_join_link_by_token,
    list_join_links_by_group,
    save_join_link,
)

JOIN_LINK_NOT_FOUND = "Join link not found"
JOIN_LINK_UNUSABLE = (
    "This join link has expired or is no longer active. Ask the group manager for a new one."
)
_TOKEN_BYTES = 24


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def join_link_url(token: str) -> str:
    return f"{get('WEBUDDHIST_STUDIO_BASE_URL').rstrip('/')}/join?link={token}"


def is_join_link_usable(link: AuthorGroupJoinLink, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if link.revoked_at is not None:
        return False
    if _as_aware_utc(link.expires_at) <= now:
        return False
    return link.max_uses is None or (link.use_count or 0) < link.max_uses


def _to_dto(link: AuthorGroupJoinLink) -> GroupJoinLinkDTO:
    return GroupJoinLinkDTO(
        id=link.id,
        group_id=link.group_id,
        role=AuthorGroupMemberRole(_to_role_value(link.role)),
        token=link.token,
        url=join_link_url(link.token),
        max_uses=link.max_uses,
        use_count=link.use_count or 0,
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        created_at=link.created_at,
        created_by=link.created_by,
        is_usable=is_join_link_usable(link),
    )


def _link_expires_at(expires_in_days: Optional[int]) -> datetime:
    max_days = get_int("GROUP_JOIN_LINK_MAX_EXPIRY_DAYS")
    days = expires_in_days or get_int("GROUP_JOIN_LINK_DEFAULT_EXPIRY_DAYS")
    if days > max_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A join link can last at most {max_days} days",
        )
    return datetime.now(timezone.utc) + timedelta(days=days)


def create_group_join_link(
    token: str,
    group_id: UUID,
    request: CreateGroupJoinLinkRequest,
) -> GroupJoinLinkDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        actor_role = _assert_can_manage_group_invites(db, group_id=group_id, author=author)
        _assert_invite_role_allowed(actor_role=actor_role, invite_role=_to_role_value(request.role))
        link = AuthorGroupJoinLink(
            group_id=group_id,
            token=secrets.token_urlsafe(_TOKEN_BYTES),
            role=request.role,
            max_uses=request.max_uses,
            use_count=0,
            expires_at=_link_expires_at(request.expires_in_days),
            created_at=datetime.now(timezone.utc),
            created_by=author.email or str(author.id),
        )
        return _to_dto(create_join_link(db=db, link=link))


def list_group_join_links(token: str, group_id: UUID) -> GroupJoinLinkListResponse:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        _assert_can_manage_group_invites(db, group_id=group_id, author=author)
        links = [_to_dto(link) for link in list_join_links_by_group(db=db, group_id=group_id)]
    return GroupJoinLinkListResponse(links=links, total=len(links))


def revoke_group_join_link(token: str, group_id: UUID, link_id: UUID) -> None:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        actor_role = _assert_can_manage_group_invites(db, group_id=group_id, author=author)
        link = get_join_link_by_id(db=db, link_id=link_id)
        if link is None or link.group_id != group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=JOIN_LINK_NOT_FOUND)
        if (
            _to_role_value(link.role) == AuthorGroupMemberRole.ADMIN.value
            and actor_role != AuthorGroupMemberRole.OWNER.value
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the group owner can revoke an ADMIN join link",
            )
        if link.revoked_at is not None:
            return
        link.revoked_at = datetime.now(timezone.utc)
        link.revoked_by = author.email or str(author.id)
        save_join_link(db=db, link=link)


def get_join_link_preview(link_token: str) -> GroupJoinLinkPreviewDTO:
    """Public: what the Studio /join?link= page shows before sign-in."""
    with SessionLocal() as db:
        link = get_join_link_by_token(db=db, token=link_token)
        if link is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=JOIN_LINK_NOT_FOUND)
        group_name = _group_title_from_metadata(link.group.metadata_entries if link.group else None)
        return GroupJoinLinkPreviewDTO(
            group_id=link.group_id,
            group_name=group_name,
            role=AuthorGroupMemberRole(_to_role_value(link.role)),
            expires_at=link.expires_at,
            is_usable=is_join_link_usable(link),
        )


def redeem_join_link(db: Session, *, author, link_token: str) -> GroupJoinLinkRedeemResponse:
    """Add the author to the link's group. Membership only - whether the
    author may be activated is studio_access_service's call. An existing
    member keeps their role and doesn't use up the link."""
    link = get_join_link_by_token(db=db, token=link_token, for_update=True)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=JOIN_LINK_NOT_FOUND)
    if not is_join_link_usable(link):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=JOIN_LINK_UNUSABLE)
    group = get_group_by_id(db=db, group_id=link.group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=JOIN_LINK_NOT_FOUND)
    group_id = link.group_id
    group_name = _group_title_from_metadata(group.metadata_entries)
    role = AuthorGroupMemberRole(_to_role_value(link.role))

    existing = get_group_member(db=db, group_id=group_id, author_id=author.id)
    if existing is not None:
        existing_role = AuthorGroupMemberRole(_to_role_value(existing.role))
        db.rollback()  # release the row lock; nothing to write
        return GroupJoinLinkRedeemResponse(
            group_id=group_id,
            group_name=group_name,
            role=existing_role,
            already_member=True,
        )

    add_member_via_join_link(
        db=db,
        link=link,
        member=AuthorGroupMember(
            group_id=group_id,
            author_id=author.id,
            role=role,
            created_by=author.email or str(author.id),
        ),
    )
    return GroupJoinLinkRedeemResponse(
        group_id=group_id,
        group_name=group_name,
        role=role,
        already_member=False,
    )
