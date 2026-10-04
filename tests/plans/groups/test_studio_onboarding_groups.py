"""Group side of faster Studio onboarding: signed invite links, bulk invites,
auto-accepting invites on first entry, and shareable join links."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from jose import jwt as jose_jwt

from pecha_api.plans.groups import group_invite_token, join_links_service
from pecha_api.plans.groups.groups_enums import AuthorGroupInviteStatus, AuthorGroupMemberRole
from pecha_api.plans.groups.groups_response_models import (
    BulkGroupInviteRequest,
    CreateGroupJoinLinkRequest,
    GroupInviteCreatedResponse,
    GroupInviteDTO,
)
from pecha_api.plans.groups.groups_service import (
    accept_pending_invites_for_author,
    create_group_member_invites_bulk,
    get_invite_preview,
    notify_pending_group_invites,
)

GROUPS = "pecha_api.plans.groups.groups_service"
LINKS = "pecha_api.plans.groups.join_links_service"
TOKEN = "pecha_api.plans.groups.group_invite_token"

_CONFIG = {
    "JWT_SECRET_KEY": "test-secret",
    "JWT_ALGORITHM": "HS256",
    "JWT_AUD": "https://pecha.org",
    "JWT_ISSUER": "https://pecha.org",
}


def _session(session_local):
    db = MagicMock()
    session_local.return_value.__enter__.return_value = db
    session_local.return_value.__exit__.return_value = False
    return db


# ------------------------------------------------------------- invite tokens

@pytest.fixture
def jwt_config():
    with patch(f"{TOKEN}.get", side_effect=lambda key: _CONFIG[key]):
        yield


def test_invite_token_round_trip(jwt_config):
    invite_id = uuid4()
    token = group_invite_token.create_invite_token(
        invite_id=invite_id,
        target_email="Tenzin@Example.org",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    assert group_invite_token.decode_invite_token(token) == (invite_id, "tenzin@example.org")


def test_expired_invite_token_says_so(jwt_config):
    token = group_invite_token.create_invite_token(
        invite_id=uuid4(),
        target_email="a@example.org",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    with pytest.raises(HTTPException) as exc:
        group_invite_token.decode_invite_token(token)
    assert exc.value.detail == group_invite_token.INVITE_TOKEN_EXPIRED


def test_access_token_is_not_an_invite_token(jwt_config):
    access_token = jose_jwt.encode(
        {"sub": str(uuid4()), "aud": _CONFIG["JWT_AUD"], "iss": _CONFIG["JWT_ISSUER"]},
        _CONFIG["JWT_SECRET_KEY"],
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        group_invite_token.decode_invite_token(access_token)
    assert exc.value.detail == group_invite_token.INVITE_TOKEN_INVALID


def test_invite_token_cannot_be_replayed_as_a_bearer_token(jwt_config):
    from pecha_api.auth.auth_repository import decode_backend_token

    token = group_invite_token.create_invite_token(
        invite_id=uuid4(),
        target_email="a@example.org",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    with patch("pecha_api.auth.auth_repository.get", side_effect=lambda key: _CONFIG[key]):
        with pytest.raises(Exception):
            decode_backend_token(token)
    claims = jose_jwt.get_unverified_claims(token)
    assert not {"sub", "email", "phone_number"} & set(claims)


# ------------------------------------------------------------- invite flows

def test_notify_pending_invites_skips_phone_only_authors():
    with patch(f"{GROUPS}.SessionLocal") as session_local:
        notify_pending_group_invites(SimpleNamespace(id=uuid4(), email=None))
    session_local.assert_not_called()


def test_accept_pending_invites_skips_ones_that_fail():
    author = SimpleNamespace(id=uuid4(), email="a@example.org")
    good, bad = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    group = SimpleNamespace(id=uuid4())

    def _accept(db, invite, author):
        if invite is bad:
            raise HTTPException(status_code=400, detail="Invite has expired")
        return group

    with patch(f"{GROUPS}.list_pending_invites_by_email", return_value=[good, bad]), \
            patch(f"{GROUPS}._accept_invite", side_effect=_accept):
        assert accept_pending_invites_for_author(MagicMock(), author) == [group.id]


def _invite_dto(email):
    now = datetime.now(timezone.utc)
    return GroupInviteDTO(
        id=uuid4(),
        group_id=uuid4(),
        group_name="Sangha",
        target_email=email,
        role=AuthorGroupMemberRole.AUTHOR,
        status=AuthorGroupInviteStatus.PENDING,
        expires_at=now + timedelta(days=7),
        created_at=now,
        created_by="owner@example.org",
        inviter_name="Owner",
        inviter_email="owner@example.org",
    )


def test_bulk_invites_report_each_address():
    def _send(*, author, group_id, target_email, role):
        if target_email == "pending@example.org":
            raise HTTPException(status_code=400, detail="A pending invitation already exists for this email")
        return GroupInviteCreatedResponse(invite=_invite_dto(target_email))

    with patch(f"{GROUPS}.validate_and_extract_author_details", return_value=MagicMock()), \
            patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}._assert_can_manage_group_invites", return_value="OWNER"), \
            patch(f"{GROUPS}._send_member_invite", side_effect=_send) as send:
        _session(session_local)
        result = create_group_member_invites_bulk(
            token="t",
            group_id=uuid4(),
            request=BulkGroupInviteRequest(
                target_emails=[" New@Example.org ", "not-an-email", "new@example.org", "pending@example.org"],
                role=AuthorGroupMemberRole.AUTHOR,
            ),
        )

    assert [invite.target_email for invite in result.invites] == ["new@example.org"]
    assert [(s.target_email, s.reason) for s in result.skipped] == [
        ("not-an-email", "Not a valid email address"),
        ("new@example.org", "Listed more than once"),
        ("pending@example.org", "A pending invitation already exists for this email"),
    ]
    assert send.call_count == 2


def test_bulk_admin_invites_need_the_owner():
    with patch(f"{GROUPS}.validate_and_extract_author_details", return_value=MagicMock()), \
            patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}._assert_can_manage_group_invites", return_value="ADMIN"), \
            patch(f"{GROUPS}._send_member_invite") as send:
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            create_group_member_invites_bulk(
                token="t",
                group_id=uuid4(),
                request=BulkGroupInviteRequest(target_emails=["a@example.org"], role=AuthorGroupMemberRole.ADMIN),
            )
    assert exc.value.status_code == 403
    send.assert_not_called()


def test_bulk_invites_are_capped():
    with pytest.raises(Exception):
        BulkGroupInviteRequest(target_emails=[f"a{i}@example.org" for i in range(51)], role=AuthorGroupMemberRole.AUTHOR)


def _invite(**overrides):
    now = datetime.now(timezone.utc)
    values = dict(
        id=uuid4(),
        group_id=uuid4(),
        group=None,
        target_email="tenzin@example.org",
        role=AuthorGroupMemberRole.AUTHOR,
        status=AuthorGroupInviteStatus.PENDING.value,
        expires_at=now + timedelta(days=7),
        accepted_at=None,
        rejected_at=None,
        revoked_at=None,
        created_at=now,
        created_by="owner@example.org",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_invite_preview_shows_the_invite_and_whether_to_sign_up():
    invite = _invite()
    owner = SimpleNamespace(first_name="Karma", last_name="Owner", email="owner@example.org")
    with patch(f"{GROUPS}.decode_invite_token", return_value=(invite.id, "tenzin@example.org")), \
            patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}.get_invite_by_id", return_value=invite), \
            patch(f"{GROUPS}.find_author_by_email", side_effect=lambda db, email: owner if email == "owner@example.org" else None):
        _session(session_local)
        preview = get_invite_preview("tok")
    assert preview.invite_id == invite.id
    assert preview.inviter_name == "Karma Owner"
    assert preview.status == AuthorGroupInviteStatus.PENDING
    assert preview.account_exists is False


def test_invite_preview_marks_a_lapsed_invite_expired():
    invite = _invite(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    with patch(f"{GROUPS}.decode_invite_token", return_value=(invite.id, "tenzin@example.org")), \
            patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}.get_invite_by_id", return_value=invite), \
            patch(f"{GROUPS}.find_author_by_email", return_value=None):
        _session(session_local)
        assert get_invite_preview("tok").status == AuthorGroupInviteStatus.EXPIRED


def test_invite_preview_rejects_a_token_for_another_address():
    invite = _invite(target_email="someone@example.org")
    with patch(f"{GROUPS}.decode_invite_token", return_value=(invite.id, "tenzin@example.org")), \
            patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}.get_invite_by_id", return_value=invite):
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            get_invite_preview("tok")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------- join links

def _link(**overrides):
    now = datetime.now(timezone.utc)
    values = dict(
        id=uuid4(),
        group_id=uuid4(),
        group=None,
        token="tok",
        role=AuthorGroupMemberRole.AUTHOR,
        max_uses=None,
        use_count=0,
        expires_at=now + timedelta(days=14),
        revoked_at=None,
        revoked_by=None,
        created_at=now,
        created_by="owner@example.org",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "overrides, usable",
    [
        ({}, True),
        ({"max_uses": 3, "use_count": 2}, True),
        ({"max_uses": 3, "use_count": 3}, False),
        ({"revoked_at": datetime.now(timezone.utc)}, False),
        ({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}, False),
        ({"expires_at": datetime.now() + timedelta(days=1)}, True),  # naive timestamps read as UTC
    ],
)
def test_join_link_usability(overrides, usable):
    assert join_links_service.is_join_link_usable(_link(**overrides)) is usable


def _int_config(key):
    return {"GROUP_JOIN_LINK_DEFAULT_EXPIRY_DAYS": 14, "GROUP_JOIN_LINK_MAX_EXPIRY_DAYS": 90}[key]


def _persisted(db, link):
    link.id = uuid4()
    return link


def test_create_join_link_defaults_to_two_weeks():
    author = SimpleNamespace(id=uuid4(), email="owner@example.org")
    group_id = uuid4()
    with patch(f"{LINKS}.validate_and_extract_author_details", return_value=author), \
            patch(f"{LINKS}.SessionLocal") as session_local, \
            patch(f"{LINKS}._assert_can_manage_group_invites", return_value="OWNER"), \
            patch(f"{LINKS}.get_int", side_effect=_int_config), \
            patch(f"{LINKS}.get", return_value="https://studio.webuddhist.com/"), \
            patch(f"{LINKS}.create_join_link", side_effect=_persisted) as create:
        _session(session_local)
        dto = join_links_service.create_group_join_link(
            "t", group_id, CreateGroupJoinLinkRequest(max_uses=25)
        )
    link = create.call_args.kwargs["link"]
    assert len(link.token) >= 32
    assert dto.url == f"https://studio.webuddhist.com/join?link={link.token}"
    assert dto.max_uses == 25
    assert dto.role == AuthorGroupMemberRole.AUTHOR
    assert timedelta(days=13) < dto.expires_at - datetime.now(timezone.utc) <= timedelta(days=14)
    assert dto.is_usable is True


def test_create_join_link_refuses_too_long_a_lifetime():
    with patch(f"{LINKS}.validate_and_extract_author_details", return_value=MagicMock()), \
            patch(f"{LINKS}.SessionLocal") as session_local, \
            patch(f"{LINKS}._assert_can_manage_group_invites", return_value="OWNER"), \
            patch(f"{LINKS}.get_int", side_effect=_int_config), \
            patch(f"{LINKS}.create_join_link") as create:
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            join_links_service.create_group_join_link("t", uuid4(), CreateGroupJoinLinkRequest(expires_in_days=365))
    assert exc.value.status_code == 400
    create.assert_not_called()


def test_only_the_owner_creates_admin_join_links():
    with patch(f"{LINKS}.validate_and_extract_author_details", return_value=MagicMock()), \
            patch(f"{LINKS}.SessionLocal") as session_local, \
            patch(f"{LINKS}._assert_can_manage_group_invites", return_value="ADMIN"), \
            patch(f"{LINKS}.create_join_link") as create:
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            join_links_service.create_group_join_link(
                "t", uuid4(), CreateGroupJoinLinkRequest(role=AuthorGroupMemberRole.ADMIN)
            )
    assert exc.value.status_code == 403
    create.assert_not_called()


def test_revoke_join_link():
    link = _link()
    with patch(f"{LINKS}.validate_and_extract_author_details", return_value=SimpleNamespace(id=uuid4(), email="o@x.org")), \
            patch(f"{LINKS}.SessionLocal") as session_local, \
            patch(f"{LINKS}._assert_can_manage_group_invites", return_value="ADMIN"), \
            patch(f"{LINKS}.get_join_link_by_id", return_value=link), \
            patch(f"{LINKS}.save_join_link") as save:
        _session(session_local)
        join_links_service.revoke_group_join_link("t", link.group_id, link.id)
    assert link.revoked_at is not None
    assert link.revoked_by == "o@x.org"
    save.assert_called_once()


def test_revoke_join_link_of_another_group_is_not_found():
    link = _link()
    with patch(f"{LINKS}.validate_and_extract_author_details", return_value=MagicMock()), \
            patch(f"{LINKS}.SessionLocal") as session_local, \
            patch(f"{LINKS}._assert_can_manage_group_invites", return_value="OWNER"), \
            patch(f"{LINKS}.get_join_link_by_id", return_value=link):
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            join_links_service.revoke_group_join_link("t", uuid4(), link.id)
    assert exc.value.status_code == 404


def _redeem(link, member=None):
    group = SimpleNamespace(id=link.group_id, metadata_entries=[])
    with patch(f"{LINKS}.get_join_link_by_token", return_value=link), \
            patch(f"{LINKS}.get_group_by_id", return_value=group), \
            patch(f"{LINKS}.get_group_member", return_value=member), \
            patch(f"{LINKS}.add_member_via_join_link") as add:
        result = join_links_service.redeem_join_link(
            MagicMock(), author=SimpleNamespace(id=uuid4(), email=None), link_token=link.token
        )
    return result, add


def test_redeem_join_link_adds_the_member():
    link = _link(role=AuthorGroupMemberRole.VIEWER)
    result, add = _redeem(link)
    assert result.already_member is False
    assert result.role == AuthorGroupMemberRole.VIEWER
    member = add.call_args.kwargs["member"]
    assert member.role == AuthorGroupMemberRole.VIEWER
    assert member.created_by  # phone-only author still records who joined


def test_redeem_join_link_does_not_spend_a_use_on_existing_members():
    link = _link()
    result, add = _redeem(link, member=SimpleNamespace(role=AuthorGroupMemberRole.ADMIN))
    assert result.already_member is True
    assert result.role == AuthorGroupMemberRole.ADMIN
    add.assert_not_called()


def test_redeem_join_link_refuses_a_used_up_link():
    link = _link(max_uses=1, use_count=1)
    with pytest.raises(HTTPException) as exc:
        _redeem(link)
    assert exc.value.status_code == 400
    assert exc.value.detail == join_links_service.JOIN_LINK_UNUSABLE


def test_invite_email_carries_a_signed_join_link():
    from pecha_api.plans.groups.groups_service import _send_member_invite

    author = SimpleNamespace(id=uuid4(), email="owner@example.org", first_name="Karma", last_name="Owner")
    group = SimpleNamespace(id=uuid4(), metadata_entries=[])
    created = _invite(group_id=group.id)
    with patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}.find_author_by_email", return_value=None), \
            patch(f"{GROUPS}.has_pending_invite", return_value=False), \
            patch(f"{GROUPS}.create_group_invite", return_value=created), \
            patch(f"{GROUPS}.get_group_by_id", return_value=group), \
            patch(f"{GROUPS}.create_invite_token", return_value="signed") as sign, \
            patch(f"{GROUPS}.send_group_invitation_email") as send:
        _session(session_local)
        _send_member_invite(
            author=author,
            group_id=group.id,
            target_email="tenzin@example.org",
            role=AuthorGroupMemberRole.AUTHOR,
        )
    assert sign.call_args.kwargs == {
        "invite_id": created.id,
        "target_email": created.target_email,
        "expires_at": created.expires_at,
    }
    assert send.call_args.kwargs["invite_token"] == "signed"


def test_invite_email_still_goes_out_if_signing_fails():
    from pecha_api.plans.groups.groups_service import _send_member_invite

    author = SimpleNamespace(id=uuid4(), email="owner@example.org", first_name="Karma", last_name="Owner")
    group = SimpleNamespace(id=uuid4(), metadata_entries=[])
    with patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}.find_author_by_email", return_value=None), \
            patch(f"{GROUPS}.has_pending_invite", return_value=False), \
            patch(f"{GROUPS}.create_group_invite", return_value=_invite(group_id=group.id)), \
            patch(f"{GROUPS}.get_group_by_id", return_value=group), \
            patch(f"{GROUPS}.create_invite_token", side_effect=RuntimeError("no key")), \
            patch(f"{GROUPS}.send_group_invitation_email") as send:
        _session(session_local)
        _send_member_invite(
            author=author,
            group_id=group.id,
            target_email="tenzin@example.org",
            role=AuthorGroupMemberRole.AUTHOR,
        )
    assert send.call_args.kwargs["invite_token"] is None


# ---------------------------------------------------- group name term filter

from pecha_api.plans.groups.groups_response_models import (  # noqa: E402
    CreateAuthorGroupRequest,
    GroupMetadataInput,
    UpdateAuthorGroupRequest,
)
from pecha_api.plans.groups.groups_service import (  # noqa: E402
    GROUP_NAME_INAPPROPRIATE_MESSAGE,
    create_author_group,
    update_author_group,
)
from pecha_api.plans.platform_enums import PlatformRole  # noqa: E402


def _metadata(title, sub_title=None):
    return [GroupMetadataInput(title=title, sub_title=sub_title, language="EN")]


def _assert_rejected(exc):
    assert exc.value.status_code == 400
    assert exc.value.detail == {
        "success": False,
        "code": "INAPPROPRIATE_LANGUAGE",
        "message": GROUP_NAME_INAPPROPRIATE_MESSAGE,
    }


@pytest.mark.parametrize(
    "slug, title, sub_title",
    [
        ("dharma-circle", "Shit posting club", None),
        ("dharma-circle", "Dharma Circle", "for fuck sake"),
        ("fuck-this", "Dharma Circle", None),
    ],
)
def test_create_group_rejects_a_bad_name(slug, title, sub_title):
    with patch(f"{GROUPS}.validate_and_extract_author_details") as validate, \
            patch(f"{GROUPS}.create_group") as create:
        with pytest.raises(HTTPException) as exc:
            create_author_group(
                token="t",
                request=CreateAuthorGroupRequest(slug=slug, metadata=_metadata(title, sub_title)),
            )
    _assert_rejected(exc)
    validate.assert_not_called()
    create.assert_not_called()


def test_create_group_allows_dharma_vocabulary():
    author = SimpleNamespace(id=uuid4(), email="a@example.org")
    with patch(f"{GROUPS}.validate_and_extract_author_details", return_value=author), \
            patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}.get_group_by_slug", return_value=None), \
            patch(f"{GROUPS}.create_group", return_value=SimpleNamespace(id=uuid4())) as create, \
            patch(f"{GROUPS}.get_group_by_id"), \
            patch(f"{GROUPS}._group_to_detail"):
        _session(session_local)
        create_author_group(
            token="t",
            request=CreateAuthorGroupRequest(
                slug="hell-realms-and-the-third-precept",
                metadata=_metadata("Hell Realms Study", "Lust, sexual misconduct and the precepts"),
            ),
        )
    create.assert_called_once()


def test_renaming_a_group_goes_through_the_filter():
    owner = MagicMock(platform_role=PlatformRole.SUPER_ADMIN)
    group = MagicMock(slug="dharma-circle", is_public=True)
    with patch(f"{GROUPS}.validate_and_extract_author_details", return_value=owner), \
            patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}.get_group_by_id", return_value=group), \
            patch(f"{GROUPS}.replace_group_metadata") as replace, \
            patch(f"{GROUPS}.update_group") as update:
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            update_author_group(
                token="t",
                group_id=uuid4(),
                request=UpdateAuthorGroupRequest(metadata=_metadata("Bitch please")),
            )
    _assert_rejected(exc)
    replace.assert_not_called()
    update.assert_not_called()
    assert group.slug == "dharma-circle"


def test_changing_a_group_slug_goes_through_the_filter():
    owner = MagicMock(platform_role=PlatformRole.SUPER_ADMIN)
    group = MagicMock(slug="dharma-circle")
    with patch(f"{GROUPS}.validate_and_extract_author_details", return_value=owner), \
            patch(f"{GROUPS}.SessionLocal") as session_local, \
            patch(f"{GROUPS}.get_group_by_id", return_value=group), \
            patch(f"{GROUPS}.update_group") as update:
        _session(session_local)
        with pytest.raises(HTTPException) as exc:
            update_author_group(token="t", group_id=uuid4(), request=UpdateAuthorGroupRequest(slug="shit-circle"))
    _assert_rejected(exc)
    update.assert_not_called()
    assert group.slug == "dharma-circle"
