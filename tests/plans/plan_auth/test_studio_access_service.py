from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.plans.auth import studio_access_service as svc
from pecha_api.plans.auth.plan_auth_enums import AuthorStatus
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
from pecha_api.plans.groups.groups_response_models import (
    GroupJoinLinkRedeemResponse,
    RedeemGroupJoinLinkRequest,
)
from pecha_api.plans.response_message import AUTHOR_NOT_ACTIVE, AUTHOR_SUSPENDED

MODULE = "pecha_api.plans.auth.studio_access_service"


def _author(**overrides):
    values = dict(
        id=uuid4(),
        first_name="Tenzin",
        last_name="Dolma",
        email="tenzin@example.org",
        phone_number=None,
        is_verified=True,
        is_active=False,
        suspended_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _redeemed(group_id=None, already_member=False):
    return GroupJoinLinkRedeemResponse(
        group_id=group_id or uuid4(),
        group_name="Sangha",
        role=AuthorGroupMemberRole.AUTHOR,
        already_member=already_member,
    )


@pytest.fixture
def deps():
    """Patch every collaborator admit_author touches; tests flip the ones they need."""
    with patch(f"{MODULE}.update_author") as update_author, \
            patch(f"{MODULE}.accept_pending_invites_for_author", return_value=[]) as accept, \
            patch(f"{MODULE}.redeem_join_link") as redeem:
        yield SimpleNamespace(update_author=update_author, accept=accept, redeem=redeem)


def test_account_status_distinguishes_never_signed_in_from_suspended():
    assert svc.account_status(_author(is_active=True)) == AuthorStatus.ACTIVE
    assert svc.account_status(_author()) == AuthorStatus.INACTIVE
    assert svc.account_status(_author(suspended_at=datetime.now(timezone.utc))) == AuthorStatus.SUSPENDED
    assert svc.not_active_message(_author()) == AUTHOR_NOT_ACTIVE
    assert svc.not_active_message(_author(suspended_at=datetime.now(timezone.utc))) == AUTHOR_SUSPENDED


def test_signing_in_without_an_invite_activates_the_author(deps):
    author = _author()

    admission = svc.admit_author(MagicMock(), author)

    assert author.is_active is True
    assert admission.activated is True
    assert admission.joined_group_ids == []
    deps.update_author.assert_called_once()


def test_first_sign_in_joins_the_invited_groups(deps):
    author = _author()
    group_id = uuid4()
    deps.accept.return_value = [group_id]

    admission = svc.admit_author(MagicMock(), author)

    assert author.is_active is True
    assert admission.joined_group_ids == [group_id]


def test_suspended_author_is_never_reactivated(deps):
    author = _author(suspended_at=datetime.now(timezone.utc))

    admission = svc.admit_author(MagicMock(), author, join_link_token="link")

    assert author.is_active is False
    assert admission.activated is False
    assert admission.join_link_error == AUTHOR_SUSPENDED
    deps.redeem.assert_not_called()
    deps.accept.assert_not_called()
    deps.update_author.assert_not_called()


def test_unproven_email_is_activated_but_does_not_accept_invites(deps):
    # e.g. someone signing in with an app account, whose email was never checked
    author = _author(is_verified=False)

    admission = svc.admit_author(MagicMock(), author)

    assert author.is_active is True
    assert admission.activated is True
    deps.accept.assert_not_called()


def test_join_link_joins_its_group_on_the_way_in(deps):
    author = _author(email=None, phone_number="+14155552671")
    group_id = uuid4()
    deps.redeem.return_value = _redeemed(group_id)

    admission = svc.admit_author(MagicMock(), author, join_link_token="link")

    assert author.is_active is True
    assert admission.joined_group_ids == [group_id]
    # phone-only: no email, so no email invites to accept
    deps.accept.assert_not_called()


def test_join_link_group_is_not_listed_twice(deps):
    author = _author()
    group_id = uuid4()
    deps.redeem.return_value = _redeemed(group_id)
    deps.accept.return_value = [group_id]

    admission = svc.admit_author(MagicMock(), author, join_link_token="link")

    assert admission.joined_group_ids == [group_id]


def test_bad_join_link_does_not_block_sign_in(deps):
    author = _author()
    deps.redeem.side_effect = HTTPException(status_code=400, detail="expired")

    admission = svc.admit_author(MagicMock(), author, join_link_token="link")

    assert admission.join_link_error == "expired"
    assert author.is_active is True


def test_active_author_is_left_alone(deps):
    author = _author(is_active=True)

    admission = svc.admit_author(MagicMock(), author)

    assert admission.activated is False
    assert admission.joined_group_ids == []
    deps.accept.assert_not_called()
    deps.update_author.assert_not_called()


def test_active_author_can_still_join_through_a_link(deps):
    author = _author(is_active=True)
    group_id = uuid4()
    deps.redeem.return_value = _redeemed(group_id)

    admission = svc.admit_author(MagicMock(), author, join_link_token="link")

    assert admission.joined_group_ids == [group_id]
    assert admission.activated is False


def test_admin_activation_emails_and_accepts_invites():
    author = _author(is_active=True)
    with patch(f"{MODULE}.accept_pending_invites_for_author") as accept, \
            patch(f"{MODULE}.send_account_activated_email") as activated_email:
        svc.on_author_activated_by_admin(MagicMock(), author, was_suspended=False)
    accept.assert_called_once()
    activated_email.assert_called_once_with(to_email=author.email, first_name="Tenzin")


def test_lifting_a_suspension_only_emails():
    author = _author(is_active=True)
    with patch(f"{MODULE}.accept_pending_invites_for_author") as accept, \
            patch(f"{MODULE}.send_account_activated_email") as activated_email:
        svc.on_author_activated_by_admin(MagicMock(), author, was_suspended=True)
    accept.assert_not_called()
    activated_email.assert_called_once()


def _redeem_patches(author):
    session_local = MagicMock()
    session_local.return_value.__enter__.return_value = MagicMock()
    return (
        patch(f"{MODULE}.validate_and_extract_author_details", return_value=author),
        patch(f"{MODULE}.SessionLocal", session_local),
        patch(f"{MODULE}.get_author_by_id", return_value=author),
    )


def test_signed_in_redeem_activates_an_inactive_author():
    author = _author()
    validate, session_local, get_author = _redeem_patches(author)
    with validate, session_local, get_author, \
            patch(f"{MODULE}.redeem_join_link", return_value=_redeemed()) as redeem, \
            patch(f"{MODULE}.update_author"), \
            patch(f"{MODULE}.accept_pending_invites_for_author") as accept:
        result = svc.redeem_join_link_for_signed_in_author("t", RedeemGroupJoinLinkRequest(token="link"))
    assert result.already_member is False
    assert author.is_active is True
    redeem.assert_called_once()
    accept.assert_called_once()


def test_signed_in_redeem_refuses_a_suspended_author():
    author = _author(suspended_at=datetime.now(timezone.utc))
    validate, session_local, get_author = _redeem_patches(author)
    with validate, session_local, get_author, \
            patch(f"{MODULE}.redeem_join_link") as redeem:
        with pytest.raises(HTTPException) as exc:
            svc.redeem_join_link_for_signed_in_author("t", RedeemGroupJoinLinkRequest(token="link"))
    assert exc.value.status_code == 403
    redeem.assert_not_called()
