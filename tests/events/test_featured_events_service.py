from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.events.event_response_models import EventDTO
from pecha_api.events.event_service import (
    get_featured_events_service,
    update_event_featured_service,
)

MODULE = "pecha_api.events.event_service"


def _author(author_id=None):
    return MagicMock(id=author_id or uuid4())


def _event(event_id=None, group_id=None, featured=False):
    now = datetime.now(timezone.utc)
    event = MagicMock()
    event.id = event_id or uuid4()
    event.plan_id = None
    event.series_id = None
    event.accumulator_id = None
    event.group_accumulator_id = None
    event.mantra_id = None
    event.timer_id = None
    event.group_recitation_collection_id = None
    event.group_id = group_id or uuid4()
    event.location_id = None
    event.location = None
    event.plan = None
    event.series = None
    event.accumulator = None
    event.group_accumulator = None
    event.mantra = None
    event.timer = None
    event.group_recitation_collection = None
    event.start_date = now
    event.end_date = now
    event.timezone = None
    event.image_url = None
    event.featured = featured
    event.event_format = "hybrid"
    event.is_recurring = False
    event.metadata_entries = []
    event.links = []
    event.created_at = now
    event.created_by = "author@example.com"
    event.updated_at = None
    return event


def _recurring_template(event_id=None, group_id=None, featured=False, created_at=None):
    template = _event(event_id=event_id, group_id=group_id, featured=featured)
    template.is_recurring = True
    template.recurrence_frequency = "YEARLY"
    template.recurrence_date_system = "GREGORIAN"
    template.recurrence_calendar_type = None
    template.recurrence_month = 1
    template.recurrence_day = 1
    template.duration_days = 1
    if created_at is not None:
        template.created_at = created_at
    return template


# --------------------------- get_featured_events_service ---------------------------


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_featured_recurring_events", return_value=[])
@patch(f"{MODULE}.get_featured_events")
def test_get_featured_events_returns_list(mock_get_featured, _mock_recurring, _mock_counts, _mock_groups, mock_session):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    
    event1 = _event(featured=True)
    event2 = _event(featured=True)
    mock_get_featured.return_value = [event1, event2]

    result = get_featured_events_service(language="en", limit=10)

    assert len(result) == 2
    assert all(isinstance(e, EventDTO) for e in result)
    assert all(e.is_joined is None for e in result)
    # Service now fetches all featured events and applies limit internally
    mock_get_featured.assert_called_once()
    _, kwargs = mock_get_featured.call_args
    assert kwargs["limit"] is None
    assert kwargs["not_ended_before"] is not None


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_featured_recurring_events", return_value=[])
@patch(f"{MODULE}.get_featured_events")
def test_get_featured_events_empty_list(mock_get_featured, _mock_recurring, _mock_counts, mock_session):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    mock_get_featured.return_value = []

    result = get_featured_events_service(language="en", limit=10)

    assert result == []
    mock_get_featured.assert_called_once()
    assert mock_get_featured.call_args.kwargs["limit"] is None
    assert mock_get_featured.call_args.kwargs["not_ended_before"] is not None


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_featured_recurring_events", return_value=[])
@patch(f"{MODULE}.get_featured_events")
def test_get_featured_events_with_language(mock_get_featured, _mock_recurring, _mock_counts, _mock_groups, mock_session):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    
    event = _event(featured=True)
    mock_get_featured.return_value = [event]

    result = get_featured_events_service(language="bo", limit=5)

    assert len(result) == 1
    mock_get_featured.assert_called_once()
    assert mock_get_featured.call_args.kwargs["limit"] is None
    assert mock_get_featured.call_args.kwargs["not_ended_before"] is not None


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_featured_recurring_events", return_value=[])
@patch(f"{MODULE}.get_featured_events")
def test_get_featured_events_respects_limit(mock_get_featured, _mock_recurring, _mock_counts, _mock_groups, mock_session):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    
    events = [_event(featured=True) for _ in range(3)]
    mock_get_featured.return_value = events

    result = get_featured_events_service(limit=3)

    assert len(result) == 3
    # Service fetches all and applies limit internally
    mock_get_featured.assert_called_once()
    assert mock_get_featured.call_args.kwargs["limit"] is None
    assert mock_get_featured.call_args.kwargs["not_ended_before"] is not None


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.resolve_current_or_next_occurrence")
@patch(f"{MODULE}.get_featured_recurring_events")
@patch(f"{MODULE}.get_featured_events")
def test_get_featured_events_ranks_non_active_recurring_by_proximity(
    mock_get_featured, mock_get_recurring, mock_resolve, _mock_counts, _mock_groups, mock_session
):
    """A not-yet-started occurrence should rank by how soon it happens, not by
    when its template was created: an imminent occurrence stays competitive
    with recent content, a distant one sinks below it, regardless of the
    template's own created_at."""
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db

    now = datetime.now(timezone.utc)

    recent_one_shot = _event(featured=True)
    recent_one_shot.created_at = now - timedelta(days=1)

    old_one_shot = _event(featured=True)
    old_one_shot.created_at = now - timedelta(days=400)

    # Created just now, but its next occurrence is far away: must NOT jump to
    # the top just because the template itself is fresh.
    soon_recurring = _recurring_template(created_at=now)
    distant_recurring = _recurring_template(created_at=now)

    mock_get_featured.return_value = [recent_one_shot, old_one_shot]
    mock_get_recurring.return_value = [soon_recurring, distant_recurring]

    def _resolve(template, after):
        if template is soon_recurring:
            start = (now + timedelta(days=2)).date()
            return (start, start, False)
        if template is distant_recurring:
            start = (now + timedelta(days=500)).date()
            return (start, start, False)
        return None

    mock_resolve.side_effect = _resolve

    result = get_featured_events_service(limit=10)

    assert [e.id for e in result] == [
        recent_one_shot.id,
        soon_recurring.id,
        old_one_shot.id,
        distant_recurring.id,
    ]


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.resolve_current_or_next_occurrence")
@patch(f"{MODULE}.get_featured_recurring_events")
@patch(f"{MODULE}.get_featured_events")
def test_get_featured_events_active_recurring_ranks_by_start_date(
    mock_get_featured, mock_get_recurring, mock_resolve, _mock_counts, _mock_groups, mock_session
):
    """Active (already-started) occurrences rank by their own start_date so
    multiple active events don't all tie at 'now'."""
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db

    now = datetime.now(timezone.utc)

    older_one_shot = _event(featured=True)
    older_one_shot.created_at = now - timedelta(days=10)

    started_recently = _recurring_template(created_at=now - timedelta(days=300))
    started_earlier = _recurring_template(created_at=now - timedelta(days=300))

    mock_get_featured.return_value = [older_one_shot]
    mock_get_recurring.return_value = [started_recently, started_earlier]

    def _resolve(template, after):
        if template is started_recently:
            start = (now - timedelta(days=1)).date()
            return (start, start, True)
        if template is started_earlier:
            start = (now - timedelta(days=5)).date()
            return (start, start, True)
        return None

    mock_resolve.side_effect = _resolve

    result = get_featured_events_service(limit=10)

    assert [e.id for e in result] == [
        started_recently.id,
        started_earlier.id,
        older_one_shot.id,
    ]


