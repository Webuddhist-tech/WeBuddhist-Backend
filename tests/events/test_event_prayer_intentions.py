from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events.event_response_models import (
    CreateEventRequest,
    UpdateEventRequest,
)
from pecha_api.events.event_service import (
    _intention_dtos_for_event,
    create_event_service,
    update_event_service,
)
from pecha_api.prayer_intentions.prayer_intention_response_models import (
    PrayerIntentionDTO,
)

MODULE = "pecha_api.events.event_service"


@patch("pecha_api.events.event_service.count_event_prayer_intention_links")
@patch("pecha_api.events.event_service.list_prayer_intentions_for_event")
def test_intention_dtos_for_event_returns_empty_when_unrestricted(
    mock_list, mock_count
):
    event_id = uuid4()
    db = MagicMock()
    mock_count.return_value = 0

    assert _intention_dtos_for_event(db=db, event_id=event_id) == []
    mock_list.assert_not_called()


@patch("pecha_api.events.event_service.prayer_intention_to_dto")
@patch("pecha_api.events.event_service.count_event_prayer_intention_links")
@patch("pecha_api.events.event_service.list_prayer_intentions_for_event")
def test_intention_dtos_for_event_returns_linked_dtos(
    mock_list, mock_count, mock_to_dto
):
    event_id = uuid4()
    db = MagicMock()
    mock_count.return_value = 1
    row = MagicMock()
    mock_list.return_value = [row]
    expected = PrayerIntentionDTO(
        slug="healing",
        label="Healing",
        color="#4A78C2",
        description="Recovery",
        display_order=0,
    )
    mock_to_dto.return_value = expected

    result = _intention_dtos_for_event(db=db, event_id=event_id)

    assert result == [expected]
    mock_list.assert_called_once_with(db=db, event_id=event_id)


def test_create_event_links_intentions_before_commit():
    intention_id = uuid4()
    now = datetime.now(timezone.utc)
    request = CreateEventRequest(
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        metadata=[{"name": "Event", "language": "EN"}],
        intention_ids=[intention_id],
        notifications_enabled=False,
    )
    saved = MagicMock(id=uuid4(), notifications_enabled=False)
    db = MagicMock()

    def fake_save(db_session, event, metadata, links, youtube_entries=None, after_flush=None):
        event.id = saved.id
        after_flush(event)
        return saved

    with patch(f"{MODULE}.validate_cms_author_details", return_value=MagicMock()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal") as mock_session, patch(
        f"{MODULE}.save_event", side_effect=fake_save
    ), patch(f"{MODULE}.schedule_event_reminders"), patch(
        f"{MODULE}.sync_event_youtube_to_plan_day"
    ), patch(f"{MODULE}.replace_event_prayer_intentions") as mock_replace, patch(
        f"{MODULE}._intention_dtos_for_event", return_value=[]
    ), patch(f"{MODULE}._event_to_dto", return_value=MagicMock()):
        mock_session.return_value.__enter__.return_value = db
        create_event_service(token="token", request=request)

    mock_replace.assert_called_once_with(
        db=db, event_id=saved.id, intention_ids=[intention_id]
    )


def test_update_event_replaces_intentions_before_persisting_the_event():
    intention_id = uuid4()
    existing = MagicMock(id=uuid4(), chat_enabled=True, notifications_enabled=True)
    existing.timezone = "UTC"
    request = UpdateEventRequest(intention_ids=[intention_id])
    call_order = []

    def fake_replace(**_kwargs):
        call_order.append("replace")

    def fake_update(*_args, **_kwargs):
        call_order.append("update")
        return existing

    with patch(f"{MODULE}.validate_cms_author_details", return_value=MagicMock()), patch(
        f"{MODULE}.SessionLocal"
    ) as mock_session, patch(
        f"{MODULE}.get_event_by_id", return_value=existing
    ), patch(f"{MODULE}._require_can_edit_event"), patch(
        f"{MODULE}.youtube_video_keys_of_event", return_value=set()
    ), patch(
        f"{MODULE}._apply_recurrence_or_dates", return_value=False
    ), patch(f"{MODULE}._apply_simple_field_updates"), patch(
        f"{MODULE}._apply_relational_field_updates"
    ), patch(f"{MODULE}._sync_event_reminders"), patch(
        f"{MODULE}.replace_event_prayer_intentions", side_effect=fake_replace
    ), patch(f"{MODULE}.update_event", side_effect=fake_update), patch(
        f"{MODULE}._intention_dtos_for_event", return_value=[]
    ), patch(f"{MODULE}._chat_room_id_for_event", return_value=None), patch(
        f"{MODULE}._event_to_dto", return_value=MagicMock()
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        update_event_service(token="token", event_id=existing.id, request=request)

    assert call_order == ["replace", "update"]
