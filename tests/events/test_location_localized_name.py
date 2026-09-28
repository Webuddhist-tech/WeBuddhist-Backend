"""The location name a reader gets for the language they asked for."""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional
from uuid import uuid4

from pecha_api.events.event_service import _event_to_dto, _location_to_dto


def _location_metadata(language: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name=name, language=language)


def _location(
    name: str = "Bodh Gaya",
    metadata_entries: Optional[List[SimpleNamespace]] = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        group_id=uuid4(),
        name=name,
        latitude=None,
        longitude=None,
        metadata_entries=metadata_entries if metadata_entries is not None else [],
    )


def _event(location: Optional[SimpleNamespace]) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        plan_id=None,
        accumulator_id=None,
        mantra_id=None,
        timer_id=None,
        group_recitation_collection_id=None,
        group_id=uuid4(),
        location_id=location.id if location else None,
        location=location,
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


def test_returns_requested_language_name() -> None:
    location = _location(
        metadata_entries=[
            _location_metadata("EN", "Bodh Gaya"),
            _location_metadata("BO", "རྡོ་རྗེ་གདན།"),
        ]
    )

    dto = _location_to_dto(_event(location), language="bo")

    assert dto.name == "རྡོ་རྗེ་གདན།"


def test_falls_back_to_english_when_requested_language_missing() -> None:
    location = _location(
        metadata_entries=[
            _location_metadata("EN", "Bodh Gaya"),
            _location_metadata("BO", "རྡོ་རྗེ་གདན།"),
        ]
    )

    dto = _location_to_dto(_event(location), language="zh")

    assert dto.name == "Bodh Gaya"


def test_falls_back_to_canonical_name_when_neither_exists() -> None:
    location = _location(
        name="Tushita", metadata_entries=[_location_metadata("BO", "བདེ་ཆེན།")]
    )

    dto = _location_to_dto(_event(location), language="zh")

    assert dto.name == "Tushita"


def test_location_without_translations_keeps_its_own_name() -> None:
    location = _location(name="Online")

    dto = _location_to_dto(_event(location), language="bo")

    assert dto.name == "Online"


def test_no_language_asked_for_returns_canonical_name() -> None:
    location = _location(
        name="Bodh Gaya", metadata_entries=[_location_metadata("BO", "རྡོ་རྗེ་གདན།")]
    )

    dto = _location_to_dto(_event(location))

    assert dto.name == "Bodh Gaya"


def test_event_without_location_has_none() -> None:
    assert _location_to_dto(_event(None), language="bo") is None


def test_event_dto_carries_the_localized_location_name() -> None:
    location = _location(
        metadata_entries=[
            _location_metadata("EN", "Bodh Gaya"),
            _location_metadata("BO", "རྡོ་རྗེ་གདན།"),
        ]
    )

    dto = _event_to_dto(_event(location), language="bo", fallback=True)

    assert dto.location is not None
    assert dto.location.name == "རྡོ་རྗེ་གདན།"
    assert dto.location_id == location.id
