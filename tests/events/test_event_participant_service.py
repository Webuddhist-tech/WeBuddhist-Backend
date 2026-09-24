from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.events.event_enums import ParticipationType
from pecha_api.events.event_participant_service import (
    _fullname,
    get_cms_event_participants_service,
    get_event_participants_service,
    join_event_service,
    leave_event_service,
    update_participation_type_service,
)

_SVC = "pecha_api.events.event_participant_service"


def _user(**kw):
    base = dict(
        id=uuid4(),
        firstname="Lena",
        lastname="T",
        username="lena",
        avatar_url=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# --- _fullname composition ---

def test_fullname_combines_first_and_last():
    assert _fullname(_user(firstname="Lena", lastname="Thurman")) == "Lena Thurman"


def test_fullname_handles_missing_lastname():
    assert _fullname(_user(firstname="Lena", lastname=None)) == "Lena"


def test_fullname_none_when_no_names():
    assert _fullname(_user(firstname=None, lastname=None)) is None


# --- join ---

def test_join_event_upserts_participant():
    event_id = uuid4()
    user = _user()
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=user), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=SimpleNamespace(id=event_id, group_id=uuid4())), \
         patch(f"{_SVC}.upsert_event_participant") as mock_upsert:
        join_event_service(token="tok", event_id=event_id)

    assert mock_upsert.call_count == 1
    _, kwargs = mock_upsert.call_args
    assert kwargs["event_id"] == event_id
    assert kwargs["user_id"] == user.id


def test_join_event_404_when_event_missing():
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=None), \
         patch(f"{_SVC}.upsert_event_participant") as mock_upsert:
        with pytest.raises(HTTPException) as exc:
            join_event_service(token="tok", event_id=uuid4())

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_upsert.assert_not_called()


# --- leave ---

def test_leave_event_204_when_row_removed():
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=SimpleNamespace(id=uuid4(), group_id=uuid4())), \
         patch(f"{_SVC}.remove_event_participant", return_value=True):
        # no exception == success (endpoint returns 204)
        leave_event_service(token="tok", event_id=uuid4())


def test_leave_event_404_when_not_joined():
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=SimpleNamespace(id=uuid4(), group_id=uuid4())), \
         patch(f"{_SVC}.remove_event_participant", return_value=False):
        with pytest.raises(HTTPException) as exc:
            leave_event_service(token="tok", event_id=uuid4())

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_leave_event_404_when_event_missing():
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=None), \
         patch(f"{_SVC}.remove_event_participant") as mock_remove:
        with pytest.raises(HTTPException) as exc:
            leave_event_service(token="tok", event_id=uuid4())

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_remove.assert_not_called()


# --- public list ---

def test_public_list_builds_response():
    event_id = uuid4()
    user = _user(firstname="Lena", lastname=None, username=None, avatar_url=None)
    now = datetime.now(timezone.utc)
    with patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=SimpleNamespace(id=event_id, group_id=uuid4())), \
         patch(
             f"{_SVC}.get_event_participants_paginated",
             return_value=([(user, now, "offline")], 1),
         ):
        result = get_event_participants_service(event_id=event_id, skip=0, limit=20)

    assert result.total == 1
    assert result.participants[0].fullname == "Lena"
    assert result.participants[0].username is None
    assert result.participants[0].avatar_url is None
    assert result.participants[0].participation_type == "offline"


def test_public_list_404_when_event_missing():
    with patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=None):
        with pytest.raises(HTTPException) as exc:
            get_event_participants_service(event_id=uuid4())

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


# --- CMS list ---

def test_cms_list_checks_group_read_access():
    event_id = uuid4()
    group_id = uuid4()
    author = SimpleNamespace(id=uuid4())
    with patch(f"{_SVC}.validate_cms_author_details", return_value=author), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=SimpleNamespace(id=event_id, group_id=group_id)), \
         patch(f"{_SVC}.require_can_read_group_content") as mock_perm, \
         patch(f"{_SVC}.get_event_participants_paginated", return_value=([], 0)):
        result = get_cms_event_participants_service(token="tok", event_id=event_id)

    assert result.total == 0
    _, kwargs = mock_perm.call_args
    assert kwargs["group_id"] == group_id
    assert kwargs["author"] == author


def test_cms_list_denied_propagates():
    with patch(f"{_SVC}.validate_cms_author_details", return_value=SimpleNamespace(id=uuid4())), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=SimpleNamespace(id=uuid4(), group_id=uuid4())), \
         patch(
             f"{_SVC}.require_can_read_group_content",
             side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="nope"),
         ), \
         patch(f"{_SVC}.get_event_participants_paginated") as mock_list:
        with pytest.raises(HTTPException) as exc:
            get_cms_event_participants_service(token="tok", event_id=uuid4())

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_list.assert_not_called()


# --- participation type ---

def _event_obj(event_format="hybrid", event_id=None):
    return SimpleNamespace(
        id=event_id or uuid4(), group_id=uuid4(), event_format=event_format
    )


def test_join_passes_chosen_participation_type_on_hybrid_event():
    event = _event_obj("hybrid")
    user = _user()
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=user), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=event), \
         patch(f"{_SVC}.upsert_event_participant") as mock_upsert:
        join_event_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.OFFLINE,
        )

    assert mock_upsert.call_args.kwargs["participation_type"] == "offline"


