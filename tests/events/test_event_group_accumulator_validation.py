"""Group accumulator links on events must belong to the event's group."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.events.event_response_models import CreateEventRequest, EventMetadataInput
from pecha_api.events.event_service import create_event_service, update_event_service
from pecha_api.events.event_response_models import UpdateEventRequest

MODULE = "pecha_api.events.event_service"


def _metadata() -> list[EventMetadataInput]:
    return [EventMetadataInput(name="Retreat", description="Desc", language="EN")]


def _create_request(**overrides) -> CreateEventRequest:
    group_id = overrides.pop("group_id", uuid4())
    now = datetime.now(timezone.utc)
    defaults = {
        "group_id": group_id,
        "start_date": now,
        "end_date": now,
        "metadata": _metadata(),
    }
    defaults.update(overrides)
    return CreateEventRequest(**defaults)


@patch(f"{MODULE}.enqueue_event_notification")
@patch(f"{MODULE}.save_event")
@patch(f"{MODULE}.require_can_create_content")
@patch(f"{MODULE}.validate_cms_author_details")
@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_group_accumulator_by_id")
def test_create_event_rejects_cross_group_group_accumulator(
    mock_get_accumulator,
    mock_session,
    mock_validate_author,
    mock_require_create,
    mock_save_event,
    mock_enqueue,
) -> None:
    event_group = uuid4()
    other_group = uuid4()
    accumulator_id = uuid4()
    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    mock_validate_author.return_value = MagicMock(email="a@b.com")
    mock_get_accumulator.return_value = MagicMock(group_id=other_group)

    with pytest.raises(HTTPException) as exc:
        create_event_service(
            token="token",
            request=_create_request(
                group_id=event_group,
                group_accumulator_id=accumulator_id,
            ),
        )

    assert exc.value.status_code == 400
    assert "does not belong" in exc.value.detail
    mock_save_event.assert_not_called()


@patch(f"{MODULE}.update_event")
@patch(f"{MODULE}.get_event_by_id")
@patch(f"{MODULE}._require_can_edit_event")
@patch(f"{MODULE}.validate_cms_author_details")
@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_group_accumulator_by_id")
def test_update_event_rejects_cross_group_group_accumulator(
    mock_get_accumulator,
    mock_session,
    mock_validate_author,
    mock_require_edit,
    mock_get_event,
    mock_update_event,
) -> None:
    event_group = uuid4()
    other_group = uuid4()
    accumulator_id = uuid4()
    event_id = uuid4()
    event = MagicMock()
    event.group_id = event_group
    event.group_accumulator_id = None
    event.timezone = "UTC"
    event.notifications_enabled = True
    event.chat_enabled = True

    mock_db = MagicMock()
    mock_session.return_value.__enter__.return_value = mock_db
    mock_validate_author.return_value = MagicMock(email="a@b.com")
    mock_get_event.return_value = event
    mock_get_accumulator.return_value = MagicMock(group_id=other_group)
    mock_update_event.side_effect = lambda db, ev, **kwargs: ev

    with pytest.raises(HTTPException) as exc:
        update_event_service(
            token="token",
            event_id=event_id,
            request=UpdateEventRequest(group_accumulator_id=accumulator_id),
        )

    assert exc.value.status_code == 400
    assert "does not belong" in exc.value.detail
    mock_update_event.assert_not_called()
