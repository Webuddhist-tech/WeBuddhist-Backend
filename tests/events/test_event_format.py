from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pecha_api.events.event_filters import EventContentFilter
from pecha_api.events.event_model import Event
from pecha_api.events.event_repository import _apply_event_filters
from pecha_api.events.event_response_models import (
    CreateEventRequest,
    UpdateEventRequest,
    EventDTO,
)


def test_create_event_request_accepts_valid_event_formats() -> None:
    """Test that CreateEventRequest accepts valid event_format values."""
    now = datetime.now(timezone.utc)
    
    for format_value in ["online", "offline", "hybrid"]:
        request = CreateEventRequest(
            group_id=uuid4(),
            start_date=now,
            end_date=now,
            metadata=[{"name": "Event", "language": "EN"}],
            event_format=format_value,
        )
        assert request.event_format == format_value


def test_create_event_request_rejects_invalid_event_format() -> None:
    """Test that CreateEventRequest rejects invalid event_format values."""
    now = datetime.now(timezone.utc)
    
    with pytest.raises(ValidationError) as exc_info:
        CreateEventRequest(
            group_id=uuid4(),
            start_date=now,
            end_date=now,
            metadata=[{"name": "Event", "language": "EN"}],
            event_format="invalid_format",
        )
    
    assert "event_format" in str(exc_info.value)


def test_create_event_request_event_format_defaults_to_hybrid() -> None:
    """Test that event_format defaults to hybrid when omitted in CreateEventRequest."""
    now = datetime.now(timezone.utc)

    request = CreateEventRequest(
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        metadata=[{"name": "Event", "language": "EN"}],
    )
    assert request.event_format == "hybrid"


def test_create_event_request_rejects_null_event_format() -> None:
    """Test that CreateEventRequest rejects an explicit null event_format."""
    now = datetime.now(timezone.utc)

    with pytest.raises(ValidationError) as exc_info:
        CreateEventRequest(
            group_id=uuid4(),
            start_date=now,
            end_date=now,
            metadata=[{"name": "Event", "language": "EN"}],
            event_format=None,
        )

    assert "event_format" in str(exc_info.value)


def test_update_event_request_accepts_valid_event_formats() -> None:
    """Test that UpdateEventRequest accepts valid event_format values."""
    for format_value in ["online", "offline", "hybrid"]:
        request = UpdateEventRequest(event_format=format_value)
        assert request.event_format == format_value


def test_update_event_request_rejects_invalid_event_format() -> None:
    """Test that UpdateEventRequest rejects invalid event_format values."""
    with pytest.raises(ValidationError) as exc_info:
        UpdateEventRequest(event_format="in-person")
    
    assert "event_format" in str(exc_info.value)


def test_update_event_request_event_format_is_optional() -> None:
    """Test that omitting event_format in UpdateEventRequest leaves it untouched."""
    request = UpdateEventRequest()
    assert request.event_format is None
    assert "event_format" not in request.model_fields_set


def test_update_event_request_rejects_null_event_format() -> None:
    """Test that UpdateEventRequest rejects an explicit null event_format."""
    with pytest.raises(ValidationError) as exc_info:
        UpdateEventRequest(event_format=None)

    assert "event_format" in str(exc_info.value)


def test_event_dto_includes_event_format() -> None:
    """Test that EventDTO includes event_format field."""
    now = datetime.now(timezone.utc)
    
    event = EventDTO(
        id=uuid4(),
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        is_one_day=True,
        featured=False,
        event_format="online",
        metadata=[],
        created_at=now,
        created_by="author@example.com",
    )
    
    assert event.event_format == "online"


def test_event_dto_event_format_defaults_to_hybrid() -> None:
    """Test that EventDTO event_format defaults to hybrid when omitted."""
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

    assert event.event_format == "hybrid"


def test_event_dto_rejects_null_event_format() -> None:
    """Test that EventDTO rejects an explicit null event_format."""
    now = datetime.now(timezone.utc)

    with pytest.raises(ValidationError):
        EventDTO(
            id=uuid4(),
            group_id=uuid4(),
            start_date=now,
            end_date=now,
            is_one_day=True,
            featured=False,
            event_format=None,
            metadata=[],
            created_at=now,
            created_by="author@example.com",
        )


