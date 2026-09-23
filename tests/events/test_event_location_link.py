import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette import status

from pecha_api.app import api  # noqa: F401
from pecha_api.events.event_response_models import (
    CreateEventRequest,
    UpdateEventRequest,
)
from pecha_api.events.event_service import (
    create_event_service,
    get_featured_events_service,
    update_event_service,
)

MODULE = "pecha_api.events.event_service"


def _location_stub(group_id=None, name="Tushita Meditation Centre"):
    return SimpleNamespace(
        id=uuid4(),
        group_id=group_id or uuid4(),
        name=name,
        latitude=Decimal("32.242305"),
        longitude=Decimal("76.321284"),
    )


def _saved_event_stub(group_id=None, location=None) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        plan_id=None,
        accumulator_id=None,
        mantra_id=None,
        timer_id=None,
        group_recitation_collection_id=None,
        group_id=group_id or uuid4(),
        location_id=location.id if location else None,
        location=location,
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


def _create_request(group_id, location_id=None) -> CreateEventRequest:
    now = datetime.now(timezone.utc)
    payload = {
        "group_id": group_id,
        "start_date": now,
        "end_date": now,
        "metadata": [{"name": "Event", "language": "EN"}],
    }
    if location_id is not None:
        payload["location_id"] = location_id
    return CreateEventRequest(**payload)


# --------------------------- create ---------------------------


def test_create_event_with_same_group_location_persists() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)
    request = _create_request(group_id, location_id=location.id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_without_group_filter", return_value=location
    ), patch(
        f"{MODULE}.save_event",
        return_value=_saved_event_stub(group_id=group_id, location=location),
    ) as mock_save:
        result = create_event_service(token="token", request=request)

    persisted = mock_save.mock_calls[0].args[1]
    assert persisted.location_id == location.id
    assert result.location_id == location.id
    assert result.location.name == "Tushita Meditation Centre"


def test_create_event_with_cross_group_location_rejected() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=uuid4())
    request = _create_request(group_id, location_id=location.id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_without_group_filter", return_value=location
    ), patch(
        f"{MODULE}.save_event"
    ) as mock_save:
        with pytest.raises(HTTPException) as exc:
            create_event_service(token="token", request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.value.detail["error"] == "LOCATION_GROUP_MISMATCH"
    mock_save.assert_not_called()


def test_create_event_with_unknown_location_returns_404() -> None:
    group_id = uuid4()
    request = _create_request(group_id, location_id=uuid4())

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_without_group_filter", return_value=None
    ), patch(
        f"{MODULE}.save_event"
    ) as mock_save:
        with pytest.raises(HTTPException) as exc:
            create_event_service(token="token", request=request)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_save.assert_not_called()


def test_create_event_without_location_skips_validation() -> None:
    group_id = uuid4()
    request = _create_request(group_id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_without_group_filter"
    ) as mock_lookup, patch(
        f"{MODULE}.save_event", return_value=_saved_event_stub(group_id=group_id)
    ):
        result = create_event_service(token="token", request=request)

    mock_lookup.assert_not_called()
    assert result.location_id is None
    assert result.location is None


# --------------------------- update: omit vs null ---------------------------


def test_update_event_omitting_location_leaves_it_untouched() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)
    existing = _saved_event_stub(group_id=group_id, location=location)
    request = UpdateEventRequest()

    assert "location_id" not in request.model_fields_set

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}._require_can_edit_event"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_event_by_id", return_value=existing
    ), patch(
        f"{MODULE}.get_location_without_group_filter"
    ) as mock_lookup, patch(
        f"{MODULE}.update_event", side_effect=lambda db, event, **kwargs: event
    ):
        update_event_service(token="token", event_id=existing.id, request=request)

    mock_lookup.assert_not_called()
    assert existing.location_id == location.id


