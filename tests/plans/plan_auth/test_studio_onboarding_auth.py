"""Sign-in paths added for faster Studio onboarding: one-step sign-up from an
invite email, invite links that verify an existing account, signing in with
a WeBuddhist app account, and the replies for active and suspended authors."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.auth.auth0_sms import Auth0SMSIdentity
from pecha_api.plans.auth.plan_auth_enums import AuthorStatus
from pecha_api.plans.auth.plan_auth_models import (
    AppLoginRequest,
    InviteRegisterRequest,
    PhoneExchangeRequest,
)
from pecha_api.plans.auth.plan_auth_services import (
    APP_ACCOUNT_CONFLICT,
    INVITE_ACCOUNT_EXISTS,
    INVITE_EMAIL_MISMATCH,
    authenticate_author,
    exchange_phone_token,
    login_with_app_account,
    register_author_from_invite,
)
from pecha_api.plans.auth.studio_access_service import StudioAdmission
from pecha_api.plans.groups.groups_enums import AuthorGroupInviteStatus
from pecha_api.plans.response_message import AUTHOR_NOT_ACTIVE, AUTHOR_SUSPENDED

MODULE = "pecha_api.plans.auth.plan_auth_services"


def _session(session_local):
    db = MagicMock()
    session_local.return_value.__enter__.return_value = db
    return db


def _author(**overrides):
    values = dict(
        id=uuid4(),
        first_name="Tenzin",
        last_name="Dolma",
        email="tenzin@example.org",
        phone_number=None,
        password="hashed",
        image_url=None,
        is_verified=True,
        is_active=False,
        suspended_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _activate(author_group_ids=()):
    def _admit(db, author, join_link_token=None):
        author.is_active = True
        return StudioAdmission(joined_group_ids=list(author_group_ids))
    return _admit


def _pending_invite(email="tenzin@example.org"):
    return SimpleNamespace(
        id=uuid4(),
        target_email=email,
        status=AuthorGroupInviteStatus.PENDING.value,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )


# ------------------------------------------------------- register from invite

def _saved(db, author):
    author.id = uuid4()
    return author


@patch(f"{MODULE}.SessionLocal")
def test_register_from_invite_creates_a_verified_author_and_signs_in(session_local, _no_studio_admission):
    db = _session(session_local)
    invite = _pending_invite()
    group_id = uuid4()
    _no_studio_admission.side_effect = _activate([group_id])

    with patch(f"{MODULE}.decode_invite_token", return_value=(invite.id, "tenzin@example.org")), \
            patch(f"{MODULE}.find_author_by_email", return_value=None), \
            patch(f"{MODULE}.get_invite_by_id", return_value=invite), \
            patch(f"{MODULE}.save_author", side_effect=_saved) as save, \
            patch(f"{MODULE}.link_or_create_user_for_author") as link_user, \
            patch(f"{MODULE}.get_hashed_password", return_value="hashed!"):
        response = register_author_from_invite(
            InviteRegisterRequest(
                invite_token="tok",
                first_name=" Tenzin ",
                last_name=" Dolma ",
                password="secret123",
            )
        )

    created = save.call_args.kwargs["author"]
    assert created.email == "tenzin@example.org"
    assert created.first_name == "Tenzin"
    assert created.password == "hashed!"
    assert created.is_verified is True
    link_user.assert_called_once_with(db=db, author=created)
    assert response.auth.access_token
    assert response.joined_group_ids == [group_id]


@patch(f"{MODULE}.SessionLocal")
def test_register_from_invite_refuses_an_existing_account(session_local):
    _session(session_local)
    with patch(f"{MODULE}.decode_invite_token", return_value=(uuid4(), "tenzin@example.org")), \
            patch(f"{MODULE}.find_author_by_email", return_value=_author()):
        with pytest.raises(HTTPException) as exc:
            register_author_from_invite(
                InviteRegisterRequest(invite_token="t", first_name="A", last_name="B", password="secret123")
            )
    assert exc.value.status_code == 409
    assert exc.value.detail == INVITE_ACCOUNT_EXISTS


@patch(f"{MODULE}.SessionLocal")
def test_register_from_invite_needs_a_live_invite(session_local):
    _session(session_local)
    invite = _pending_invite()
    invite.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    with patch(f"{MODULE}.decode_invite_token", return_value=(invite.id, "tenzin@example.org")), \
            patch(f"{MODULE}.find_author_by_email", return_value=None), \
            patch(f"{MODULE}.get_invite_by_id", return_value=invite), \
            patch(f"{MODULE}.save_author") as save:
        with pytest.raises(HTTPException) as exc:
            register_author_from_invite(
                InviteRegisterRequest(invite_token="t", first_name="A", last_name="B", password="secret123")
            )
    assert exc.value.status_code == 400
    save.assert_not_called()


def test_register_from_invite_requires_names():
    with patch(f"{MODULE}.decode_invite_token", return_value=(uuid4(), "tenzin@example.org")):
        with pytest.raises(HTTPException) as exc:
            register_author_from_invite(
                InviteRegisterRequest(invite_token="t", first_name=" ", last_name="B", password="secret123")
            )
    assert exc.value.status_code == 422


# ------------------------------------------------- password login with invite

@patch(f"{MODULE}.SessionLocal")
def test_login_with_invite_token_verifies_the_account(session_local, _no_studio_admission):
    _session(session_local)
    author = _author(is_verified=False)
    _no_studio_admission.side_effect = _activate()
    with patch(f"{MODULE}.get_author_by_email", return_value=author), \
            patch(f"{MODULE}.verify_password", return_value=True), \
            patch(f"{MODULE}.decode_invite_token", return_value=(uuid4(), "tenzin@example.org")), \
            patch(f"{MODULE}.update_author") as update:
        result, _ = authenticate_author("tenzin@example.org", "pw", invite_token="tok")
    assert result.is_verified is True
    assert result.is_active is True
    update.assert_called_once()


@patch(f"{MODULE}.SessionLocal")
def test_login_with_someone_elses_invite_token_is_refused(session_local):
    _session(session_local)
    author = _author(is_verified=False)
    with patch(f"{MODULE}.get_author_by_email", return_value=author), \
            patch(f"{MODULE}.verify_password", return_value=True), \
            patch(f"{MODULE}.decode_invite_token", return_value=(uuid4(), "other@example.org")):
        with pytest.raises(HTTPException) as exc:
            authenticate_author("tenzin@example.org", "pw", invite_token="tok")
    assert exc.value.status_code == 403
    assert exc.value.detail == INVITE_EMAIL_MISMATCH
    assert author.is_verified is False


@patch(f"{MODULE}.SessionLocal")
def test_login_of_a_suspended_author_keeps_the_studio_detail(session_local):
    # The Studio matches this exact 401 detail to show its not-active screen.
    _session(session_local)
    suspended = _author(suspended_at=datetime.now(timezone.utc))
    with patch(f"{MODULE}.get_author_by_email", return_value=suspended), \
            patch(f"{MODULE}.verify_password", return_value=True):
        with pytest.raises(HTTPException) as exc:
            authenticate_author("tenzin@example.org", "pw")
    assert exc.value.status_code == 401
    assert exc.value.detail == AUTHOR_NOT_ACTIVE


# --------------------------------------------------------------- app account

@patch(f"{MODULE}.SessionLocal")
def test_app_login_rejects_a_bad_password(session_local):
    _session(session_local)
    user = SimpleNamespace(id=uuid4(), email="tenzin@example.org", phone_number=None, password="h")
    with patch(f"{MODULE}.get_user_by_email_or_none", return_value=user), \
            patch(f"{MODULE}.verify_password", return_value=False):
        with pytest.raises(HTTPException) as exc:
            login_with_app_account(AppLoginRequest(email="tenzin@example.org", password="nope"))
    assert exc.value.status_code == 401


@patch(f"{MODULE}.SessionLocal")
def test_app_login_signs_in_the_linked_active_author(session_local):
    _session(session_local)
    user = SimpleNamespace(id=uuid4(), email="tenzin@example.org", phone_number=None, password="h")
    author = _author(is_active=True, is_verified=False)
    with patch(f"{MODULE}.get_user_by_email_or_none", return_value=user), \
            patch(f"{MODULE}.verify_password", return_value=True), \
            patch(f"{MODULE}.find_author_by_user_id", return_value=author):
        response = login_with_app_account(AppLoginRequest(email="tenzin@example.org", password="pw"))
    assert response.status == AuthorStatus.ACTIVE
    assert response.auth is not None


@patch(f"{MODULE}.SessionLocal")
def test_app_login_never_attaches_to_a_studio_account_sharing_the_email(session_local):
    _session(session_local)
    user = SimpleNamespace(id=uuid4(), email="tenzin@example.org", phone_number=None, password="h")
    with patch(f"{MODULE}.get_user_by_email_or_none", return_value=user), \
            patch(f"{MODULE}.verify_password", return_value=True), \
            patch(f"{MODULE}.find_author_by_user_id", return_value=None), \
            patch(f"{MODULE}.find_author_by_email", return_value=_author()), \
            patch(f"{MODULE}.link_or_create_author_for_user") as link:
        with pytest.raises(HTTPException) as exc:
            login_with_app_account(AppLoginRequest(email="tenzin@example.org", password="pw"))
    assert exc.value.status_code == 409
    assert exc.value.detail == APP_ACCOUNT_CONFLICT
    link.assert_not_called()


@patch(f"{MODULE}.SessionLocal")
def test_app_login_creates_an_author_and_signs_them_straight_in(session_local, _no_studio_admission):
    _session(session_local)
    user = SimpleNamespace(id=uuid4(), email="tenzin@example.org", phone_number=None, password="h")
    created = _author(is_verified=False)
    _no_studio_admission.side_effect = _activate()
    with patch(f"{MODULE}.get_user_by_email_or_none", return_value=user), \
            patch(f"{MODULE}.verify_password", return_value=True), \
            patch(f"{MODULE}.find_author_by_user_id", return_value=None), \
            patch(f"{MODULE}.find_author_by_email", return_value=None), \
            patch(f"{MODULE}.link_or_create_author_for_user", return_value=created):
        response = login_with_app_account(
            AppLoginRequest(email="tenzin@example.org", password="pw", join_link_token="link")
        )
    assert response.status == AuthorStatus.ACTIVE
    assert response.account_status == AuthorStatus.ACTIVE
    assert response.auth is not None
    assert _no_studio_admission.call_args.kwargs == {"join_link_token": "link"}


@patch(f"{MODULE}.SessionLocal")
def test_app_login_of_a_suspended_author_says_so(session_local):
    _session(session_local)
    user = SimpleNamespace(id=uuid4(), email="tenzin@example.org", phone_number=None, password="h")
    author = _author(suspended_at=datetime.now(timezone.utc))
    with patch(f"{MODULE}.get_user_by_email_or_none", return_value=user), \
            patch(f"{MODULE}.verify_password", return_value=True), \
            patch(f"{MODULE}.find_author_by_user_id", return_value=author):
        response = login_with_app_account(AppLoginRequest(email="tenzin@example.org", password="pw"))
    assert response.status == AuthorStatus.INACTIVE
    assert response.account_status == AuthorStatus.SUSPENDED
    assert response.message == AUTHOR_SUSPENDED
    assert response.auth is None


# ------------------------------------------------------------- phone exchange

@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.verify_auth0_sms_token")
def test_phone_sign_in_works_for_an_approved_author_with_an_unverified_email(verify_sms, session_local):
    # Authors made for app signups carry is_verified=False; the SMS code is
    # what proves this person, so approval alone should let them in.
    verify_sms.return_value = Auth0SMSIdentity(subject="sms|1", phone_number="+14155552671")
    _session(session_local)
    author = _author(is_active=True, is_verified=False, phone_number="+14155552671")
    with patch(f"{MODULE}.get_author_by_phone", return_value=author), \
            patch(f"{MODULE}.update_author") as update:
        response = exchange_phone_token(PhoneExchangeRequest(auth0_token="t"))
    assert response.auth is not None
    # has an email, which SMS doesn't prove - leave its verified flag alone
    update.assert_not_called()
    assert author.is_verified is False


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.verify_auth0_sms_token")
def test_phone_sign_in_verifies_a_phone_only_author_and_passes_the_join_link(
    verify_sms, session_local, _no_studio_admission
):
    verify_sms.return_value = Auth0SMSIdentity(subject="sms|1", phone_number="+14155552671")
    _session(session_local)
    author = _author(email=None, is_verified=False, phone_number="+14155552671")
    with patch(f"{MODULE}.get_author_by_phone", return_value=author), \
            patch(f"{MODULE}.update_author", side_effect=lambda db, author: author):
        response = exchange_phone_token(PhoneExchangeRequest(auth0_token="t", join_link_token="link"))
    assert author.is_verified is True
    assert _no_studio_admission.call_args.kwargs == {"join_link_token": "link"}
