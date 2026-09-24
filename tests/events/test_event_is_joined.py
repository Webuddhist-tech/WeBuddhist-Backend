from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events.event_service import (
    get_event_by_id_service,
    get_events_service,
    get_featured_events_service,
)

MODULE = "pecha_api.events.event_service"


def _event(event_id=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=event_id or uuid4(),
        plan_id=None,
        accumulator_id=None,
        mantra_id=None,
        timer_id=None,
        group_recitation_collection_id=None,
        group_id=uuid4(),
        location_id=None,
        location=None,
        start_date=now,
        end_date=now,
        timezone=None,
        notifications_enabled=True,
        image_url=None,
        featured=False,
        event_format="hybrid",
        is_recurring=False,
        metadata_entries=[],
        links=[],
        created_at=now,
        created_by="author@example.com",
        updated_at=None,
    )


def _user(user_id=None):
    return SimpleNamespace(id=user_id or uuid4())


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_events")
def test_list_without_token_leaves_is_joined_null(
    mock_get_events, _mock_counts, _mock_groups, mock_session
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event()
    mock_get_events.return_value = ([event], 1)

    result = get_events_service()

    assert result.events[0].is_joined is None


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.validate_and_extract_user_details")
@patch(f"{MODULE}.get_joined_event_ids_by_user")
@patch(f"{MODULE}.get_event_participant_counts")
@patch(f"{MODULE}.get_events")
def test_list_with_token_sets_is_joined(
    mock_get_events,
    mock_counts,
    mock_joined_ids,
    mock_validate,
    _mock_groups,
    mock_session,
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    joined = _event()
    not_joined = _event()
    mock_get_events.return_value = ([joined, not_joined], 2)
    mock_counts.return_value = {joined.id: 3, not_joined.id: 1}
    user = _user()
    mock_validate.return_value = user
    mock_joined_ids.return_value = [joined.id]

    result = get_events_service(token="user-token")

    by_id = {event.id: event for event in result.events}
    assert by_id[joined.id].is_joined is True
    assert by_id[not_joined.id].is_joined is False
    mock_validate.assert_called_once_with(token="user-token")
    mock_joined_ids.assert_called_once()
    assert mock_joined_ids.call_args.kwargs["user_id"] == user.id
    assert set(mock_joined_ids.call_args.kwargs["event_ids"]) == {
        joined.id,
        not_joined.id,
    }


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_count", return_value=2)
@patch(f"{MODULE}.get_event_by_id")
def test_detail_without_token_leaves_is_joined_null(
    mock_get_by_id, _mock_count, _mock_groups, mock_session
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event()
    mock_get_by_id.return_value = event

    result = get_event_by_id_service(event_id=event.id)

    assert result.is_joined is None


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.validate_and_extract_user_details")
@patch(f"{MODULE}.get_user_participation_type", return_value="online")
@patch(f"{MODULE}.is_user_joined_event", return_value=True)
@patch(f"{MODULE}.get_event_participant_count", return_value=2)
@patch(f"{MODULE}.get_event_by_id")
def test_detail_with_token_sets_is_joined_true(
    mock_get_by_id,
    _mock_count,
    mock_is_joined,
    _mock_participation_type,
    mock_validate,
    _mock_groups,
    mock_session,
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event()
    mock_get_by_id.return_value = event
    user = _user()
    mock_validate.return_value = user

    result = get_event_by_id_service(event_id=event.id, token="user-token")

    assert result.is_joined is True
    assert result.my_participation_type == "online"
    mock_is_joined.assert_called_once_with(
        db=mock_session.return_value.__enter__.return_value,
        event_id=event.id,
        user_id=user.id,
    )


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.validate_and_extract_user_details")
@patch(f"{MODULE}.is_user_joined_event", return_value=False)
@patch(f"{MODULE}.get_event_participant_count", return_value=0)
@patch(f"{MODULE}.get_event_by_id")
def test_detail_with_token_sets_is_joined_false(
    mock_get_by_id,
    _mock_count,
    mock_is_joined,
    mock_validate,
    _mock_groups,
    mock_session,
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event()
    mock_get_by_id.return_value = event
    mock_validate.return_value = _user()

    result = get_event_by_id_service(event_id=event.id, token="user-token")

    assert result.is_joined is False
    mock_is_joined.assert_called_once()


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.validate_and_extract_user_details")
@patch(f"{MODULE}.get_joined_event_ids_by_user")
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_featured_events")
def test_featured_with_token_sets_is_joined(
    mock_get_featured,
    _mock_counts,
    mock_joined_ids,
    mock_validate,
    _mock_groups,
    mock_session,
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    joined = _event()
    not_joined = _event()
    joined.featured = True
    not_joined.featured = True
    mock_get_featured.return_value = [joined, not_joined]
    mock_validate.return_value = _user()
    mock_joined_ids.return_value = [joined.id]

    result = get_featured_events_service(token="user-token")

    by_id = {event.id: event for event in result}
    assert by_id[joined.id].is_joined is True
    assert by_id[not_joined.id].is_joined is False


# --- my_participation_type on the read paths ---


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_participation_types_by_user")
@patch(f"{MODULE}.validate_and_extract_user_details")
@patch(f"{MODULE}.get_joined_event_ids_by_user")
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_events")
def test_list_surfaces_my_participation_type_only_for_the_caller(
    mock_get_events,
    _mock_counts,
    mock_joined_ids,
    mock_validate,
    mock_types,
    _mock_groups,
    mock_session,
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    online = _event()
    undecided = _event()
    not_joined = _event()
    mock_get_events.return_value = ([online, undecided, not_joined], 3)
    user = _user()
    mock_validate.return_value = user
    mock_joined_ids.return_value = [online.id, undecided.id]
    # the repository leaves out participants who never picked
    mock_types.return_value = {online.id: "online"}

    result = get_events_service(token="user-token")

    by_id = {event.id: event for event in result.events}
    assert by_id[online.id].my_participation_type == "online"
    assert by_id[undecided.id].my_participation_type is None
    assert by_id[not_joined.id].my_participation_type is None
    # only the events they actually joined are looked up
    assert set(mock_types.call_args.kwargs["event_ids"]) == {online.id, undecided.id}
    assert mock_types.call_args.kwargs["user_id"] == user.id


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_participation_types_by_user")
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_events")
def test_list_without_token_skips_the_participation_lookup(
    mock_get_events, _mock_counts, mock_types, _mock_groups, mock_session
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event()
    mock_get_events.return_value = ([event], 1)

    result = get_events_service()

    assert result.events[0].my_participation_type is None
    mock_types.assert_not_called()


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_user_participation_type", return_value="offline")
@patch(f"{MODULE}.validate_and_extract_user_details")
@patch(f"{MODULE}.is_user_joined_event", return_value=True)
@patch(f"{MODULE}.get_event_participant_count", return_value=1)
@patch(f"{MODULE}.get_event_by_id")
def test_detail_surfaces_my_participation_type(
    mock_get_by_id,
    _mock_count,
    _mock_is_joined,
    mock_validate,
    mock_type,
    _mock_groups,
    mock_session,
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event()
    mock_get_by_id.return_value = event
    user = _user()
    mock_validate.return_value = user

    result = get_event_by_id_service(event_id=event.id, token="user-token")

    assert result.my_participation_type == "offline"
    assert mock_type.call_args.kwargs["user_id"] == user.id


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_user_participation_type")
@patch(f"{MODULE}.validate_and_extract_user_details")
@patch(f"{MODULE}.is_user_joined_event", return_value=False)
@patch(f"{MODULE}.get_event_participant_count", return_value=0)
@patch(f"{MODULE}.get_event_by_id")
def test_detail_skips_participation_lookup_when_not_joined(
    mock_get_by_id,
    _mock_count,
    _mock_is_joined,
    mock_validate,
    mock_type,
    _mock_groups,
    mock_session,
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event()
    mock_get_by_id.return_value = event
    mock_validate.return_value = _user()

    result = get_event_by_id_service(event_id=event.id, token="user-token")

    assert result.my_participation_type is None
    mock_type.assert_not_called()


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_participation_types_by_user")
@patch(f"{MODULE}.validate_and_extract_user_details")
@patch(f"{MODULE}.get_joined_event_ids_by_user")
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_featured_events")
def test_featured_surfaces_my_participation_type(
    mock_get_featured,
    _mock_counts,
    mock_joined_ids,
    mock_validate,
    mock_types,
    _mock_groups,
    mock_session,
):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event()
    event.featured = True
    mock_get_featured.return_value = [event]
    mock_validate.return_value = _user()
    mock_joined_ids.return_value = [event.id]
    mock_types.return_value = {event.id: "online"}

    result = get_featured_events_service(token="user-token")

    assert result[0].my_participation_type == "online"