# --------------------------- update_event_featured_service ---------------------------


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.validate_cms_author_details")
@patch(f"{MODULE}.get_event_by_id")
@patch(f"{MODULE}.require_can_change_status")
@patch(f"{MODULE}.update_event")
def test_update_featured_toggles_false_to_true(
    mock_update, mock_require, mock_get_by_id, mock_validate, mock_session
):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    
    author = _author()
    mock_validate.return_value = author
    
    event = _event(featured=False)
    mock_get_by_id.return_value = event

    update_event_featured_service(token="tok", event_id=event.id)

    assert event.featured is True
    assert event.updated_at is not None
    mock_require.assert_called_once_with(db=mock_db, group_id=event.group_id, author=author)
    mock_update.assert_called_once_with(mock_db, event)


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.validate_cms_author_details")
@patch(f"{MODULE}.get_event_by_id")
@patch(f"{MODULE}.require_can_change_status")
@patch(f"{MODULE}.update_event")
def test_update_featured_toggles_true_to_false(
    mock_update, mock_require, mock_get_by_id, mock_validate, mock_session
):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    
    author = _author()
    mock_validate.return_value = author
    
    event = _event(featured=True)
    mock_get_by_id.return_value = event

    update_event_featured_service(token="tok", event_id=event.id)

    assert event.featured is False
    assert event.updated_at is not None
    mock_require.assert_called_once_with(db=mock_db, group_id=event.group_id, author=author)
    mock_update.assert_called_once_with(mock_db, event)


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.validate_cms_author_details")
@patch(f"{MODULE}.get_event_by_id")
def test_update_featured_404_when_not_found(mock_get_by_id, mock_validate, mock_session):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    
    mock_validate.return_value = _author()
    mock_get_by_id.return_value = None
    
    event_id = uuid4()

    with pytest.raises(HTTPException) as exc:
        update_event_featured_service(token="tok", event_id=event_id)

    assert exc.value.status_code == 404
    assert f"Event with id '{event_id}' not found" in exc.value.detail


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.validate_cms_author_details")
@patch(f"{MODULE}.get_event_by_id")
@patch(f"{MODULE}.require_can_change_status")
def test_update_featured_403_no_permission(
    mock_require, mock_get_by_id, mock_validate, mock_session
):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    
    author = _author()
    mock_validate.return_value = author
    
    event = _event(featured=False)
    mock_get_by_id.return_value = event
    
    mock_require.side_effect = HTTPException(status_code=403, detail="STATUS_CHANGE_FORBIDDEN")

    with pytest.raises(HTTPException) as exc:
        update_event_featured_service(token="tok", event_id=event.id)

    assert exc.value.status_code == 403


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.validate_cms_author_details")
@patch(f"{MODULE}.get_event_by_id")
@patch(f"{MODULE}.require_can_change_status")
@patch(f"{MODULE}.update_event")
def test_update_featured_updates_timestamp(
    mock_update, mock_require, mock_get_by_id, mock_validate, mock_session
):
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    
    author = _author()
    mock_validate.return_value = author
    
    event = _event(featured=False)
    event.updated_at = None
    mock_get_by_id.return_value = event

    update_event_featured_service(token="tok", event_id=event.id)

    assert event.updated_at is not None
    assert event.updated_at.tzinfo is not None
    mock_update.assert_called_once_with(mock_db, event)
