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


def test_update_participation_type_writes_choice():
    event = _event_obj("hybrid")
    user = _user()
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=user), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=event), \
         patch(f"{_SVC}.set_event_participation_type", return_value=True) as mock_set:
        update_participation_type_service(
            token="tok",
            event_id=event.id,
            participation_type=ParticipationType.ONLINE,
        )

    kwargs = mock_set.call_args.kwargs
    assert kwargs["event_id"] == event.id
    assert kwargs["user_id"] == user.id
    assert kwargs["participation_type"] == "online"


def test_update_participation_type_404_when_not_joined():
    event = _event_obj("hybrid")
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=event), \
         patch(f"{_SVC}.set_event_participation_type", return_value=False):
        with pytest.raises(HTTPException) as exc:
            update_participation_type_service(
                token="tok",
                event_id=event.id,
                participation_type=ParticipationType.ONLINE,
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_update_participation_type_404_when_event_missing():
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=None), \
         patch(f"{_SVC}.set_event_participation_type") as mock_set:
        with pytest.raises(HTTPException) as exc:
            update_participation_type_service(
                token="tok",
                event_id=uuid4(),
                participation_type=ParticipationType.ONLINE,
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_set.assert_not_called()


def test_update_participation_type_rejects_format_mismatch():
    event = _event_obj("offline")
    with patch(f"{_SVC}.validate_and_extract_user_details", return_value=_user()), \
         patch(f"{_SVC}.SessionLocal"), \
         patch(f"{_SVC}.get_event_by_id", return_value=event), \
         patch(f"{_SVC}.set_event_participation_type") as mock_set:
        with pytest.raises(HTTPException) as exc:
            update_participation_type_service(
                token="tok",
                event_id=event.id,
                participation_type=ParticipationType.ONLINE,
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_set.assert_not_called()
