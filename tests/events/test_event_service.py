from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events.event_response_models import EventDTO, EventsResponse
from pecha_api.events.event_service import (
    EventContentFilter,
    _expand_earliest_occurrences,
    can_view_event_linked_content_without_group_join,
    event_has_publishable_linked_content,
    get_events_service,
    get_events_today_service,
)


def test_get_events_today_service_uses_day_bounds() -> None:
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


def test_get_events_service_limits_authenticated_user_to_followed_groups() -> None:
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


def test_get_events_service_can_include_unfollowed_public_groups() -> None:
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


def test_get_events_service_hides_finished_events_even_when_from_date_is_in_the_past() -> None:
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


def test_get_events_service_does_not_expand_recurring_from_historical_from_date() -> None:
    past = datetime(2000, 1, 1, tzinfo=timezone.utc)

    with patch(
        "pecha_api.events.event_service.SessionLocal"
    ) as mock_session, patch(
        "pecha_api.events.event_service.get_events",
        return_value=([], 0),
    ), patch(
        "pecha_api.events.event_service.get_recurring_events",
        return_value=[],
    ), patch(
        "pecha_api.events.event_service.get_event_participant_counts",
        return_value={},
    ), patch(
        "pecha_api.events.event_service._expand_earliest_occurrences",
        return_value=[],
    ) as mock_expand:
        mock_session.return_value.__enter__.return_value = MagicMock()
        get_events_service(from_date=past)

    from_date_obj = mock_expand.call_args.args[1]
    cutoff = mock_expand.call_args.kwargs["not_ended_before"]
    assert from_date_obj != past.date()
    assert from_date_obj == cutoff.date()
    assert cutoff > past


def test_expand_earliest_occurrences_skips_finished_occurrence_when_cutoff_set() -> None:
    template = MagicMock()
    template.start_date = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    template.end_date = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    finished = date(2026, 1, 1)
    upcoming = date(2026, 1, 8)
    cutoff = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    with patch(
        "pecha_api.events.event_service.expand_occurrences",
        return_value=[(finished, finished), (upcoming, upcoming)],
    ):
        result = _expand_earliest_occurrences(
            [template],
            finished,
            upcoming,
            not_ended_before=cutoff,
        )

    assert len(result) == 1
    assert result[0]["start_date"].date() == upcoming


def test_expand_earliest_occurrences_keeps_past_occurrence_without_cutoff() -> None:
    template = MagicMock()
    template.start_date = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    template.end_date = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    finished = date(2026, 1, 1)
    upcoming = date(2026, 1, 8)

    with patch(
        "pecha_api.events.event_service.expand_occurrences",
        return_value=[(finished, finished), (upcoming, upcoming)],
    ):
        result = _expand_earliest_occurrences([template], finished, upcoming)

    assert len(result) == 1
    assert result[0]["start_date"].date() == finished


def test_get_events_service_includes_past_when_requested() -> None:
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
    ), patch(
        "pecha_api.events.event_service._expand_earliest_occurrences",
        return_value=[],
    ) as mock_expand:
        mock_session.return_value.__enter__.return_value = MagicMock()
        get_events_service(should_include_past=True)

    assert mock_get_events.call_args.kwargs["not_ended_before"] is None
    assert mock_get_events.call_args.kwargs["from_date"] is None
    from_date_obj = mock_expand.call_args.args[1]
    assert from_date_obj < datetime.now(timezone.utc).date()
    assert mock_expand.call_args.kwargs["prefer_current_or_last"] is True


def test_expand_earliest_occurrences_cms_prefers_upcoming_then_last_past() -> None:
    template = MagicMock()
    template.start_date = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    template.end_date = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    finished = date(2026, 1, 1)
    upcoming = date(2026, 1, 8)
    reference = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)

    with patch(
        "pecha_api.events.event_service.expand_occurrences",
        return_value=[(finished, finished), (upcoming, upcoming)],
    ):
        result = _expand_earliest_occurrences(
            [template],
            finished,
            upcoming,
            prefer_current_or_last=True,
            reference=reference,
        )

    assert len(result) == 1
    assert result[0]["start_date"].date() == upcoming


def test_expand_earliest_occurrences_cms_keeps_last_past_when_none_upcoming() -> None:
    template = MagicMock()
    template.start_date = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    template.end_date = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    older = date(2025, 12, 25)
    finished = date(2026, 1, 1)
    reference = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)

    with patch(
        "pecha_api.events.event_service.expand_occurrences",
        return_value=[(older, older), (finished, finished)],
    ):
        result = _expand_earliest_occurrences(
            [template],
            older,
            finished,
            prefer_current_or_last=True,
            reference=reference,
        )

    assert len(result) == 1
    assert result[0]["start_date"].date() == finished


def test_get_events_service_accepts_naive_from_date() -> None:
    naive = datetime(2026, 9, 17, 0, 0, 0)

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
    ), patch(
        "pecha_api.events.event_service._expand_earliest_occurrences",
        return_value=[],
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        get_events_service(from_date=naive)

    passed = mock_get_events.call_args.kwargs["from_date"]
    assert passed.tzinfo is not None
    assert passed == datetime(2026, 9, 17, 0, 0, 0, tzinfo=timezone.utc)


def test_event_has_publishable_linked_content_rejects_draft_plan() -> None:
    plan_id = uuid4()
    event = MagicMock(plan_id=plan_id, series_id=None)
    assert (
        event_has_publishable_linked_content(
            event,
            published_plan_ids=set(),
            published_series_ids=set(),
        )
        is False
    )


def test_can_view_linked_content_false_when_plan_hidden_for_timezone() -> None:
    group_id = uuid4()
    plan_id = uuid4()
    event = MagicMock(group_id=group_id, plan_id=plan_id, series_id=None)
    group = MagicMock(is_public=True, status="PUBLISHED")

    with patch(
        "pecha_api.events.event_service.is_group_published",
        return_value=True,
    ), patch(
        "pecha_api.events.event_service.should_hide_for_timezone",
        return_value=True,
    ):
        assert not can_view_event_linked_content_without_group_join(
            event,
            group=group,
            published_plan_ids={plan_id},
            published_series_ids=set(),
            timezone_name="Asia/Shanghai",
        )


def test_can_view_linked_content_without_group_join_is_separate_from_membership() -> None:
    group_id = uuid4()
    plan_id = uuid4()
    event = MagicMock(group_id=group_id, plan_id=plan_id, series_id=None)
    group = MagicMock(is_public=True, status="PUBLISHED")
    published = {plan_id}

    with patch(
        "pecha_api.events.event_service.is_group_published",
        return_value=True,
    ):
        assert can_view_event_linked_content_without_group_join(
            event,
            group=group,
            published_plan_ids=published,
            published_series_ids=set(),
        )
        assert event.group_id not in set()

