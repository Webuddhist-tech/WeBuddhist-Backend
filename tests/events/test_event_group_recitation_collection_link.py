from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from starlette import status
from fastapi import HTTPException

from pecha_api.app import api  # noqa: F401
from pecha_api.events.event_response_models import (
    CreateEventRequest,
    UpdateEventRequest,
)
from pecha_api.events.event_service import (
    create_event_service,
    update_event_service,
    get_events_service,
    EventContentFilter,
)


def _saved_event_stub(group_id=None, collection_id=None) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        plan_id=None,
        accumulator_id=None,
        mantra_id=None,
        timer_id=None,
        group_recitation_collection_id=collection_id,
        group_id=group_id or uuid4(),
        location_id=None,
        location=None,
        start_date=now,
        end_date=now,
        timezone=None,
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


def _author() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), email="author@example.com")


def test_create_event_with_valid_same_group_collection_persists() -> None:
    group_id = uuid4()
    collection_id = uuid4()
    now = datetime.now(timezone.utc)
    request = CreateEventRequest(
        group_id=group_id,
        start_date=now,
        end_date=now,
        metadata=[{"name": "Event", "language": "EN"}],
        group_recitation_collection_id=collection_id,
    )

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=_author(),
    ), patch(
        "pecha_api.events.event_service.require_can_create_content",
    ), patch(
        "pecha_api.events.event_service.get_collection_by_id",
        return_value=SimpleNamespace(id=collection_id, group_id=group_id),
    ) as mock_get_collection, patch(
        "pecha_api.events.event_service.save_event",
        return_value=_saved_event_stub(group_id=group_id, collection_id=collection_id),
    ) as mock_save:
        result = create_event_service(token="token", request=request)

    _, _, kwargs = mock_get_collection.mock_calls[0]
    assert kwargs["collection_id"] == collection_id
    assert kwargs["group_id"] == group_id
    saved_event = mock_save.mock_calls[0].args[1]
    assert saved_event.group_recitation_collection_id == collection_id
    assert result.group_recitation_collection_id == collection_id


def test_create_event_with_other_group_collection_rejected() -> None:
    group_id = uuid4()
    collection_id = uuid4()
    now = datetime.now(timezone.utc)
    request = CreateEventRequest(
        group_id=group_id,
        start_date=now,
        end_date=now,
        metadata=[{"name": "Event", "language": "EN"}],
        group_recitation_collection_id=collection_id,
    )

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=_author(),
    ), patch(
        "pecha_api.events.event_service.require_can_create_content",
    ), patch(
        "pecha_api.events.event_service.get_collection_by_id",
        return_value=None,
    ), patch(
        "pecha_api.events.event_service.save_event",
    ) as mock_save:
        with pytest.raises(HTTPException) as exc:
            create_event_service(token="token", request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_save.assert_not_called()


def test_create_event_without_collection_skips_validation() -> None:
    now = datetime.now(timezone.utc)
    request = CreateEventRequest(
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        metadata=[{"name": "Event", "language": "EN"}],
    )

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=_author(),
    ), patch(
        "pecha_api.events.event_service.require_can_create_content",
    ), patch(
        "pecha_api.events.event_service.get_collection_by_id",
    ) as mock_get_collection, patch(
        "pecha_api.events.event_service.save_event",
        return_value=_saved_event_stub(),
    ):
        create_event_service(token="token", request=request)

    mock_get_collection.assert_not_called()


def test_update_event_sets_collection_when_valid() -> None:
    group_id = uuid4()
    collection_id = uuid4()
    existing = _saved_event_stub(group_id=group_id)
    request = UpdateEventRequest(group_recitation_collection_id=collection_id)

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=_author(),
    ), patch(
        "pecha_api.events.event_service.get_event_by_id",
        return_value=existing,
    ), patch(
        "pecha_api.events.event_service._require_can_edit_event",
    ), patch(
        "pecha_api.events.event_service.get_collection_by_id",
        return_value=SimpleNamespace(id=collection_id, group_id=group_id),
    ), patch(
        "pecha_api.events.event_service.update_event",
        return_value=existing,
    ):
        update_event_service(token="token", event_id=existing.id, request=request)

    assert existing.group_recitation_collection_id == collection_id


def test_update_event_clears_collection_with_explicit_null() -> None:
    group_id = uuid4()
    existing = _saved_event_stub(group_id=group_id, collection_id=uuid4())
    request = UpdateEventRequest.model_validate({"group_recitation_collection_id": None})

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=_author(),
    ), patch(
        "pecha_api.events.event_service.get_event_by_id",
        return_value=existing,
    ), patch(
        "pecha_api.events.event_service._require_can_edit_event",
    ), patch(
        "pecha_api.events.event_service.get_collection_by_id",
    ) as mock_get_collection, patch(
        "pecha_api.events.event_service.update_event",
        return_value=existing,
    ):
        update_event_service(token="token", event_id=existing.id, request=request)

    assert existing.group_recitation_collection_id is None
    mock_get_collection.assert_not_called()


def test_update_event_omitting_collection_leaves_link_untouched() -> None:
    group_id = uuid4()
    original_collection = uuid4()
    existing = _saved_event_stub(group_id=group_id, collection_id=original_collection)
    request = UpdateEventRequest(start_date=None)

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=_author(),
    ), patch(
        "pecha_api.events.event_service.get_event_by_id",
        return_value=existing,
    ), patch(
        "pecha_api.events.event_service._require_can_edit_event",
    ), patch(
        "pecha_api.events.event_service.get_collection_by_id",
    ) as mock_get_collection, patch(
        "pecha_api.events.event_service.update_event",
        return_value=existing,
    ):
        update_event_service(token="token", event_id=existing.id, request=request)

    assert existing.group_recitation_collection_id == original_collection
    mock_get_collection.assert_not_called()


def test_update_event_with_other_group_collection_rejected() -> None:
    group_id = uuid4()
    collection_id = uuid4()
    existing = _saved_event_stub(group_id=group_id)
    request = UpdateEventRequest(group_recitation_collection_id=collection_id)

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=_author(),
    ), patch(
        "pecha_api.events.event_service.get_event_by_id",
        return_value=existing,
    ), patch(
        "pecha_api.events.event_service._require_can_edit_event",
    ), patch(
        "pecha_api.events.event_service.get_collection_by_id",
        return_value=None,
    ), patch(
        "pecha_api.events.event_service.update_event",
    ) as mock_update:
        with pytest.raises(HTTPException) as exc:
            update_event_service(token="token", event_id=existing.id, request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_update.assert_not_called()


def test_get_events_service_forwards_collection_filter_to_repository() -> None:
    collection_id = uuid4()
    mock_db = MagicMock()
    with patch(
        "pecha_api.events.event_service.SessionLocal",
        return_value=mock_db,
    ), patch(
        "pecha_api.events.event_service.get_events",
        return_value=([], 0),
    ) as mock_get_events, patch(
        "pecha_api.events.event_service.get_recurring_events",
        return_value=[],
    ):
        get_events_service(
            content_filter=EventContentFilter(group_recitation_collection_id=collection_id)
        )

    _, _, kwargs = mock_get_events.mock_calls[0]
    assert kwargs["content_filter"].group_recitation_collection_id == collection_id
