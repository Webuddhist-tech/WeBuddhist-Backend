from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events.event_service import (
    get_event_by_id_service,
    get_events_service,
    _event_to_dto,
)

MODULE = "pecha_api.events.event_service"


def _metadata(language, name):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description=None,
        language=language,
    )


def _link(language, type_="web"):
    return SimpleNamespace(
        id=uuid4(),
        type=type_,
        url="https://example.com",
        label=None,
        language=language,
        display_order=1,
    )


def _event(metadata_entries, links=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
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
        metadata_entries=metadata_entries,
        links=links or [],
        created_at=now,
        created_by="author@example.com",
        updated_at=None,
    )


# --------------------------- _event_to_dto fallback behaviour ---------------------------


def test_returns_selected_language_when_available():
    event = _event([_metadata("bo", "Tibetan"), _metadata("en", "English")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert dto.metadata is not None
    assert dto.metadata.language == "bo"
    assert dto.metadata.name == "Tibetan"


def test_falls_back_to_english_when_selected_language_missing():
    event = _event([_metadata("en", "English")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert dto.metadata is not None
    assert dto.metadata.language == "en"
    assert dto.metadata.name == "English"


def test_returns_null_metadata_when_neither_selected_nor_english_exists():
    event = _event([_metadata("fr", "French")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    # Event is still returned; only the metadata is empty.
    assert dto.metadata is None
    assert dto.id == event.id


def test_event_not_excluded_when_no_metadata_at_all():
    event = _event([])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert dto.metadata is None
    assert dto.id == event.id


def test_no_fallback_returns_null_when_selected_language_missing():
    # CMS / strict path (fallback=False): English is not substituted.
    event = _event([_metadata("en", "English")])

    dto = _event_to_dto(event, language="bo", fallback=False)

    assert dto.metadata is None


# --------------------------- public services thread fallback=True ---------------------------


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_events")
def test_get_events_service_public_uses_fallback(mock_get_events, _mock_counts, _mock_groups, mock_session):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event([_metadata("en", "English")])
    mock_get_events.return_value = ([event], 1)

    response = get_events_service(language="bo", fallback=True)

    assert response.total == 1
    assert response.events[0].metadata.language == "en"


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_counts", return_value={})
@patch(f"{MODULE}.get_events")
def test_get_events_service_cms_default_no_fallback(mock_get_events, _mock_counts, _mock_groups, mock_session):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event([_metadata("en", "English")])
    mock_get_events.return_value = ([event], 1)

    # Default fallback=False (the CMS path leaves it unset).
    response = get_events_service(language="bo")

    assert response.total == 1
    assert response.events[0].metadata is None


@patch(f"{MODULE}.SessionLocal")
@patch(f"{MODULE}.get_groups_by_ids", return_value=[])
@patch(f"{MODULE}.get_event_participant_count", return_value=0)
@patch(f"{MODULE}.get_event_by_id")
def test_get_event_by_id_service_uses_fallback(mock_get_by_id, _mock_count, _mock_groups, mock_session):
    mock_session.return_value.__enter__.return_value = MagicMock()
    event = _event([_metadata("en", "English")])
    mock_get_by_id.return_value = event

    dto = get_event_by_id_service(event_id=event.id, language="bo")

    assert dto.metadata is not None
    assert dto.metadata.language == "en"
    assert dto.is_joined is None


# --------------------------- _event_to_dto links/youtube fallback behaviour ---------------------------
# Mirrors the metadata fallback tests above, except links/youtube never
# collapse to a single object - a "no match" result is an empty list, not None.


def test_links_returns_selected_language_when_available():
    event = _event([], links=[_link("bo"), _link("en")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert [link.language for link in dto.links] == ["bo"]


def test_links_falls_back_to_english_when_selected_language_missing():
    event = _event([], links=[_link("en")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert [link.language for link in dto.links] == ["en"]


def test_links_returns_empty_list_when_neither_selected_nor_english_exists():
    event = _event([], links=[_link("fr")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert dto.links == []


def test_youtube_returns_selected_language_when_available():
    event = _event([], links=[_link("bo", "youtube"), _link("en", "youtube")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert [item.language for item in dto.youtube] == ["bo"]


def test_youtube_falls_back_to_english_when_selected_language_missing():
    event = _event([], links=[_link("en", "youtube")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert [item.language for item in dto.youtube] == ["en"]


def test_youtube_returns_empty_list_when_neither_selected_nor_english_exists():
    event = _event([], links=[_link("fr", "youtube")])

    dto = _event_to_dto(event, language="bo", fallback=True)

    assert dto.youtube == []
