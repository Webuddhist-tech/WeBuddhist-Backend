"""Who gets into the Studio, and when.

Anyone who signs in to the Studio is let straight in as a creator - there is
no approval step. admit_author() runs on every Studio sign-in (and on email
verification) and:

  1. redeems a group join link if one was sent, joining that group;
  2. activates the author if they weren't active yet;
  3. on that first entry, accepts every pending invite to their verified
     email, so they land inside the groups they were invited to.

Being active doesn't let anyone touch a group they aren't a member of: group
roles still decide that (see shared/permissions.py). What a brand-new author
can do on their own is create a group, and its name goes through the chat
term filter (groups_service._assert_group_name_clean).

Activation only happens on a Studio sign-in. The inert Author created for
every app signup stays inactive until that person actually uses the Studio.

Nothing here ever re-activates a suspended author (suspended_at set): only a
SuperAdmin can.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.plans.auth.plan_auth_enums import AuthorStatus
from pecha_api.plans.auth.studio_access_emails import send_account_activated_email
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.authors.plan_authors_repository import get_author_by_id, update_author
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_response_models import (
    GroupJoinLinkRedeemResponse,
    RedeemGroupJoinLinkRequest,
)
from pecha_api.plans.groups.groups_service import accept_pending_invites_for_author
from pecha_api.plans.groups.join_links_service import redeem_join_link
from pecha_api.plans.response_message import AUTHOR_NOT_ACTIVE, AUTHOR_SUSPENDED


@dataclass
class StudioAdmission:
    # Groups the author is in because of this sign-in (invites accepted, or
    # the join link's group, even if they were already a member) - the
    # Studio can open the first one instead of an empty dashboard.
    joined_group_ids: List[UUID] = field(default_factory=list)
    join_link_error: Optional[str] = None
    # True when this sign-in is the one that activated the author.
    activated: bool = False


def account_status(author: Author) -> AuthorStatus:
    """ACTIVE, SUSPENDED, or INACTIVE for an author who has never signed in
    to the Studio (e.g. created for an app signup)."""
    if author.is_active:
        return AuthorStatus.ACTIVE
    if author.suspended_at is not None:
        return AuthorStatus.SUSPENDED
    return AuthorStatus.INACTIVE


def not_active_message(author: Author) -> str:
    if author.suspended_at is not None:
        return AUTHOR_SUSPENDED
    return AUTHOR_NOT_ACTIVE


def _has_proven_email(author: Author) -> bool:
    # is_verified on an author with an email means the Studio verify-email
    # link, Auth0 or an invite link proved they read that inbox. Inert
    # Authors created for app signups are never verified: app signup doesn't
    # check the email, so it must not be enough to accept invites sent to it.
    return bool(author.is_verified and author.email)


def _activate(db, author: Author, admission: StudioAdmission) -> None:
    author.is_active = True
    update_author(db=db, author=author)
    admission.activated = True


def admit_author(db, author: Author, *, join_link_token: Optional[str] = None) -> StudioAdmission:
    """Let an author who has just proven who they are into the Studio. The
    author must belong to `db`. Never raises for a bad join link - the
    sign-in still goes ahead and join_link_error says why."""
    admission = StudioAdmission()
    suspended = author.suspended_at is not None

    if join_link_token:
        if suspended:
            admission.join_link_error = AUTHOR_SUSPENDED
        else:
            try:
                redeemed = redeem_join_link(db, author=author, link_token=join_link_token)
            except HTTPException as exc:
                admission.join_link_error = str(exc.detail)
            else:
                admission.joined_group_ids.append(redeemed.group_id)

    if not author.is_active and not suspended:
        _activate(db, author, admission)

    if admission.activated and _has_proven_email(author):
        for group_id in accept_pending_invites_for_author(db, author):
            if group_id not in admission.joined_group_ids:
                admission.joined_group_ids.append(group_id)
    return admission


def on_author_activated_by_admin(db, author: Author, *, was_suspended: bool) -> None:
    """A SuperAdmin just switched an inactive author on: tell them, and - when
    this isn't lifting a suspension - put them into the groups they were
    already invited to, as a first sign-in would."""
    if not was_suspended and _has_proven_email(author):
        try:
            accept_pending_invites_for_author(db, author)
        except Exception:
            logging.exception("Failed to accept pending invites for activated author %s", author.id)
    if author.email:
        send_account_activated_email(to_email=author.email, first_name=author.first_name)


def redeem_join_link_for_signed_in_author(
    token: str,
    request: RedeemGroupJoinLinkRequest,
) -> GroupJoinLinkRedeemResponse:
    """For an author who is already signed in (or is using an app token):
    join the link's group, activating them if they weren't yet."""
    caller = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        author = get_author_by_id(db=db, author_id=caller.id)
        if author.suspended_at is not None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AUTHOR_SUSPENDED)
        redeemed = redeem_join_link(db, author=author, link_token=request.token)
        if not author.is_active:
            admission = StudioAdmission()
            _activate(db, author, admission)
            if _has_proven_email(author):
                accept_pending_invites_for_author(db, author)
        return redeemed