def test_join_without_choice_leaves_hybrid_participation_unset():
    event = _event_obj("hybrid")
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=event), \
         patch(f"{_SVC}.upsert_event_participant") as mock_upsert:
        join_event_service(token="tok", event_id=event.id)

    assert mock_upsert.call_args.kwargs["participation_type"] is None


def test_join_infers_participation_type_from_online_only_event():
    event = _event_obj("online")
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=event), \
         patch(f"{_SVC}.upsert_event_participant") as mock_upsert:
        join_event_service(token="tok", event_id=event.id)

    assert mock_upsert.call_args.kwargs["participation_type"] == "online"


def test_join_rejects_participation_type_the_event_does_not_offer():
    event = _event_obj("online")
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=event), \
         patch(f"{_SVC}.upsert_event_participant") as mock_upsert:
        with pytest.raises(HTTPException) as exc:
            join_event_service(
                token="tok",
                event_id=event.id,
                participation_type=ParticipationType.OFFLINE,
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_upsert.assert_not_called()


def _group_obj(group_type="COMMUNITY", is_public=True):
    return SimpleNamespace(
        id=uuid4(), group_type=group_type, is_public=is_public, status="PUBLISHED"
    )


@contextmanager
def _update_patches(event, user, group=None, joined=False, ban_expiry=None):
    """The surface update_participation_type_service touches, so each test
    only spells out the part it is actually about."""
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=user), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=event), \
         patch(f"{_SVC}.upsert_event_participant") as mock_upsert, \
         patch(f"{_SVC}.get_group_by_id", return_value=group), \
         patch(f"{_SVC}.is_group_published", return_value=group is not None), \
         patch(f"{_SVC}.lock_group_membership_changes"), \
         patch(f"{_SVC}.is_user_joined_group", return_value=joined), \
         patch(f"{_SVC}.get_group_ban_expiry", return_value=ban_expiry), \
         patch(f"{_SVC}.upsert_group_join") as mock_join, \
         patch(f"{_SVC}._join_event_chat_room"):
        yield mock_upsert, mock_join


def test_update_participation_type_writes_choice():
    event = _event_obj("hybrid")
    user = _user()
    with _update_patches(event, user, group=_group_obj()) as (mock_upsert, _):
        update_participation_type_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.ONLINE,
        )

    kwargs = mock_upsert.call_args.kwargs
    assert kwargs["event_id"] == event.id
    assert kwargs["user_id"] == user.id
    assert kwargs["participation_type"] == "online"


def test_update_participation_type_joins_caller_who_had_not_joined():
    """The upsert is the point of the change: no 404 for a first-time caller."""
    event = _event_obj("hybrid")
    user = _user()
    with _update_patches(event, user, group=_group_obj()) as (mock_upsert, _):
        update_participation_type_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.OFFLINE,
        )

    assert mock_upsert.call_args.kwargs["participation_type"] == "offline"


def test_update_participation_type_joins_parent_group():
    event = _event_obj("hybrid")
    user = _user()
    with _update_patches(event, user, group=_group_obj()) as (_, mock_join):
        update_participation_type_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.ONLINE,
        )

    kwargs = mock_join.call_args.kwargs
    assert kwargs['group_id'] == event.group_id
    assert kwargs['user_id'] == user.id


def test_update_participation_type_skips_group_join_when_already_joined():
    event = _event_obj("hybrid")
    with _update_patches(event, _user(), group=_group_obj(), joined=True) as (
        mock_upsert,
        mock_join,
    ):
        update_participation_type_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.ONLINE,
        )

    mock_upsert.assert_called_once()
    mock_join.assert_not_called()


def test_update_participation_type_skips_group_join_for_page_group():
    """A PAGE group is followed, not joined, so there is no membership to add."""
    event = _event_obj("hybrid")
    with _update_patches(event, _user(), group=_group_obj(group_type="PAGE")) as (
        mock_upsert,
        mock_join,
    ):
        update_participation_type_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.ONLINE,
        )

    mock_upsert.assert_called_once()
    mock_join.assert_not_called()


def test_update_participation_type_skips_group_join_for_private_group():
    event = _event_obj("hybrid")
    with _update_patches(event, _user(), group=_group_obj(is_public=False)) as (
        mock_upsert,
        mock_join,
    ):
        update_participation_type_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.ONLINE,
        )

    mock_upsert.assert_called_once()
    mock_join.assert_not_called()


def test_update_participation_type_does_not_slip_a_banned_user_back_in():
    event = _event_obj("hybrid")
    expiry = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with _update_patches(event, _user(), group=_group_obj(), ban_expiry=expiry) as (
        mock_upsert,
        mock_join,
    ):
        update_participation_type_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.ONLINE,
        )

    # The RSVP still lands - the ban blocks rejoining the group, nothing else.
    mock_upsert.assert_called_once()
    mock_join.assert_not_called()


def test_update_participation_type_404_when_event_missing():
    with _update_patches(None, _user()) as (mock_upsert, _):
        with pytest.raises(HTTPException) as exc:
            update_participation_type_service(
                token="tok",
                event_id=uuid4(),
                participation_type=ParticipationType.ONLINE,
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_upsert.assert_not_called()


def test_update_participation_type_rejects_format_mismatch():
    event = _event_obj("offline")
    with _update_patches(event, _user(), group=_group_obj()) as (mock_upsert, mock_join):
        with pytest.raises(HTTPException) as exc:
            update_participation_type_service(
                token="tok",
                event_id=event.id,
                participation_type=ParticipationType.ONLINE,
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_upsert.assert_not_called()
    mock_join.assert_not_called()
