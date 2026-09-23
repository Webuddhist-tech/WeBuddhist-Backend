from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette import status

from pecha_api.app import api
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.events.event_model import Event
from pecha_api.events.event_link_model import EventLink
from pecha_api.events.event_response_models import (
    EventDTO,
    EventLinkInput,
    EventYoutubeInput,
    CreateEventRequest,
    UpdateEventRequest,
)
from pecha_api.events.event_service import (
    _links_to_dtos,
    _youtube_to_dtos,
    create_event_service,
    update_event_service,
)
from pecha_api.events import event_repository as event_repository_module
from pecha_api.events.event_repository import update_event

client = TestClient(api)


# --------------------------- EventLinkInput validation ---------------------------

def test_event_link_input_accepts_valid_http_and_https() -> None:
    http_link = EventLinkInput(type="web", url="http://example.com/info", language="EN")
    https_link = EventLinkInput(type="google-meet", url="https://meet.google.com/abc", language="EN")
    assert http_link.url == "http://example.com/info"
    assert https_link.display_order == 1  # default


def test_event_link_input_trims_url() -> None:
    link = EventLinkInput(type="web", url="  https://example.com  ", language="EN")
    assert link.url == "https://example.com"


@pytest.mark.parametrize(
    "bad_url",
    ["ftp://example.com", "notaurl", "javascript:alert(1)", "http://", "https://", "mailto:a@b.com"],
)
def test_event_link_input_rejects_non_http_url(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        EventLinkInput(type="web", url=bad_url, language="EN")


@pytest.mark.parametrize("bad_type", ["", "   ", "not-a-type"])
def test_event_link_input_rejects_unknown_type(bad_type: str) -> None:
    with pytest.raises(ValidationError):
        EventLinkInput(type=bad_type, url="https://example.com", language="EN")


def test_event_link_input_rejects_oversized_fields() -> None:
    # url > 2000, label > 255 must be rejected at validation, not at the DB
    with pytest.raises(ValidationError):
        EventLinkInput(type="web", url="https://example.com/" + "a" * 2000, language="EN")
    with pytest.raises(ValidationError):
        EventLinkInput(type="web", url="https://example.com", label="y" * 256, language="EN")


def test_event_link_input_requires_language() -> None:
    with pytest.raises(ValidationError):
        EventLinkInput(type="web", url="https://example.com")


def test_event_link_input_rejects_youtube_type() -> None:
    with pytest.raises(ValidationError, match="youtube"):
        EventLinkInput(type="youtube", url="https://example.com", language="EN")


@pytest.mark.parametrize("bad_case", ["YouTube", "YOUTUBE", "YouTUBE"])
def test_event_link_input_rejects_youtube_type_case_variants(bad_case: str) -> None:
    # Rejected via enum-membership validation (case-sensitive), not the custom
    # youtube-specific message - either way it must not be accepted.
    with pytest.raises(ValidationError):
        EventLinkInput(type=bad_case, url="https://example.com", language="EN")


# --------------------------- EventYoutubeInput validation ---------------------------

@pytest.mark.parametrize(
    "good_url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_event_youtube_input_accepts_youtube_urls(good_url: str) -> None:
    entry = EventYoutubeInput(url=good_url, language="EN")
    assert entry.url == good_url


@pytest.mark.parametrize(
    "bad_url",
    ["https://vimeo.com/12345", "https://example.com", "https://youtubemusic.com/x"],
)
def test_event_youtube_input_rejects_non_youtube_url(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        EventYoutubeInput(url=bad_url, language="EN")


def test_event_youtube_input_requires_language() -> None:
    with pytest.raises(ValidationError):
        EventYoutubeInput(url="https://youtu.be/dQw4w9WgXcQ")


def test_event_youtube_input_has_no_type_field() -> None:
    entry = EventYoutubeInput(url="https://youtu.be/dQw4w9WgXcQ", language="EN")
    assert not hasattr(entry, "type")


# --------------------------- request defaults ---------------------------

def test_create_event_request_defaults_links_and_youtube_to_empty_list() -> None:
    now = datetime.now(timezone.utc)
    request = CreateEventRequest(
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        metadata=[{"name": "Event", "language": "EN"}],
    )
    assert request.links == []
    assert request.youtube == []


def test_create_event_request_accepts_empty_links_and_youtube_explicitly() -> None:
    now = datetime.now(timezone.utc)
    request = CreateEventRequest(
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        metadata=[{"name": "Event", "language": "EN"}],
        links=[],
        youtube=[],
    )
    assert request.links == []
    assert request.youtube == []


def test_update_event_request_defaults_links_and_youtube_to_none() -> None:
    request = UpdateEventRequest()
    assert request.links is None
    assert request.youtube is None


# --------------------------- _links_to_dtos / _youtube_to_dtos ---------------------------

def _link(display_order: int, type_: str = "web", language: str = "EN") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        type=type_,
        url="https://example.com",
        label=None,
        language=language,
        display_order=display_order,
    )


def test_links_to_dtos_orders_by_display_order() -> None:
    links = [_link(3), _link(1), _link(2)]
    dtos = _links_to_dtos(links)
    assert [dto.display_order for dto in dtos] == [1, 2, 3]


def test_links_to_dtos_empty_returns_empty_list() -> None:
    assert _links_to_dtos([]) == []
    assert _links_to_dtos(None) == []


def test_links_to_dtos_excludes_youtube_entries() -> None:
    mixed = [_link(1, "web"), _link(2, "youtube")]
    dtos = _links_to_dtos(mixed)
    assert [dto.type for dto in dtos] == ["web"]


def test_youtube_to_dtos_returns_only_youtube_entries() -> None:
    mixed = [_link(1, "web"), _link(2, "youtube")]
    dtos = _youtube_to_dtos(mixed)
    assert len(dtos) == 1
    assert dtos[0].url == "https://example.com"
    assert not hasattr(dtos[0], "type")


def test_youtube_to_dtos_empty_returns_empty_list() -> None:
    assert _youtube_to_dtos([]) == []
    assert _youtube_to_dtos(None) == []


def test_links_to_dtos_strict_language_filter_no_fallback() -> None:
    links = [_link(1, language="EN"), _link(2, language="BO")]
    dtos = _links_to_dtos(links, language="BO", fallback=False)
    assert [dto.language for dto in dtos] == ["BO"]


def test_links_to_dtos_strict_filter_returns_empty_when_no_match() -> None:
    links = [_link(1, language="EN")]
    dtos = _links_to_dtos(links, language="ZH", fallback=False)
    assert dtos == []


def test_links_to_dtos_fallback_to_english_when_no_match() -> None:
    links = [_link(1, language="EN")]
    dtos = _links_to_dtos(links, language="BO", fallback=True)
    assert [dto.language for dto in dtos] == ["EN"]


def test_links_to_dtos_fallback_prefers_exact_match() -> None:
    links = [_link(1, language="EN"), _link(2, language="BO")]
    dtos = _links_to_dtos(links, language="BO", fallback=True)
    assert [dto.language for dto in dtos] == ["BO"]


def test_links_to_dtos_returns_all_entries_sharing_a_language() -> None:
    # Unlike metadata, links/youtube never collapse to a single object.
    links = [_link(1, language="EN"), _link(2, language="EN")]
    dtos = _links_to_dtos(links, language="EN", fallback=False)
    assert len(dtos) == 2


def test_youtube_to_dtos_fallback_to_english_when_no_match() -> None:
    entries = [_link(1, "youtube", language="EN")]
    dtos = _youtube_to_dtos(entries, language="BO", fallback=True)
    assert [dto.language for dto in dtos] == ["EN"]


# --------------------------- EventDTO serialization ---------------------------

def test_event_dto_serializes_links_ordered() -> None:
    now = datetime.now(timezone.utc)
    event = EventDTO(
        id=uuid4(),
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        is_one_day=True,
        featured=False,
        metadata=[],
        links=_links_to_dtos([_link(2, "web"), _link(1, "google-meet")]),
        created_at=now,
        created_by="author@example.com",
    )
    dumped = event.model_dump()
    assert [link["type"] for link in dumped["links"]] == ["google-meet", "web"]
    assert dumped["links"][0]["language"] == "EN"
    # label is None -> excluded via ser_json_exclude_none
    assert "label" not in event.model_dump(exclude_none=True)["links"][0]


def test_event_dto_serializes_youtube_without_type_key() -> None:
    now = datetime.now(timezone.utc)
    event = EventDTO(
        id=uuid4(),
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        is_one_day=True,
        featured=False,
        metadata=[],
        youtube=_youtube_to_dtos([_link(1, "youtube")]),
        created_at=now,
        created_by="author@example.com",
    )
    dumped = event.model_dump()
    assert len(dumped["youtube"]) == 1
    assert "type" not in dumped["youtube"][0]
    assert dumped["youtube"][0]["language"] == "EN"


# --------------------------- endpoint 422 on bad payloads ---------------------------

def test_create_event_endpoint_rejects_bad_url() -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/cms/events",
        headers={"Authorization": "Bearer token"},
        json={
            "group_id": str(uuid4()),
            "start_date": now,
            "end_date": now,
            "metadata": [{"name": "Event", "language": "EN"}],
            "links": [{"type": "web", "url": "ftp://bad.example.com", "language": "EN"}],
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_event_endpoint_rejects_unknown_type() -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/cms/events",
        headers={"Authorization": "Bearer token"},
        json={
            "group_id": str(uuid4()),
            "start_date": now,
            "end_date": now,
            "metadata": [{"name": "Event", "language": "EN"}],
            "links": [{"type": "carrier-pigeon", "url": "https://ok.example.com", "language": "EN"}],
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_event_endpoint_rejects_youtube_type_in_links() -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/cms/events",
        headers={"Authorization": "Bearer token"},
        json={
            "group_id": str(uuid4()),
            "start_date": now,
            "end_date": now,
            "metadata": [{"name": "Event", "language": "EN"}],
            "links": [{"type": "youtube", "url": "https://youtu.be/dQw4w9WgXcQ", "language": "EN"}],
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_event_endpoint_rejects_link_missing_language() -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/cms/events",
        headers={"Authorization": "Bearer token"},
        json={
            "group_id": str(uuid4()),
            "start_date": now,
            "end_date": now,
            "metadata": [{"name": "Event", "language": "EN"}],
            "links": [{"type": "web", "url": "https://ok.example.com"}],
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_event_endpoint_rejects_non_youtube_host_in_youtube_array() -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/cms/events",
        headers={"Authorization": "Bearer token"},
        json={
            "group_id": str(uuid4()),
            "start_date": now,
            "end_date": now,
            "metadata": [{"name": "Event", "language": "EN"}],
            "youtube": [{"url": "https://vimeo.com/12345", "language": "EN"}],
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# --------------------------- service passes links/youtube to repository ---------------------------

def _saved_event_stub() -> SimpleNamespace:
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


def test_create_event_service_passes_links_and_youtube_to_save() -> None:
    now = datetime.now(timezone.utc)
    request = CreateEventRequest(
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        metadata=[{"name": "Event", "language": "EN"}],
        links=[{"type": "web", "url": "https://example.com", "language": "EN"}],
        youtube=[{"url": "https://youtu.be/dQw4w9WgXcQ", "language": "EN"}],
    )
    author = SimpleNamespace(id=uuid4(), email="author@example.com")

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=author,
    ), patch(
        "pecha_api.events.event_service.require_can_create_content",
    ), patch(
        "pecha_api.events.event_service.save_event",
        return_value=_saved_event_stub(),
    ) as mock_save:
        create_event_service(token="token", request=request)

    # links are forwarded as the 4th positional arg; youtube by keyword
    _, args, kwargs = mock_save.mock_calls[0]
    forwarded_links = args[3] if len(args) > 3 else kwargs.get("link_entries")
    assert forwarded_links == request.links
    assert kwargs["youtube_entries"] == request.youtube


def test_update_event_service_replaces_links_and_youtube() -> None:
    request = UpdateEventRequest(
        links=[{"type": "google-meet", "url": "https://meet.google.com/abc", "language": "EN"}],
        youtube=[{"url": "https://youtu.be/dQw4w9WgXcQ", "language": "EN"}],
    )
    author = SimpleNamespace(id=uuid4(), email="author@example.com")
    existing = _saved_event_stub()

    with patch(
        "pecha_api.events.event_service.validate_cms_author_details",
        return_value=author,
    ), patch(
        "pecha_api.events.event_service.get_event_by_id",
        return_value=existing,
    ), patch(
        "pecha_api.events.event_service._require_can_edit_event",
    ), patch(
        "pecha_api.events.event_service.update_event",
        return_value=existing,
    ) as mock_update:
        update_event_service(token="token", event_id=existing.id, request=request)

    _, _, kwargs = mock_update.mock_calls[0]
    assert kwargs["link_entries"] == request.links
    assert kwargs["youtube_entries"] == request.youtube


# --------------------------- repository: scoped replace-all (real DB) ---------------------------
#
# The scoped delete predicates (type != 'youtube' vs type == 'youtube') are SQL
# behavior a mocked session can't meaningfully verify, so this uses a real
# in-memory SQLite session (StaticPool keeps it alive across two Session()
# calls), following the same pattern as test_event_reminder_repository.py.
# get_event_by_id is patched out since it eager-loads several unrelated
# relationship tables (plans, accumulators, mantra, ...) that aren't needed to
# verify the event_links rows themselves and aren't created in this schema.

def _make_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Event.metadata.create_all(bind=engine, tables=[Event.__table__, EventLink.__table__])
    return sessionmaker(bind=engine)


def _seed_event_with_links(db) -> Event:
    now = datetime.now(timezone.utc)
    event = Event(
        id=uuid4(),
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        created_by="author@example.com",
    )
    db.add(event)
    db.flush()
    db.add(EventLink(
        event_id=event.id, type="web", url="https://example.com/web",
        label=None, language=LanguageCode.EN, display_order=1,
    ))
    db.add(EventLink(
        event_id=event.id, type="youtube", url="https://youtu.be/dQw4w9WgXcQ",
        label=None, language=LanguageCode.EN, display_order=1,
    ))
    db.commit()
    return event


def _link_input(**overrides) -> EventLinkInput:
    defaults = {"type": "zoom", "url": "https://zoom.us/j/123", "language": "EN", "display_order": 1}
    defaults.update(overrides)
    return EventLinkInput(**defaults)


def _youtube_input(**overrides) -> EventYoutubeInput:
    defaults = {"url": "https://youtu.be/oHg5SJYRHA0", "language": "EN", "display_order": 1}
    defaults.update(overrides)
    return EventYoutubeInput(**defaults)


def test_update_event_link_entries_only_replaces_non_youtube_rows() -> None:
    Session = _make_sessionmaker()
    db = Session()
    event = _seed_event_with_links(db)

    with patch.object(event_repository_module, "get_event_by_id", side_effect=lambda _db, _id: event):
        update_event(db, event, link_entries=[_link_input()])

    rows = db.query(EventLink).filter(EventLink.event_id == event.id).all()
    assert sorted(row.type for row in rows) == ["youtube", "zoom"]


def test_update_event_youtube_entries_only_replaces_youtube_rows() -> None:
    Session = _make_sessionmaker()
    db = Session()
    event = _seed_event_with_links(db)

    with patch.object(event_repository_module, "get_event_by_id", side_effect=lambda _db, _id: event):
        update_event(db, event, youtube_entries=[_youtube_input()])

    rows = db.query(EventLink).filter(EventLink.event_id == event.id).all()
    assert sorted(row.type for row in rows) == ["web", "youtube"]
    youtube_row = next(row for row in rows if row.type == "youtube")
    assert youtube_row.url == "https://youtu.be/oHg5SJYRHA0"


def test_update_event_both_scopes_replace_independently() -> None:
    Session = _make_sessionmaker()
    db = Session()
    event = _seed_event_with_links(db)

    with patch.object(event_repository_module, "get_event_by_id", side_effect=lambda _db, _id: event):
        update_event(
            db, event,
            link_entries=[_link_input()],
            youtube_entries=[_youtube_input()],
        )

    rows = db.query(EventLink).filter(EventLink.event_id == event.id).all()
    assert sorted(row.type for row in rows) == ["youtube", "zoom"]


def test_update_event_neither_scope_leaves_links_untouched() -> None:
    Session = _make_sessionmaker()
    db = Session()
    event = _seed_event_with_links(db)

    with patch.object(event_repository_module, "get_event_by_id", side_effect=lambda _db, _id: event):
        update_event(db, event)

    rows = db.query(EventLink).filter(EventLink.event_id == event.id).all()
    assert sorted(row.type for row in rows) == ["web", "youtube"]
