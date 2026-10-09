"""Removing a joined user from a group, and the rejoin block that follows."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.plans.groups.group_ban_guard import assert_user_not_banned_from_group
from pecha_api.plans.groups.groups_enums import AuthorGroupType
from pecha_api.plans.groups.groups_response_models import (
    DEFAULT_GROUP_BAN_DURATION_DAYS,
    MAX_GROUP_BAN_DURATION_DAYS,
    RemoveGroupUserRequest,
)
from pecha_api.plans.groups.groups_service import (
    GROUP_BAN_NOT_FOUND,
    GROUP_NOT_FOUND,
    USER_NOT_JOINED_GROUP,
    lift_group_ban_by_id,
    list_cms_group_joined_users,
    list_group_bans,
    remove_and_ban_group_user,
)

GUARD = "pecha_api.plans.groups.group_ban_guard.get_active_group_ban"
SERVICE = "pecha_api.plans.groups.groups_service"


def _session(mock_session_local: MagicMock) -> MagicMock:
    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db
    mock_session_local.return_value.__exit__.return_value = False
    return mock_db


def _make_group() -> MagicMock:
    group = MagicMock()
    group.id = uuid4()
    group.group_type = AuthorGroupType.COMMUNITY
    group.is_public = True
    return group


def _make_author(author_id: Optional[UUID] = None) -> MagicMock:
    author = MagicMock()
    author.id = author_id or uuid4()
    author.email = "admin@example.org"
    return author


def _make_user(user_id: Optional[UUID] = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    user.username = "dawa"
    user.firstname = "Dawa"
    user.lastname = "Norbu"
    user.avatar_url = None
    return user


def _make_ban(
    *,
    group_id: UUID,
    user_id: UUID,
    expires_at: Optional[datetime] = None,
    lifted_at: Optional[datetime] = None,
    reason: Optional[str] = None,
) -> MagicMock:
    ban = MagicMock()
    ban.id = uuid4()
    ban.group_id = group_id
    ban.user_id = user_id
    ban.reason = reason
    ban.expires_at = expires_at or datetime.now(timezone.utc) + timedelta(days=7)
    ban.lifted_at = lifted_at
    ban.created_at = datetime.now(timezone.utc)
    ban.user = _make_user(user_id)
    return ban


# --- the guard -------------------------------------------------------------


def test_guard_allows_user_with_no_ban() -> None:
    with patch(GUARD, return_value=None):
        assert_user_not_banned_from_group(
            db=MagicMock(), group_id=uuid4(), user_id=uuid4()
        )


def test_guard_blocks_banned_user_and_reports_expiry() -> None:
    group_id, user_id = uuid4(), uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    ban = _make_ban(group_id=group_id, user_id=user_id, expires_at=expires_at)

    with patch(GUARD, return_value=ban), pytest.raises(HTTPException) as exc:
        assert_user_not_banned_from_group(
            db=MagicMock(), group_id=group_id, user_id=user_id
        )

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc.value.detail["error"] == "GROUP_BANNED"
    assert exc.value.detail["expires_at"] == expires_at.isoformat()


def test_guard_treats_naive_expiry_as_utc() -> None:
    """Postgres can hand back a naive datetime; it must not crash isoformat()."""
    naive = (datetime.now(timezone.utc) + timedelta(days=3)).replace(tzinfo=None)
    ban = _make_ban(group_id=uuid4(), user_id=uuid4(), expires_at=naive)

    with patch(GUARD, return_value=ban), pytest.raises(HTTPException) as exc:
        assert_user_not_banned_from_group(
            db=MagicMock(), group_id=uuid4(), user_id=uuid4()
        )

    assert exc.value.detail["expires_at"].endswith("+00:00")


# --- removal ---------------------------------------------------------------


def test_remove_defaults_to_a_seven_day_ban() -> None:
    group = _make_group()
    author = _make_author()
    user_id = uuid4()
    ban = _make_ban(group_id=group.id, user_id=user_id)

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=author
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_user_by_id", return_value=_make_user(user_id)
    ), patch(
        f"{SERVICE}.is_user_joined_group", return_value=True
    ), patch(
        f"{SERVICE}.remove_group_accumulator_joins_for_group"
    ), patch(
        f"{SERVICE}.leave_group_membership"
    ), patch(
        f"{SERVICE}.is_user_following_group", return_value=False
    ), patch(
        f"{SERVICE}.leave_group_chat_room"
    ), patch(
        f"{SERVICE}.create_group_ban", return_value=ban
    ) as mock_create:
        _session(mock_session)
        result = remove_and_ban_group_user(
            token="t",
            group_id=group.id,
            user_id=user_id,
            request=RemoveGroupUserRequest(),
        )

    expires_at = mock_create.call_args.kwargs["expires_at"]
    days = (expires_at - datetime.now(timezone.utc)).total_seconds() / 86400
    assert DEFAULT_GROUP_BAN_DURATION_DAYS - 0.01 < days <= DEFAULT_GROUP_BAN_DURATION_DAYS
    assert mock_create.call_args.kwargs["created_by"] == author.id
    assert result.is_active is True
    assert result.user_id == user_id


def test_remove_honours_a_custom_duration_and_reason() -> None:
    group = _make_group()
    user_id = uuid4()
    ban = _make_ban(group_id=group.id, user_id=user_id)

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_user_by_id", return_value=_make_user(user_id)
    ), patch(
        f"{SERVICE}.is_user_joined_group", return_value=True
    ), patch(
        f"{SERVICE}.remove_group_accumulator_joins_for_group"
    ), patch(
        f"{SERVICE}.leave_group_membership"
    ), patch(
        f"{SERVICE}.is_user_following_group", return_value=False
    ), patch(
        f"{SERVICE}.leave_group_chat_room"
    ), patch(
        f"{SERVICE}.create_group_ban", return_value=ban
    ) as mock_create:
        _session(mock_session)
        remove_and_ban_group_user(
            token="t",
            group_id=group.id,
            user_id=user_id,
            request=RemoveGroupUserRequest(ban_duration_days=30, reason="  spam  "),
        )

    expires_at = mock_create.call_args.kwargs["expires_at"]
    days = (expires_at - datetime.now(timezone.utc)).total_seconds() / 86400
    assert 29.99 < days <= 30
    # The validator strips surrounding whitespace.
    assert mock_create.call_args.kwargs["reason"] == "spam"


def test_remove_clears_accumulator_joins_and_chat() -> None:
    group = _make_group()
    user_id = uuid4()

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_user_by_id", return_value=_make_user(user_id)
    ), patch(
        f"{SERVICE}.is_user_joined_group", return_value=True
    ), patch(
        f"{SERVICE}.remove_group_accumulator_joins_for_group"
    ) as mock_acc, patch(
        f"{SERVICE}.leave_group_membership"
    ) as mock_leave, patch(
        f"{SERVICE}.is_user_following_group", return_value=False
    ), patch(
        f"{SERVICE}.leave_group_chat_room"
    ) as mock_chat, patch(
        f"{SERVICE}.create_group_ban",
        return_value=_make_ban(group_id=group.id, user_id=user_id),
    ):
        _session(mock_session)
        remove_and_ban_group_user(
            token="t",
            group_id=group.id,
            user_id=user_id,
            request=RemoveGroupUserRequest(),
        )

    mock_acc.assert_called_once()
    mock_leave.assert_called_once()
    mock_chat.assert_called_once()


def test_remove_keeps_chat_room_when_user_still_follows_the_group() -> None:
    """Chat is granted to joiners AND followers, so a follower keeps the room."""
    group = _make_group()
    user_id = uuid4()

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_user_by_id", return_value=_make_user(user_id)
    ), patch(
        f"{SERVICE}.is_user_joined_group", return_value=True
    ), patch(
        f"{SERVICE}.remove_group_accumulator_joins_for_group"
    ), patch(
        f"{SERVICE}.leave_group_membership"
    ), patch(
        f"{SERVICE}.is_user_following_group", return_value=True
    ), patch(
        f"{SERVICE}.leave_group_chat_room"
    ) as mock_chat, patch(
        f"{SERVICE}.create_group_ban",
        return_value=_make_ban(group_id=group.id, user_id=user_id),
    ):
        _session(mock_session)
        remove_and_ban_group_user(
            token="t",
            group_id=group.id,
            user_id=user_id,
            request=RemoveGroupUserRequest(),
        )

    mock_chat.assert_not_called()


def test_remove_rejects_a_user_who_never_joined() -> None:
    group = _make_group()
    user_id = uuid4()

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_user_by_id", return_value=_make_user(user_id)
    ), patch(
        f"{SERVICE}.is_user_joined_group", return_value=False
    ), patch(
        f"{SERVICE}.create_group_ban"
    ) as mock_create:
        _session(mock_session)
        with pytest.raises(HTTPException) as exc:
            remove_and_ban_group_user(
                token="t",
                group_id=group.id,
                user_id=user_id,
                request=RemoveGroupUserRequest(),
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == USER_NOT_JOINED_GROUP
    mock_create.assert_not_called()


def test_remove_rejects_an_unknown_group() -> None:
    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=None):
        _session(mock_session)
        with pytest.raises(HTTPException) as exc:
            remove_and_ban_group_user(
                token="t",
                group_id=uuid4(),
                user_id=uuid4(),
                request=RemoveGroupUserRequest(),
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


@pytest.mark.parametrize("days", [0, -1, MAX_GROUP_BAN_DURATION_DAYS + 1])
def test_ban_duration_outside_the_allowed_range_is_rejected(days: int) -> None:
    with pytest.raises(ValueError):
        RemoveGroupUserRequest(ban_duration_days=days)


def test_blank_reason_becomes_none() -> None:
    assert RemoveGroupUserRequest(reason="   ").reason is None


# --- listing and lifting ---------------------------------------------------


def test_list_bans_marks_an_expired_row_inactive() -> None:
    group = _make_group()
    expired = _make_ban(
        group_id=group.id,
        user_id=uuid4(),
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}.is_reviewer", return_value=False
    ), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.list_group_bans_paginated", return_value=([expired], 1)
    ):
        _session(mock_session)
        result = list_group_bans(
            token="t", group_id=group.id, skip=0, limit=20, active_only=False
        )

    assert result.total == 1
    assert result.bans[0].is_active is False


def test_list_bans_marks_a_lifted_row_inactive() -> None:
    group = _make_group()
    lifted = _make_ban(
        group_id=group.id,
        user_id=uuid4(),
        lifted_at=datetime.now(timezone.utc),
    )

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}.is_reviewer", return_value=False
    ), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.list_group_bans_paginated", return_value=([lifted], 1)
    ):
        _session(mock_session)
        result = list_group_bans(token="t", group_id=group.id, skip=0, limit=20)

    assert result.bans[0].is_active is False
    assert result.bans[0].lifted_at is not None


def test_lift_ban_stamps_the_row() -> None:
    group = _make_group()
    author = _make_author()
    ban = _make_ban(group_id=group.id, user_id=uuid4())
    lifted = _make_ban(
        group_id=group.id, user_id=ban.user_id, lifted_at=datetime.now(timezone.utc)
    )

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=author
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_group_ban_by_id", return_value=ban
    ), patch(
        f"{SERVICE}.lift_group_ban", return_value=lifted
    ) as mock_lift:
        _session(mock_session)
        result = lift_group_ban_by_id(token="t", group_id=group.id, ban_id=ban.id)

    assert mock_lift.call_args.kwargs["lifted_by"] == author.id
    assert result.is_active is False


def test_lift_ban_rejects_a_ban_from_another_group() -> None:
    group = _make_group()
    foreign = _make_ban(group_id=uuid4(), user_id=uuid4())

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_group_ban_by_id", return_value=foreign
    ):
        _session(mock_session)
        with pytest.raises(HTTPException) as exc:
            lift_group_ban_by_id(token="t", group_id=group.id, ban_id=foreign.id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_BAN_NOT_FOUND


def test_lift_ban_rejects_an_already_lifted_ban() -> None:
    group = _make_group()
    ban = _make_ban(
        group_id=group.id, user_id=uuid4(), lifted_at=datetime.now(timezone.utc)
    )

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_group_ban_by_id", return_value=ban
    ), patch(
        f"{SERVICE}.lift_group_ban"
    ) as mock_lift:
        _session(mock_session)
        with pytest.raises(HTTPException) as exc:
            lift_group_ban_by_id(token="t", group_id=group.id, ban_id=ban.id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_lift.assert_not_called()


def test_lift_ban_rejects_an_expired_ban() -> None:
    group = _make_group()
    ban = _make_ban(
        group_id=group.id,
        user_id=uuid4(),
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_group_ban_by_id", return_value=ban
    ), patch(
        f"{SERVICE}.lift_group_ban"
    ) as mock_lift:
        _session(mock_session)
        with pytest.raises(HTTPException) as exc:
            lift_group_ban_by_id(token="t", group_id=group.id, ban_id=ban.id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_lift.assert_not_called()


def test_joined_users_list_carries_user_ids() -> None:
    group = _make_group()
    user = _make_user()
    joined_at = datetime.now(timezone.utc) - timedelta(days=2)

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}.is_reviewer", return_value=False
    ), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}._user_avatar_url", return_value=None
    ), patch(
        f"{SERVICE}.list_group_joiners_with_join_date_paginated",
        return_value=([(user, joined_at)], 1),
    ):
        _session(mock_session)
        result = list_cms_group_joined_users(
            token="t", group_id=group.id, skip=0, limit=20
        )

    assert result.total == 1
    assert result.users[0].user_id == user.id
    assert result.users[0].fullname == "Dawa Norbu"
    assert result.users[0].joined_at == joined_at


# --- the guard is wired into every path that can re-create a join ----------
#
# The unit tests for those paths stub the guard out, so these assert the call
# is still there. Delete the guard and these fail, not just the integration.


def test_join_group_consults_the_ban_guard() -> None:
    group = _make_group()
    user = _make_user()

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_user_details", return_value=user
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}.is_group_published", return_value=True
    ), patch(
        f"{SERVICE}._assert_group_allows_engagement"
    ), patch(
        f"{SERVICE}.upsert_group_join"
    ), patch(
        f"{SERVICE}.assert_user_not_banned_from_group"
    ) as mock_guard:
        _session(mock_session)
        from pecha_api.plans.groups.groups_service import join_group

        join_group(token="t", group_id=group.id)

    assert mock_guard.call_args.kwargs["group_id"] == group.id
    assert mock_guard.call_args.kwargs["user_id"] == user.id


def test_join_group_request_consults_the_ban_guard() -> None:
    from pecha_api.plans.groups.groups_enums import AuthorGroupJoinRequestStatus

    group = _make_group()
    group.is_public = False
    group.metadata_entries = []
    user = _make_user()
    created = MagicMock()
    created.id = uuid4()
    created.status = AuthorGroupJoinRequestStatus.PENDING.value

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_user_details", return_value=user
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}.is_group_published", return_value=True
    ), patch(
        f"{SERVICE}._assert_group_allows_engagement"
    ), patch(
        f"{SERVICE}.lock_group_visibility", return_value=False
    ), patch(
        f"{SERVICE}.is_user_joined_group", return_value=False
    ), patch(
        f"{SERVICE}.has_pending_join_request", return_value=False
    ), patch(
        f"{SERVICE}.create_group_join_request", return_value=created
    ), patch(
        f"{SERVICE}.list_group_member_ids_by_roles", return_value=[]
    ), patch(
        f"{SERVICE}.enqueue_join_request_created"
    ), patch(
        f"{SERVICE}.assert_user_not_banned_from_group"
    ) as mock_guard:
        _session(mock_session)
        from pecha_api.plans.groups.groups_response_models import CreateGroupJoinRequest
        from pecha_api.plans.groups.groups_service import submit_group_join_request

        submit_group_join_request(
            token="t", group_id=group.id, request=CreateGroupJoinRequest(message=None)
        )

    assert mock_guard.call_args.kwargs["group_id"] == group.id
    assert mock_guard.call_args.kwargs["user_id"] == user.id


def test_accumulator_join_consults_the_ban_guard() -> None:
    """Joining an accumulator joins the parent group, so it must check too."""
    accumulator_service = "pecha_api.group_accumulator.group_accumulator_service"
    group = _make_group()
    user = _make_user()
    accumulator = MagicMock()
    accumulator.id = uuid4()
    accumulator.group_id = group.id

    with patch(f"{accumulator_service}.SessionLocal") as mock_session, patch(
        f"{accumulator_service}.validate_and_extract_user_details", return_value=user
    ), patch(
        f"{accumulator_service}.get_group_accumulator_by_id", return_value=accumulator
    ), patch(
        f"{accumulator_service}.get_group_by_id", return_value=group
    ), patch(
        f"{accumulator_service}.is_group_published", return_value=True
    ), patch(
        f"{accumulator_service}._assert_group_allows_join"
    ), patch(
        f"{accumulator_service}.upsert_group_join"
    ), patch(
        f"{accumulator_service}.upsert_group_accumulator_join"
    ), patch(
        f"{accumulator_service}.get_or_create_active_user_group_accumulator"
    ), patch(
        f"{accumulator_service}.assert_user_not_banned_from_group"
    ) as mock_guard:
        _session(mock_session)
        from pecha_api.group_accumulator.group_accumulator_service import (
            join_group_accumulator_service,
        )

        join_group_accumulator_service(
            token="t", group_accumulator_id=accumulator.id
        )

    assert mock_guard.call_args.kwargs["group_id"] == group.id
    assert mock_guard.call_args.kwargs["user_id"] == user.id


# --- removal is one transaction, ordered against a concurrent join ---------


def test_remove_lands_the_membership_the_chat_room_and_the_ban_in_one_commit() -> None:
    """A failure part way through must not leave the user removed but unbanned:
    a retry would then 404 on "not joined", with the moderation left half done."""
    group = _make_group()
    user_id = uuid4()

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_user_by_id", return_value=_make_user(user_id)
    ), patch(
        f"{SERVICE}.is_user_joined_group", return_value=True
    ), patch(
        f"{SERVICE}.remove_group_accumulator_joins_for_group"
    ), patch(
        f"{SERVICE}.leave_group_membership"
    ) as mock_leave, patch(
        f"{SERVICE}.is_user_following_group", return_value=False
    ), patch(
        f"{SERVICE}.leave_group_chat_room"
    ) as mock_chat, patch(
        f"{SERVICE}.create_group_ban",
        return_value=_make_ban(group_id=group.id, user_id=user_id),
    ) as mock_create:
        mock_db = _session(mock_session)
        remove_and_ban_group_user(
            token="t",
            group_id=group.id,
            user_id=user_id,
            request=RemoveGroupUserRequest(),
        )

    assert mock_leave.call_args.kwargs["commit"] is False
    assert mock_chat.call_args.kwargs["commit"] is False
    assert mock_create.call_args.kwargs["commit"] is False
    # One commit for the whole removal, not one per step.
    mock_db.commit.assert_called_once_with()


def test_remove_locks_the_group_before_it_reads_the_membership() -> None:
    """The lock is what stops a join slipping between the delete and the ban."""
    group = _make_group()
    user_id = uuid4()
    calls = []

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_moderate_group_users"
    ), patch(
        f"{SERVICE}.get_user_by_id", return_value=_make_user(user_id)
    ), patch(
        f"{SERVICE}.lock_group_membership_changes",
        side_effect=lambda **kwargs: calls.append("lock"),
    ) as mock_lock, patch(
        f"{SERVICE}.is_user_joined_group",
        side_effect=lambda **kwargs: calls.append("joined") or True,
    ), patch(
        f"{SERVICE}.remove_group_accumulator_joins_for_group"
    ), patch(
        f"{SERVICE}.leave_group_membership"
    ), patch(
        f"{SERVICE}.is_user_following_group", return_value=False
    ), patch(
        f"{SERVICE}.leave_group_chat_room"
    ), patch(
        f"{SERVICE}.create_group_ban",
        return_value=_make_ban(group_id=group.id, user_id=user_id),
    ):
        _session(mock_session)
        remove_and_ban_group_user(
            token="t",
            group_id=group.id,
            user_id=user_id,
            request=RemoveGroupUserRequest(),
        )

    assert mock_lock.call_args.kwargs["group_id"] == group.id
    assert calls == ["lock", "joined"]


def test_join_group_takes_the_same_lock_before_reading_the_ban() -> None:
    group = _make_group()
    user = _make_user()
    calls = []

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_user_details", return_value=user
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}.is_group_published", return_value=True
    ), patch(
        f"{SERVICE}._assert_group_allows_engagement"
    ), patch(
        f"{SERVICE}.lock_group_membership_changes",
        side_effect=lambda **kwargs: calls.append("lock"),
    ), patch(
        f"{SERVICE}.assert_user_not_banned_from_group",
        side_effect=lambda **kwargs: calls.append("ban"),
    ), patch(
        f"{SERVICE}.upsert_group_join"
    ):
        _session(mock_session)
        from pecha_api.plans.groups.groups_service import join_group

        join_group(token="t", group_id=group.id)

    assert calls == ["lock", "ban"]


# --- the other paths that write author_group_joins -------------------------


def _make_pending_join_request(*, group_id: UUID, user_id: UUID) -> MagicMock:
    from pecha_api.plans.groups.groups_enums import AuthorGroupJoinRequestStatus

    join_request = MagicMock()
    join_request.id = uuid4()
    join_request.group_id = group_id
    join_request.user_id = user_id
    join_request.status = AuthorGroupJoinRequestStatus.PENDING.value
    return join_request


def test_approving_a_join_request_refuses_a_banned_applicant() -> None:
    """A request can outlive the membership it was made for: a series enrolment
    can join the user while it is pending, and they can then be banned."""
    from pecha_api.plans.groups.groups_service import (
        USER_BANNED_FROM_GROUP,
        approve_group_join_request,
    )

    group = _make_group()
    user_id = uuid4()
    join_request = _make_pending_join_request(group_id=group.id, user_id=user_id)

    with patch(f"{SERVICE}.SessionLocal") as mock_session, patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=_make_author()
    ), patch(f"{SERVICE}.get_group_by_id", return_value=group), patch(
        f"{SERVICE}._assert_can_manage_join_requests"
    ), patch(
        f"{SERVICE}.lock_group_membership_changes"
    ), patch(
        f"{SERVICE}.get_join_request_by_id", return_value=join_request
    ), patch(
        f"{SERVICE}.get_group_ban_expiry",
        return_value=datetime.now(timezone.utc) + timedelta(days=3),
    ), patch(
        f"{SERVICE}.upsert_group_join"
    ) as mock_join, patch(
        f"{SERVICE}.save_join_request"
    ) as mock_save:
        _session(mock_session)
        with pytest.raises(HTTPException) as exc:
            approve_group_join_request(
                token="t", group_id=group.id, request_id=join_request.id
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.value.detail == USER_BANNED_FROM_GROUP
    mock_join.assert_not_called()
    mock_save.assert_not_called()


def test_publishing_a_group_leaves_a_banned_applicant_pending() -> None:
    """The publish sweep admits everyone waiting, so it has to skip bans too."""
    from pecha_api.plans.groups.groups_enums import AuthorGroupJoinRequestStatus
    from pecha_api.plans.groups.groups_service import (
        _approve_pending_join_requests_on_publish,
    )

    group_id = uuid4()
    banned_user_id = uuid4()
    allowed = _make_pending_join_request(group_id=group_id, user_id=uuid4())
    banned = _make_pending_join_request(group_id=group_id, user_id=banned_user_id)

    def _expiry(db: MagicMock, *, group_id: UUID, user_id: UUID) -> Optional[datetime]:
        if user_id == banned_user_id:
            return datetime.now(timezone.utc) + timedelta(days=3)
        return None

    with patch(
        f"{SERVICE}.list_pending_join_requests_by_group", return_value=[allowed, banned]
    ), patch(
        f"{SERVICE}.get_group_ban_expiry", side_effect=_expiry
    ), patch(
        f"{SERVICE}.upsert_group_join"
    ) as mock_join:
        _approve_pending_join_requests_on_publish(MagicMock(), group_id=group_id)

    assert mock_join.call_count == 1
    assert mock_join.call_args.kwargs["user_id"] == allowed.user_id
    assert allowed.status == AuthorGroupJoinRequestStatus.APPROVED.value
    # Left for a moderator to decide once the ban has lifted.
    assert banned.status == AuthorGroupJoinRequestStatus.PENDING.value


def test_series_enrolment_into_a_partner_group_consults_the_ban_guard() -> None:
    """Enrolling in a series joins its partner group, banned user or not."""
    from types import SimpleNamespace

    from pecha_api.plans.users.plan_users_response_models import UserSeriesEnrollRequest

    plan_users = "pecha_api.plans.users.plan_users_service"
    user = _make_user()
    series_id = uuid4()
    group_id = uuid4()

    with patch(f"{plan_users}.SessionLocal") as mock_session, patch(
        f"{plan_users}.validate_and_extract_user_details",
        return_value=SimpleNamespace(id=user.id),
    ), patch(
        f"{plan_users}.get_user_series_enrollment_by_user_and_series", return_value=None
    ), patch(
        f"{plan_users}.get_series_partner",
        return_value=SimpleNamespace(id=uuid4(), series_id=series_id, group_id=group_id),
    ), patch(
        f"{plan_users}.save_user_series_enrollment"
    ), patch(
        f"{plan_users}.lock_group_membership_changes"
    ), patch(
        f"{plan_users}.upsert_group_join"
    ), patch(
        f"{plan_users}.assert_user_not_banned_from_group"
    ) as mock_guard:
        _session(mock_session)
        from pecha_api.plans.users.plan_users_service import enroll_user_in_series

        enroll_user_in_series(
            token="t",
            enroll_request=UserSeriesEnrollRequest(series_id=series_id, group_id=group_id),
        )

    assert mock_guard.call_args.kwargs["group_id"] == group_id
    assert mock_guard.call_args.kwargs["user_id"] == user.id