def test_create_event_service_sets_event_format() -> None:
    """Test that create_event_service properly sets event_format."""
    now = datetime.now(timezone.utc)
    group_id = uuid4()
    
    request = CreateEventRequest(
        group_id=group_id,
        start_date=now,
        end_date=now,
        metadata=[{"name": "Test Event", "language": "EN"}],
        event_format="hybrid",
    )
    
    mock_event = MagicMock()
    mock_event.id = uuid4()
    mock_event.group_id = group_id
    mock_event.start_date = now
    mock_event.end_date = now
    mock_event.event_format = "hybrid"
    mock_event.timezone = None
    mock_event.featured = False
    mock_event.is_recurring = False
    mock_event.metadata_entries = []
    mock_event.links = []
    mock_event.created_at = now
    mock_event.created_by = "test@example.com"
    mock_event.updated_at = None
    mock_event.image_url = None
    mock_event.plan_id = None
    mock_event.series_id = None
    mock_event.accumulator_id = None
    mock_event.group_accumulator_id = None
    mock_event.mantra_id = None
    mock_event.timer_id = None
    mock_event.group_recitation_collection_id = None
    mock_event.location_id = None
    mock_event.location = None
    mock_event.plan = None
    mock_event.series = None
    mock_event.accumulator = None
    mock_event.group_accumulator = None
    mock_event.mantra = None
    mock_event.timer = None
    mock_event.group_recitation_collection = None

    with patch("pecha_api.events.event_service.validate_cms_author_details") as mock_auth, \
         patch("pecha_api.events.event_service.SessionLocal") as mock_session, \
         patch("pecha_api.events.event_service.save_event", return_value=mock_event) as mock_save, \
         patch("pecha_api.events.event_service.require_can_create_content"), \
         patch("pecha_api.events.event_service.enqueue_event_notification"):
        
        mock_auth.return_value = MagicMock(email="test@example.com")
        mock_session.return_value.__enter__.return_value = MagicMock()
        
        from pecha_api.events.event_service import create_event_service
        result = create_event_service(token="test-token", request=request)
        
        # Verify Event object was created with event_format
        call_args = mock_save.call_args
        event_arg = call_args[0][1]  # Second positional arg is the Event object
        assert event_arg.event_format == "hybrid"
        
        # Verify the returned DTO includes event_format
        assert result.event_format == "hybrid"


def test_update_event_service_updates_event_format() -> None:
    """Test that update_event_service properly updates event_format."""
    now = datetime.now(timezone.utc)
    event_id = uuid4()
    
    request = UpdateEventRequest(event_format="offline")
    
    mock_event = MagicMock()
    mock_event.id = event_id
    mock_event.group_id = uuid4()
    mock_event.start_date = now
    mock_event.end_date = now
    mock_event.event_format = "online"  # Original value
    mock_event.timezone = None
    mock_event.featured = False
    mock_event.is_recurring = False
    mock_event.metadata_entries = []
    mock_event.links = []
    mock_event.created_at = now
    mock_event.created_by = "test@example.com"
    mock_event.updated_at = None
    mock_event.image_url = None
    mock_event.location = None
    mock_event.plan_id = None
    mock_event.series_id = None
    mock_event.accumulator_id = None
    mock_event.group_accumulator_id = None
    mock_event.mantra_id = None
    mock_event.timer_id = None
    mock_event.group_recitation_collection_id = None
    mock_event.location_id = None
    mock_event.plan = None
    mock_event.series = None
    mock_event.accumulator = None
    mock_event.group_accumulator = None
    mock_event.mantra = None
    mock_event.timer = None
    mock_event.group_recitation_collection = None

    with patch("pecha_api.events.event_service.validate_cms_author_details") as mock_auth, \
         patch("pecha_api.events.event_service.SessionLocal") as mock_session, \
         patch("pecha_api.events.event_service.get_event_by_id", return_value=mock_event), \
         patch("pecha_api.events.event_service.update_event", return_value=mock_event) as mock_update, \
         patch("pecha_api.events.event_service._require_can_edit_event"):
        
        mock_auth.return_value = MagicMock(email="test@example.com")
        mock_session.return_value.__enter__.return_value = MagicMock()
        
        from pecha_api.events.event_service import update_event_service
        result = update_event_service(token="test-token", event_id=event_id, request=request)
        
        # Verify event_format was updated
        assert mock_event.event_format == "offline"
        
        # Verify the returned DTO includes updated event_format
        assert result.event_format == "offline"


def _event_format_session() -> tuple[Session, type[Event], Callable[..., Any]]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Event.metadata.create_all(bind=engine, tables=[Event.__table__])
    db = sessionmaker(bind=engine)()
    now = datetime.now(timezone.utc)
    for event_format in ("online", "offline", "hybrid"):
        db.add(
            Event(
                id=uuid4(),
                group_id=uuid4(),
                start_date=now,
                end_date=now,
                created_by="test@example.com",
                event_format=event_format,
                featured=False,
                is_recurring=False,
            )
        )
    db.commit()
    return db, Event, _apply_event_filters


def _formats_for(event_format: str | None) -> set[str]:
    db, event_cls, apply_filters = _event_format_session()
    query = apply_filters(
        db.query(event_cls),
        content_filter=EventContentFilter(event_format=event_format),
    )
    return {event.event_format for event in query.all()}


def test_apply_event_filters_online_includes_hybrid() -> None:
    assert _formats_for("online") == {"online", "hybrid"}


def test_apply_event_filters_offline_includes_hybrid() -> None:
    assert _formats_for("offline") == {"offline", "hybrid"}


def test_apply_event_filters_hybrid_is_exact() -> None:
    assert _formats_for("hybrid") == {"hybrid"}


def test_apply_event_filters_omits_format_clause_when_unset() -> None:
    assert _formats_for(None) == {"online", "offline", "hybrid"}

