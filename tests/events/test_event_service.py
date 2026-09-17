from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events.event_response_models import EventDTO, EventsResponse
from pecha_api.events.event_service import (
    EventContentFilter,
    get_events_service,
    get_events_today_service,
)


def test_get_events_today_service_uses_day_bounds():
    start = datetime(2026, 6, 23, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 23, 23, 59, 59, 999999, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    event = EventDTO(
        id=uuid4(),
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        is_one_day=True,
        featured=False,
        metadata=[],
        created_at=now,
        created_by="author@example.com",
    )
    expected = EventsResponse(events=[event], total=1, skip=0, limit=20)

    with patch(
        "pecha_api.events.event_service.get_day_bounds_in_timezone",
        return_value=(start, end),
    ) as mock_bounds, patch(
        "pecha_api.events.event_service.get_events_service",
        return_value=expected,
    ) as mock_get_events:
        result = get_events_today_service(timezone="Asia/Kathmandu", language="en")

    mock_bounds.assert_called_once_with("Asia/Kathmandu")
    mock_get_events.assert_called_once_with(
        content_filter=EventContentFilter(group_id=None),
        from_date=start,
        to_date=end,
        language="en",
        fallback=True,
        should_include_unfollowed=False,
        skip=0,
        limit=20,
        token=None,
    )
    assert result == expected


def test_get_events_service_limits_authenticated_user_to_followed_groups():
    user = MagicMock(id=uuid4())
    followed_group_id = uuid4()

    with patch(
        "pecha_api.events.event_service.SessionLocal"
    ) as mock_session, patch(
        "pecha_api.events.event_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.events.event_service.resolve_public_group_scope",
        return_value=([followed_group_id], {followed_group_id}),
    ) as mock_scope, patch(
        "pecha_api.events.event_service.get_events",
        return_value=([], 0),
    ) as mock_get_events, patch(
        "pecha_api.events.event_service.get_event_participant_counts",
        return_value={},
    ), patch(
        "pecha_api.events.event_service.get_joined_event_ids_by_user",
        return_value=[],
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()

        result = get_events_service(token="token")

    assert result.events == []
    mock_scope.assert_called_once()
    assert mock_scope.call_args.kwargs["should_include_unfollowed"] is False
    assert mock_get_events.call_args.kwargs["restrict_group_ids"] == [
        followed_group_id
    ]


def test_get_events_service_can_include_unfollowed_public_groups():
    user = MagicMock(id=uuid4())
    public_group_ids = [uuid4(), uuid4()]

    with patch(
        "pecha_api.events.event_service.SessionLocal"
    ) as mock_session, patch(
        "pecha_api.events.event_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.events.event_service.resolve_public_group_scope",
        return_value=(public_group_ids, set()),
    ) as mock_scope, patch(
        "pecha_api.events.event_service.get_events",
        return_value=([], 0),
    ) as mock_get_events, patch(
        "pecha_api.events.event_service.get_event_participant_counts",
        return_value={},
    ), patch(
        "pecha_api.events.event_service.get_joined_event_ids_by_user",
        return_value=[],
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()

        get_events_service(
            token="token",
            should_include_unfollowed=True,
        )

    assert mock_scope.call_args.kwargs["should_include_unfollowed"] is True
    assert mock_get_events.call_args.kwargs["restrict_group_ids"] == public_group_ids


def test_get_events_service_hides_finished_events_even_when_from_date_is_in_the_past():
    past = datetime(2000, 1, 1, tzinfo=timezone.utc)

    with patch(
        "pecha_api.events.event_service.SessionLocal"
    ) as mock_session, patch(
        "pecha_api.events.event_service.get_events",
        return_value=([], 0),
    ) as mock_get_events, patch(
        "pecha_api.events.event_service.get_recurring_events",
        return_value=[],
    ), patch(
        "pecha_api.events.event_service.get_event_participant_counts",
        return_value={},
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        get_events_service(from_date=past)

    cutoff = mock_get_events.call_args.kwargs["not_ended_before"]
    assert cutoff is not None
    assert cutoff > past
    assert mock_get_events.call_args.kwargs["from_date"] == past


def test_get_events_service_includes_past_when_requested():
    with patch(
        "pecha_api.events.event_service.SessionLocal"
    ) as mock_session, patch(
        "pecha_api.events.event_service.get_events",
        return_value=([], 0),
    ) as mock_get_events, patch(
        "pecha_api.events.event_service.get_recurring_events",
        return_value=[],
    ), patch(
        "pecha_api.events.event_service.get_event_participant_counts",
        return_value={},
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        get_events_service(should_include_past=True)

    assert mock_get_events.call_args.kwargs["not_ended_before"] is None
    assert mock_get_events.call_args.kwargs["from_date"] is None

