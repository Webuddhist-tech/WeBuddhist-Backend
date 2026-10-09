from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

import pecha_api.app  # noqa: F401  - registers every mapper before compiling

from pecha_api.notification.notification_preference_enums import NotificationType
from pecha_api.push_devices.push_device_enums import PushPlatform
from pecha_api.routines.routine_notifications.routine_notification_repository import (
    _enum_value,
    _normalize_platform,
    get_users_with_matching_timeblocks,
)
from pecha_api.routines.routines_enums import SessionType


def test_enum_value_from_session_type_enum():
    assert _enum_value(SessionType.SERIES) == "SERIES"
    assert _enum_value(SessionType.PLAN) == "PLAN"


def test_enum_value_from_stringified_enum_name():
    assert _enum_value("SessionType.SERIES") == "SERIES"
    assert _enum_value("SessionType.PLAN") == "PLAN"


def test_enum_value_from_plain_string():
    assert _enum_value("SERIES") == "SERIES"


def test_normalize_platform_from_push_platform_enum():
    assert _normalize_platform(PushPlatform.ANDROID) == "android"
    assert _normalize_platform(PushPlatform.IOS) == "ios"


def test_normalize_platform_from_stringified_enum_name():
    assert _normalize_platform("PushPlatform.ANDROID") == "android"
    assert _normalize_platform("pushplatform.android") == "android"


def test_normalize_platform_from_plain_string():
    assert _normalize_platform("ANDROID") == "android"


def _compiled_timeblock_query():
    db = MagicMock()
    db.execute.return_value.all.return_value = []
    get_users_with_matching_timeblocks(db)
    statement = db.execute.call_args[0][0]
    return statement.compile(dialect=postgresql.dialect())


def test_series_reminders_are_filtered_by_the_series_preference():
    """Regression guard: SERIES is a user-facing toggle, so a series reminder
    must not be built for someone who turned it off or snoozed it. SERIES is
    not group-scoped, so the GLOBAL row alone decides."""
    compiled = _compiled_timeblock_query()
    sql = str(compiled)

    assert "user_notification_preferences" in sql
    assert "NOT (EXISTS" in sql
    assert NotificationType.SERIES in compiled.params.values()


def test_plan_reminders_are_left_alone():
    """PLAN sessions map to ROUTINE_REMINDER, which has no v1 toggle - the
    guard has to stay conditional on the session being a SERIES."""
    compiled = _compiled_timeblock_query()

    assert "routine_sessions.session_type != " in str(compiled)
    assert SessionType.SERIES in compiled.params.values()
