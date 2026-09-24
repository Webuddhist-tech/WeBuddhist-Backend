from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

import pecha_api.app  # noqa: F401

from pecha_api.notification.notification_preference_enums import (
    NotificationChannel,
    NotificationScope,
    NotificationType,
    PreferenceSource,
    V1_GROUP_TOGGLEABLE_TYPES,
)
from pecha_api.notification.notification_preference_response_models import (
    NotificationPreferenceUpdateDTO,
    UpdateNotificationPreferencesRequest,
)
from pecha_api.notification.notification_preference_service import (
    _apply_updates,
    _expand,
    _resolve,
    delete_group_notification_preferences_service,
    get_group_notification_preferences_service,
    update_group_notification_preferences_service,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
GROUP_ID = uuid4()
USER_ID = uuid4()

SERVICE = "pecha_api.notification.notification_preference_service"


def _row(notification_type, *, enabled=True, muted_until=None, scope_id=None):
    return SimpleNamespace(
        notification_type=notification_type,
        enabled=enabled,
        muted_until=muted_until,
        scope_id=scope_id,
        scope_type=(
            NotificationScope.GLOBAL if scope_id is None else NotificationScope.GROUP
        ),
    )


class TestResolve:
    def test_absent_rows_default_to_allowed(self):
        resolved = _resolve(
            NotificationType.GROUP_POST, group_row=None, global_row=None, now=NOW
        )
        assert resolved.enabled is True
        assert resolved.source == PreferenceSource.DEFAULT

    def test_global_row_applies_when_no_group_row(self):
        resolved = _resolve(
            NotificationType.GROUP_POST,
            group_row=None,
            global_row=_row(NotificationType.GROUP_POST, enabled=False),
            now=NOW,
        )
        assert resolved.enabled is False
        assert resolved.source == PreferenceSource.GLOBAL

    def test_group_row_overrides_global(self):
        """The 'everywhere except this group' case the boolean exists for."""
        resolved = _resolve(
            NotificationType.GROUP_POST,
            group_row=_row(NotificationType.GROUP_POST, enabled=True, scope_id=GROUP_ID),
            global_row=_row(NotificationType.GROUP_POST, enabled=False),
            now=NOW,
        )
        assert resolved.enabled is True
        assert resolved.source == PreferenceSource.GROUP

    def test_global_snooze_reported_even_when_group_row_enables(self):
        """A snooze is not a preference: it outranks an explicit group opt-in."""
        until = NOW + timedelta(hours=8)
        resolved = _resolve(
            NotificationType.CHAT_MESSAGE,
            group_row=_row(NotificationType.CHAT_MESSAGE, enabled=True, scope_id=GROUP_ID),
            global_row=_row(NotificationType.CHAT_MESSAGE, muted_until=until),
            now=NOW,
        )
        assert resolved.enabled is True
        assert resolved.muted_until == until

    def test_expired_mute_is_inert(self):
        resolved = _resolve(
            NotificationType.EVENT,
            group_row=_row(
                NotificationType.EVENT,
                muted_until=NOW - timedelta(minutes=1),
                scope_id=GROUP_ID,
            ),
            global_row=None,
            now=NOW,
        )
        assert resolved.muted_until is None

    def test_naive_stored_timestamp_is_read_as_utc(self):
        resolved = _resolve(
            NotificationType.EVENT,
            group_row=_row(
                NotificationType.EVENT,
                muted_until=datetime(2026, 9, 9, 20, 0),
                scope_id=GROUP_ID,
            ),
            global_row=None,
            now=NOW,
        )
        assert resolved.muted_until is not None


class TestExpand:
    def test_all_expands_to_group_scoped_types_only(self):
        entry = NotificationPreferenceUpdateDTO(notification_type="ALL", enabled=False)
        assert tuple(_expand(entry, scope_type=NotificationScope.GROUP)) == V1_GROUP_TOGGLEABLE_TYPES

    def test_non_group_scoped_type_rejected_on_group_scope(self):
        entry = NotificationPreferenceUpdateDTO(
            notification_type="VERSE_OF_DAY", enabled=False
        )
        with pytest.raises(HTTPException) as exception:
            _expand(entry, scope_type=NotificationScope.GROUP)
        assert exception.value.status_code == 422

    def test_transactional_type_rejected_everywhere(self):
        entry = NotificationPreferenceUpdateDTO(
            notification_type="GROUP_JOIN_REQUEST", enabled=False
        )
        with pytest.raises(HTTPException) as exception:
            _expand(entry, scope_type=None)
        assert exception.value.status_code == 422

    def test_unknown_type_rejected_by_the_request_model(self):
        with pytest.raises(ValueError):
            NotificationPreferenceUpdateDTO(notification_type="NOT_A_TYPE", enabled=False)


class TestSparseUpdates:
    """An absent key and an explicit null mean different things."""

    def test_omitted_field_is_not_written(self):
        entry = NotificationPreferenceUpdateDTO(
            notification_type="EVENT", muted_until=NOW + timedelta(hours=1)
        )
        assert entry.sets_muted_until is True
        assert entry.sets_enabled is False

    def test_explicit_null_clears_the_snooze(self):
        entry = NotificationPreferenceUpdateDTO(
            notification_type="EVENT", muted_until=None
        )
        assert entry.sets_muted_until is True

    @patch(f"{SERVICE}.upsert_preference")
    def test_only_named_types_are_upserted(self, mock_upsert):
        _apply_updates(
            db=MagicMock(),
            user_id=USER_ID,
            channel=NotificationChannel.PUSH,
            scope_id=GROUP_ID,
            request=UpdateNotificationPreferencesRequest(
                preferences=[
                    NotificationPreferenceUpdateDTO(
                        notification_type="EVENT", enabled=True
                    )
                ]
            ),
            now=NOW,
        )
        assert mock_upsert.call_count == 1
        assert mock_upsert.call_args.kwargs["notification_type"] == NotificationType.EVENT
        assert mock_upsert.call_args.kwargs["set_enabled"] is True
        assert mock_upsert.call_args.kwargs["set_muted_until"] is False

    @patch(f"{SERVICE}.upsert_preference")
    def test_all_writes_one_row_per_group_scoped_type(self, mock_upsert):
        _apply_updates(
            db=MagicMock(),
            user_id=USER_ID,
            channel=NotificationChannel.PUSH,
            scope_id=GROUP_ID,
            request=UpdateNotificationPreferencesRequest(
                preferences=[
                    NotificationPreferenceUpdateDTO(
                        notification_type="ALL",
                        muted_until=NOW + timedelta(hours=8),
                    )
                ]
            ),
            now=NOW,
        )
        assert mock_upsert.call_count == len(V1_GROUP_TOGGLEABLE_TYPES)

    @patch(f"{SERVICE}.upsert_preference")
    def test_all_plus_an_explicit_type_writes_that_type_once(self, mock_upsert):
        """Regression guard: the "mute the group but keep chat" body names
        CHAT_MESSAGE twice, once through ALL. Two writes for one key stage two
        inserts that collide on the partial unique index at commit, taking the
        whole request down with an IntegrityError."""
        _apply_updates(
            db=MagicMock(),
            user_id=USER_ID,
            channel=NotificationChannel.PUSH,
            scope_id=GROUP_ID,
            request=UpdateNotificationPreferencesRequest(
                preferences=[
                    NotificationPreferenceUpdateDTO(
                        notification_type="ALL",
                        muted_until=NOW + timedelta(hours=8),
                    ),
                    NotificationPreferenceUpdateDTO(
                        notification_type="CHAT_MESSAGE", enabled=True
                    ),
                ]
            ),
            now=NOW,
        )

        assert mock_upsert.call_count == len(V1_GROUP_TOGGLEABLE_TYPES)
        written = [
            call.kwargs["notification_type"] for call in mock_upsert.call_args_list
        ]
        assert len(written) == len(set(written))

    @patch(f"{SERVICE}.upsert_preference")
    def test_the_later_entry_wins_field_by_field(self, mock_upsert):
        """Merging keeps the snooze ALL set and takes `enabled` from the
        entry that named it - neither field is lost to the other."""
        muted_until = NOW + timedelta(hours=8)
        _apply_updates(
            db=MagicMock(),
            user_id=USER_ID,
            channel=NotificationChannel.PUSH,
            scope_id=GROUP_ID,
            request=UpdateNotificationPreferencesRequest(
                preferences=[
                    NotificationPreferenceUpdateDTO(
                        notification_type="ALL", muted_until=muted_until
                    ),
                    NotificationPreferenceUpdateDTO(
                        notification_type="EVENT", enabled=False
                    ),
                ]
            ),
            now=NOW,
        )

        event_call = next(
            call
            for call in mock_upsert.call_args_list
            if call.kwargs["notification_type"] == NotificationType.EVENT
        )
        assert event_call.kwargs["set_muted_until"] is True
        assert event_call.kwargs["muted_until"] == muted_until
        assert event_call.kwargs["set_enabled"] is True
        assert event_call.kwargs["enabled"] is False

    @patch(f"{SERVICE}.upsert_preference")
    def test_the_same_type_twice_collapses_to_one_write(self, mock_upsert):
        _apply_updates(
            db=MagicMock(),
            user_id=USER_ID,
            channel=NotificationChannel.PUSH,
            scope_id=GROUP_ID,
            request=UpdateNotificationPreferencesRequest(
                preferences=[
                    NotificationPreferenceUpdateDTO(
                        notification_type="EVENT", enabled=True
                    ),
                    NotificationPreferenceUpdateDTO(
                        notification_type="EVENT", enabled=False
                    ),
                ]
            ),
            now=NOW,
        )

        assert mock_upsert.call_count == 1
        assert mock_upsert.call_args.kwargs["enabled"] is False

    def test_past_muted_until_is_rejected(self):
        with pytest.raises(HTTPException) as exception:
            _apply_updates(
                db=MagicMock(),
                user_id=USER_ID,
                channel=NotificationChannel.PUSH,
                scope_id=GROUP_ID,
                request=UpdateNotificationPreferencesRequest(
                    preferences=[
                        NotificationPreferenceUpdateDTO(
                            notification_type="EVENT",
                            muted_until=NOW - timedelta(hours=1),
                        )
                    ]
                ),
                now=NOW,
            )
        assert exception.value.status_code == 422

    def test_entry_naming_no_change_is_rejected(self):
        with pytest.raises(HTTPException) as exception:
            _apply_updates(
                db=MagicMock(),
                user_id=USER_ID,
                channel=NotificationChannel.PUSH,
                scope_id=None,
                request=UpdateNotificationPreferencesRequest(
                    preferences=[
                        NotificationPreferenceUpdateDTO(notification_type="EVENT")
                    ]
                ),
                now=NOW,
            )
        assert exception.value.status_code == 422


class TestGroupEndpoints:
    @patch(f"{SERVICE}.list_preferences_for_user", return_value=[])
    @patch(f"{SERVICE}.is_user_joined_group", return_value=True)
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_get_returns_every_group_scoped_type(
        self, mock_user, mock_session, _mock_member, _mock_rows
    ):
        mock_user.return_value = SimpleNamespace(id=USER_ID)

        result = get_group_notification_preferences_service(
            token="t", group_id=GROUP_ID
        )

        assert result.group_id == GROUP_ID
        assert [p.notification_type for p in result.preferences] == list(
            V1_GROUP_TOGGLEABLE_TYPES
        )
        assert all(p.source == PreferenceSource.DEFAULT for p in result.preferences)

    @patch(f"{SERVICE}.is_user_joined_group", return_value=False)
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_non_member_gets_404(self, mock_user, mock_session, _mock_member):
        mock_user.return_value = SimpleNamespace(id=USER_ID)

        with pytest.raises(HTTPException) as exception:
            update_group_notification_preferences_service(
                token="t",
                group_id=GROUP_ID,
                request=UpdateNotificationPreferencesRequest(
                    preferences=[
                        NotificationPreferenceUpdateDTO(
                            notification_type="EVENT", enabled=False
                        )
                    ]
                ),
            )
        assert exception.value.status_code == 404

    @patch(f"{SERVICE}.delete_scoped_preferences", return_value=0)
    @patch(f"{SERVICE}.is_user_joined_group", return_value=True)
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.validate_and_extract_user_details")
    def test_delete_of_absent_rows_is_not_an_error(
        self, mock_user, mock_session, _mock_member, mock_delete
    ):
        mock_user.return_value = SimpleNamespace(id=USER_ID)

        delete_group_notification_preferences_service(token="t", group_id=GROUP_ID)

        assert mock_delete.call_count == 1