def test_update_event_clears_location_with_explicit_null() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)
    existing = _saved_event_stub(group_id=group_id, location=location)
    request = UpdateEventRequest(**{"location_id": None})

    assert "location_id" in request.model_fields_set

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}._require_can_edit_event"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_event_by_id", return_value=existing
    ), patch(
        f"{MODULE}.update_event", side_effect=lambda db, event, **kwargs: event
    ):
        update_event_service(token="token", event_id=existing.id, request=request)

    assert existing.location_id is None


def test_update_event_sets_location_when_same_group() -> None:
    group_id = uuid4()
    existing = _saved_event_stub(group_id=group_id)
    location = _location_stub(group_id=group_id)
    request = UpdateEventRequest(location_id=location.id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}._require_can_edit_event"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_event_by_id", return_value=existing
    ), patch(
        f"{MODULE}.get_location_without_group_filter", return_value=location
    ), patch(
        f"{MODULE}.update_event", side_effect=lambda db, event, **kwargs: event
    ):
        update_event_service(token="token", event_id=existing.id, request=request)

    assert existing.location_id == location.id


def test_update_event_with_cross_group_location_rejected() -> None:
    group_id = uuid4()
    existing = _saved_event_stub(group_id=group_id)
    location = _location_stub(group_id=uuid4())
    request = UpdateEventRequest(location_id=location.id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}._require_can_edit_event"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_event_by_id", return_value=existing
    ), patch(
        f"{MODULE}.get_location_without_group_filter", return_value=location
    ), patch(
        f"{MODULE}.update_event"
    ) as mock_update:
        with pytest.raises(HTTPException) as exc:
            update_event_service(token="token", event_id=existing.id, request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.value.detail["error"] == "LOCATION_GROUP_MISMATCH"
    mock_update.assert_not_called()


def test_update_event_with_unknown_location_returns_404() -> None:
    group_id = uuid4()
    existing = _saved_event_stub(group_id=group_id)
    request = UpdateEventRequest(location_id=uuid4())

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}._require_can_edit_event"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_event_by_id", return_value=existing
    ), patch(
        f"{MODULE}.get_location_without_group_filter", return_value=None
    ), patch(
        f"{MODULE}.update_event"
    ) as mock_update:
        with pytest.raises(HTTPException) as exc:
            update_event_service(token="token", event_id=existing.id, request=request)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_update.assert_not_called()


def test_update_event_rejects_empty_string_location_id() -> None:
    """Studio has two conventions for clearing a field; an empty string must be
    rejected loudly rather than silently treated as a clear."""
    with pytest.raises(ValidationError):
        UpdateEventRequest(**{"location_id": ""})


# --------------------------- response shape ---------------------------


def test_event_dto_serializes_coordinates_as_json_numbers() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)
    request = _create_request(group_id, location_id=location.id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_without_group_filter", return_value=location
    ), patch(
        f"{MODULE}.save_event",
        return_value=_saved_event_stub(group_id=group_id, location=location),
    ):
        result = create_event_service(token="token", request=request)

    payload = json.loads(result.model_dump_json(exclude_none=True))["location"]
    assert isinstance(payload["latitude"], float)
    assert isinstance(payload["longitude"], float)
    assert payload["latitude"] == 32.242305


def test_event_dto_omits_location_when_absent() -> None:
    group_id = uuid4()
    request = _create_request(group_id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.save_event", return_value=_saved_event_stub(group_id=group_id)
    ):
        result = create_event_service(token="token", request=request)

    payload = json.loads(result.model_dump_json(exclude_none=True))
    assert "location" not in payload
    assert "location_id" not in payload


def test_featured_events_include_nested_location() -> None:
    """Guards the eager-load on get_featured_events, the read path most easily
    missed when adding a relationship."""
    group_id = uuid4()
    location = _location_stub(group_id=group_id)
    event = _saved_event_stub(group_id=group_id, location=location)
    event.featured = True

    with patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_featured_events", return_value=[event]
    ):
        results = get_featured_events_service(language="en", limit=10)

    assert results[0].location_id == location.id
    assert results[0].location.name == "Tushita Meditation Centre"
