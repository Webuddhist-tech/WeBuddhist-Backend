from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterator, List, Tuple
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette import status

from pecha_api.app import api  # noqa: F401
from pecha_api.db.database import Base
from pecha_api.events.location_metadata_model import LocationMetadata
from pecha_api.events.location_model import Location
from pecha_api.events.location_repository import (
    delete_location,
    get_locations,
    save_location,
    update_location,
)
from pecha_api.events.location_response_models import (
    CreateLocationRequest,
    LocationMetadataInput,
    UpdateLocationRequest,
)
from pecha_api.events.location_service import (
    create_location_service,
    delete_location_service,
    get_location_by_id_service,
    get_locations_service,
    update_location_service,
)
from pecha_api.plans.plans_enums import LanguageCode

MODULE = "pecha_api.events.location_service"
REPO_MODULE = "pecha_api.events.location_repository"


def _author() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), email="author@example.com")


def _location_stub(group_id=None, name="Tushita Meditation Centre", latitude=None, longitude=None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        group_id=group_id or uuid4(),
        name=name,
        latitude=latitude,
        longitude=longitude,
        created_at=now,
        updated_at=now,
        created_by="author@example.com",
    )


def _patch_auth(read_ok=True, write_ok=True):
    return (
        patch(f"{MODULE}.validate_cms_author_details", return_value=_author()),
        patch(f"{MODULE}.require_can_read_group_content"),
        patch(f"{MODULE}.require_can_create_content"),
    )


# --------------------------- request validation ---------------------------


def test_create_request_accepts_name_only() -> None:
    request = CreateLocationRequest(name="Online")
    assert request.name == "Online"
    assert request.latitude is None
    assert request.longitude is None


def test_create_request_accepts_name_with_coordinates() -> None:
    request = CreateLocationRequest(
        name="Tushita Meditation Centre",
        latitude=Decimal("32.242305"),
        longitude=Decimal("76.321284"),
    )
    assert request.latitude == Decimal("32.242305")
    assert request.longitude == Decimal("76.321284")


def test_create_request_trims_name() -> None:
    assert CreateLocationRequest(name="  Online  ").name == "Online"


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_create_request_rejects_blank_name(name: str) -> None:
    with pytest.raises(ValidationError):
        CreateLocationRequest(name=name)


def test_create_request_rejects_latitude_without_longitude() -> None:
    with pytest.raises(ValidationError):
        CreateLocationRequest(name="X", latitude=Decimal("32.0"))


def test_create_request_rejects_longitude_without_latitude() -> None:
    with pytest.raises(ValidationError):
        CreateLocationRequest(name="X", longitude=Decimal("76.0"))


@pytest.mark.parametrize("latitude", ["95", "-95", "100", "-100"])
def test_create_request_rejects_out_of_range_latitude(latitude: str) -> None:
    with pytest.raises(ValidationError):
        CreateLocationRequest(
            name="X", latitude=Decimal(latitude), longitude=Decimal("0")
        )


@pytest.mark.parametrize("longitude", ["200", "-200", "181", "-181"])
def test_create_request_rejects_out_of_range_longitude(longitude: str) -> None:
    with pytest.raises(ValidationError):
        CreateLocationRequest(
            name="X", latitude=Decimal("0"), longitude=Decimal(longitude)
        )


@pytest.mark.parametrize(
    "latitude,longitude",
    [("0", "0"), ("90", "180"), ("-90", "-180"), ("0.000001", "-0.000001")],
)
def test_create_request_accepts_boundary_coordinates(latitude, longitude) -> None:
    request = CreateLocationRequest(
        name="X", latitude=Decimal(latitude), longitude=Decimal(longitude)
    )
    assert request.latitude == Decimal(latitude)


def test_update_request_rejects_explicit_null_name() -> None:
    with pytest.raises(ValidationError):
        UpdateLocationRequest(**{"name": None})


def test_update_request_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        UpdateLocationRequest(name="   ")


def test_update_request_clears_coordinates_with_both_null() -> None:
    request = UpdateLocationRequest(**{"latitude": None, "longitude": None})
    assert "latitude" in request.model_fields_set
    assert request.latitude is None
    assert request.longitude is None


@pytest.mark.parametrize(
    "payload",
    [{"latitude": None}, {"longitude": None}, {"latitude": "32.0"}],
)
def test_update_request_rejects_unpaired_coordinates(payload: dict) -> None:
    with pytest.raises(ValidationError):
        UpdateLocationRequest(**payload)


def test_update_request_allows_empty_payload() -> None:
    request = UpdateLocationRequest()
    assert request.model_fields_set == set()


# --------------------------- create ---------------------------


def test_create_location_persists_and_returns_dto() -> None:
    group_id = uuid4()
    request = CreateLocationRequest(
        name="Tushita Meditation Centre",
        latitude=Decimal("32.242305"),
        longitude=Decimal("76.321284"),
    )
    saved = _location_stub(
        group_id=group_id,
        latitude=Decimal("32.242305"),
        longitude=Decimal("76.321284"),
    )

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ) as mock_permission, patch(
        f"{MODULE}.SessionLocal"
    ), patch(
        f"{MODULE}.save_location", return_value=saved
    ) as mock_save:
        result = create_location_service(
            token="token", group_id=group_id, request=request
        )

    mock_permission.assert_called_once()
    persisted = mock_save.mock_calls[0].kwargs["location"]
    assert persisted.name == "Tushita Meditation Centre"
    assert persisted.group_id == group_id
    assert persisted.created_by == "author@example.com"
    assert result.name == "Tushita Meditation Centre"
    assert result.event_count == 0


def test_create_location_name_only_stores_null_coordinates() -> None:
    group_id = uuid4()
    request = CreateLocationRequest(name="Online")
    saved = _location_stub(group_id=group_id, name="Online")

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.save_location", return_value=saved
    ) as mock_save:
        result = create_location_service(
            token="token", group_id=group_id, request=request
        )

    persisted = mock_save.mock_calls[0].kwargs["location"]
    assert persisted.latitude is None
    assert persisted.longitude is None
    assert result.latitude is None


def test_create_location_requires_create_permission() -> None:
    group_id = uuid4()
    request = CreateLocationRequest(name="Online")

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content",
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no"),
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.save_location"
    ) as mock_save:
        with pytest.raises(HTTPException) as exc:
            create_location_service(token="token", group_id=group_id, request=request)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_save.assert_not_called()


# --------------------------- list ---------------------------


def test_list_locations_returns_paginated_envelope() -> None:
    group_id = uuid4()
    first = _location_stub(group_id=group_id, name="Online")
    second = _location_stub(group_id=group_id, name="Tushita")

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_read_group_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_locations", return_value=([first, second], 2)
    ), patch(
        f"{MODULE}.get_event_counts", return_value={first.id: 3}
    ):
        result = get_locations_service(token="token", group_id=group_id)

    assert result.total == 2
    assert result.skip == 0
    assert result.limit == 20
    assert [location.name for location in result.locations] == ["Online", "Tushita"]
    assert result.locations[0].event_count == 3
    assert result.locations[1].event_count == 0


def test_list_locations_forwards_search_to_repository() -> None:
    group_id = uuid4()

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_read_group_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_locations", return_value=([], 0)
    ) as mock_get, patch(
        f"{MODULE}.get_event_counts", return_value={}
    ):
        result = get_locations_service(
            token="token", group_id=group_id, search="tush", skip=5, limit=50
        )

    kwargs = mock_get.mock_calls[0].kwargs
    assert kwargs["search"] == "tush"
    assert kwargs["skip"] == 5
    assert kwargs["limit"] == 50
    assert result.total == 0


def test_list_locations_requires_read_permission() -> None:
    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_read_group_content",
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="no"),
    ), patch(f"{MODULE}.SessionLocal"), patch(f"{MODULE}.get_locations") as mock_get:
        with pytest.raises(HTTPException) as exc:
            get_locations_service(token="token", group_id=uuid4())

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_get.assert_not_called()


# --------------------------- detail ---------------------------


def test_get_location_detail_includes_event_count() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_read_group_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=location
    ), patch(
        f"{MODULE}.get_event_count", return_value=7
    ):
        result = get_location_by_id_service(
            token="token", group_id=group_id, location_id=location.id
        )

    assert result.id == location.id
    assert result.event_count == 7


def test_get_location_detail_unknown_returns_404() -> None:
    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_read_group_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=None
    ):
        with pytest.raises(HTTPException) as exc:
            get_location_by_id_service(
                token="token", group_id=uuid4(), location_id=uuid4()
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_get_location_from_other_group_returns_404() -> None:
    """Group scoping is enforced by the repository filter, so a location that
    exists in another group is indistinguishable from one that does not exist."""
    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_read_group_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=None
    ) as mock_get:
        with pytest.raises(HTTPException) as exc:
            get_location_by_id_service(
                token="token", group_id=uuid4(), location_id=uuid4()
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert "group_id" in mock_get.mock_calls[0].kwargs


# --------------------------- update ---------------------------


def test_update_location_changes_name_only() -> None:
    group_id = uuid4()
    location = _location_stub(
        group_id=group_id, latitude=Decimal("32.0"), longitude=Decimal("76.0")
    )
    request = UpdateLocationRequest(name="Renamed")

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=location
    ), patch(
        f"{MODULE}.update_location", side_effect=lambda db, location, translations=None: location
    ), patch(
        f"{MODULE}.get_event_count", return_value=2
    ):
        result = update_location_service(
            token="token",
            group_id=group_id,
            location_id=location.id,
            request=request,
        )

    assert location.name == "Renamed"
    assert location.latitude == Decimal("32.0")
    assert result.event_count == 2


def test_update_location_clears_coordinates_with_explicit_nulls() -> None:
    group_id = uuid4()
    location = _location_stub(
        group_id=group_id, latitude=Decimal("32.0"), longitude=Decimal("76.0")
    )
    request = UpdateLocationRequest(**{"latitude": None, "longitude": None})

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=location
    ), patch(
        f"{MODULE}.update_location", side_effect=lambda db, location, translations=None: location
    ), patch(
        f"{MODULE}.get_event_count", return_value=0
    ):
        update_location_service(
            token="token",
            group_id=group_id,
            location_id=location.id,
            request=request,
        )

    assert location.latitude is None
    assert location.longitude is None


def test_update_location_omitting_coordinates_leaves_them_untouched() -> None:
    group_id = uuid4()
    location = _location_stub(
        group_id=group_id, latitude=Decimal("32.0"), longitude=Decimal("76.0")
    )
    request = UpdateLocationRequest(name="Renamed")

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=location
    ), patch(
        f"{MODULE}.update_location", side_effect=lambda db, location, translations=None: location
    ), patch(
        f"{MODULE}.get_event_count", return_value=0
    ):
        update_location_service(
            token="token",
            group_id=group_id,
            location_id=location.id,
            request=request,
        )

    assert location.latitude == Decimal("32.0")
    assert location.longitude == Decimal("76.0")


def test_update_location_unknown_returns_404() -> None:
    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=None
    ), patch(
        f"{MODULE}.update_location"
    ) as mock_update:
        with pytest.raises(HTTPException) as exc:
            update_location_service(
                token="token",
                group_id=uuid4(),
                location_id=uuid4(),
                request=UpdateLocationRequest(name="X"),
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_update.assert_not_called()


# --------------------------- delete ---------------------------


def test_delete_unreferenced_location_succeeds() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=location
    ), patch(
        f"{MODULE}.get_event_count", return_value=0
    ), patch(
        f"{MODULE}.delete_location"
    ) as mock_delete:
        delete_location_service(
            token="token", group_id=group_id, location_id=location.id
        )

    mock_delete.assert_called_once()


def test_delete_referenced_location_returns_409_with_event_count() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=location
    ), patch(
        f"{MODULE}.get_event_count", return_value=7
    ), patch(
        f"{MODULE}.delete_location"
    ) as mock_delete:
        with pytest.raises(HTTPException) as exc:
            delete_location_service(
                token="token", group_id=group_id, location_id=location.id
            )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert exc.value.detail["error"] == "LOCATION_IN_USE"
    assert exc.value.detail["event_count"] == 7
    mock_delete.assert_not_called()


def test_delete_location_race_returns_409_not_500() -> None:
    location = _location_stub()
    db = MagicMock()
    db.commit.side_effect = IntegrityError("stmt", {}, Exception("FK violation"))

    with patch(f"{REPO_MODULE}.get_event_count", return_value=1):
        with pytest.raises(HTTPException) as exc:
            delete_location(db=db, location=location)

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert exc.value.detail["error"] == "LOCATION_IN_USE"
    assert exc.value.detail["event_count"] == 1
    db.rollback.assert_called_once()


def test_save_location_integrity_error_returns_400_not_500() -> None:
    db = MagicMock()
    db.commit.side_effect = IntegrityError("stmt", {}, Exception("FK violation"))

    with pytest.raises(HTTPException) as exc:
        save_location(db=db, location=_location_stub())

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    db.rollback.assert_called_once()


def test_update_location_integrity_error_returns_400_not_500() -> None:
    db = MagicMock()
    db.commit.side_effect = IntegrityError("stmt", {}, Exception("constraint"))

    with pytest.raises(HTTPException) as exc:
        update_location(db=db, location=_location_stub())

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    db.rollback.assert_called_once()


def test_delete_unknown_location_returns_404() -> None:
    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=None
    ), patch(
        f"{MODULE}.delete_location"
    ) as mock_delete:
        with pytest.raises(HTTPException) as exc:
            delete_location_service(
                token="token", group_id=uuid4(), location_id=uuid4()
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_delete.assert_not_called()


# --------------------------- localized names ---------------------------


def _translation(language: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), name=name, language=language)


def test_create_request_accepts_translations() -> None:
    request = CreateLocationRequest(
        name="Bodh Gaya",
        translations=[
            {"language": "EN", "name": "Bodh Gaya"},
            {"language": "BO", "name": "རྡོ་རྗེ་གདན་"},
        ],
    )

    assert [entry.language.value for entry in request.translations] == ["EN", "BO"]


def test_create_request_rejects_duplicate_translation_languages() -> None:
    with pytest.raises(ValidationError):
        CreateLocationRequest(
            name="Bodh Gaya",
            translations=[
                {"language": "EN", "name": "Bodh Gaya"},
                {"language": "EN", "name": "Bodhgaya"},
            ],
        )


def test_create_request_rejects_blank_translation_name() -> None:
    with pytest.raises(ValidationError):
        CreateLocationRequest(
            name="Bodh Gaya", translations=[{"language": "EN", "name": "   "}]
        )


def test_update_request_omitting_translations_leaves_them_untouched() -> None:
    request = UpdateLocationRequest(name="Renamed")

    assert request.translations is None


def test_update_request_empty_translations_clears_them() -> None:
    request = UpdateLocationRequest(translations=[])

    assert request.translations == []


def test_create_location_forwards_translations_to_repository() -> None:
    group_id = uuid4()
    request = CreateLocationRequest(
        name="Bodh Gaya", translations=[{"language": "BO", "name": "རྡོ་"}]
    )
    saved = _location_stub(group_id=group_id, name="Bodh Gaya")
    saved.metadata_entries = [_translation("BO", "རྡོ་")]

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.save_location", return_value=saved
    ) as mock_save:
        result = create_location_service(
            token="token", group_id=group_id, request=request
        )

    forwarded = mock_save.mock_calls[0].kwargs["translations"]
    assert [entry.language.value for entry in forwarded] == ["BO"]
    assert [entry.language for entry in result.translations] == ["BO"]


def test_update_location_forwards_translations_to_repository() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)
    location.metadata_entries = []
    request = UpdateLocationRequest(
        translations=[{"language": "EN", "name": "Tushita"}]
    )

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=location
    ), patch(
        f"{MODULE}.update_location", side_effect=lambda db, location, translations=None: location
    ) as mock_update, patch(
        f"{MODULE}.get_event_count", return_value=0
    ):
        update_location_service(
            token="token",
            group_id=group_id,
            location_id=location.id,
            request=request,
        )

    forwarded = mock_update.mock_calls[0].kwargs["translations"]
    assert [entry.name for entry in forwarded] == ["Tushita"]


def test_location_detail_lists_translations_by_language() -> None:
    group_id = uuid4()
    location = _location_stub(group_id=group_id)
    location.metadata_entries = [
        _translation("BO", "རྡོ་"),
        _translation("EN", "Bodh Gaya"),
    ]

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_read_group_content"
    ), patch(f"{MODULE}.SessionLocal"), patch(
        f"{MODULE}.get_location_by_id", return_value=location
    ), patch(
        f"{MODULE}.get_event_count", return_value=0
    ):
        result = get_location_by_id_service(
            token="token", group_id=group_id, location_id=location.id
        )

    assert [entry.language for entry in result.translations] == ["BO", "EN"]


def test_save_location_persists_translation_rows() -> None:
    db = MagicMock()
    location = _location_stub()

    save_location(
        db=db,
        location=location,
        translations=[LocationMetadataInput(name="Bodh Gaya", language="EN")],
    )

    added = [
        call.args[0]
        for call in db.add.mock_calls
        if call.args and isinstance(call.args[0], LocationMetadata)
    ]
    assert [row.name for row in added] == ["Bodh Gaya"]
    assert [row.location_id for row in added] == [location.id]


def test_update_location_replaces_translation_rows() -> None:
    db = MagicMock()
    location = _location_stub()

    update_location(
        db=db,
        location=location,
        translations=[LocationMetadataInput(name="Tushita", language="EN")],
    )

    # The existing rows for this location are cleared before the new set lands.
    db.query.return_value.filter.return_value.delete.assert_called_once()
    added = [
        call.args[0]
        for call in db.add.mock_calls
        if call.args and isinstance(call.args[0], LocationMetadata)
    ]
    assert [row.name for row in added] == ["Tushita"]


def test_update_location_without_translations_leaves_rows_alone() -> None:
    db = MagicMock()

    update_location(db=db, location=_location_stub())

    db.query.assert_not_called()


# --- translated-name search and translation replace, against a real database ---
# A mocked session can only record that filter/delete/add were called. It
# cannot tell whether a Tibetan translation matches, whether that match is
# counted once, or whether the location handed back after commit and refresh
# still holds the translations that were just replaced.


def _location_sessionmaker() -> sessionmaker:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[Location.__table__, LocationMetadata.__table__],
    )
    return sessionmaker(bind=engine)


@pytest.fixture
def location_db() -> Iterator[Session]:
    db = _location_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def _persist_location(
    db: Session,
    group_id: UUID,
    name: str,
    translations: List[Tuple[str, str]] | None = None,
) -> Location:
    now = datetime.now(timezone.utc)
    location = Location(
        id=uuid4(),
        group_id=group_id,
        name=name,
        created_at=now,
        updated_at=now,
        created_by="author@example.com",
    )
    db.add(location)
    db.flush()
    for language, translated_name in translations or []:
        db.add(
            LocationMetadata(
                id=uuid4(),
                location_id=location.id,
                name=translated_name,
                language=LanguageCode(language),
            )
        )
    db.commit()
    return location


def test_search_matches_a_translated_name_in_the_same_group(location_db: Session) -> None:
    """Canonical name is English; the editor searched the Tibetan translation."""
    group_id = uuid4()
    matching = _persist_location(
        location_db,
        group_id,
        "Bodh Gaya",
        [("BO", "རྡོ་རྗེ་གདན།")],
    )
    _persist_location(location_db, group_id, "Tushita", [("EN", "Tushita")])
    _persist_location(
        location_db,
        uuid4(),
        "Bodh Gaya",
        [("BO", "རྡོ་རྗེ་གདན།")],
    )

    locations, total = get_locations(
        db=location_db, group_id=group_id, search="རྡོ་རྗེ་གདན།"
    )

    assert [row.id for row in locations] == [matching.id]
    assert total == 1


def test_search_still_matches_the_canonical_name(location_db: Session) -> None:
    group_id = uuid4()
    matching = _persist_location(
        location_db,
        group_id,
        "Bodh Gaya",
        [("BO", "རྡོ་རྗེ་གདན།")],
    )

    locations, total = get_locations(db=location_db, group_id=group_id, search="bodh")

    assert [row.id for row in locations] == [matching.id]
    assert total == 1


def test_search_counts_a_location_once_when_several_names_match(
    location_db: Session,
) -> None:
    """EXISTS, not a join: the name and two translations are still one row."""
    group_id = uuid4()
    matching = _persist_location(
        location_db,
        group_id,
        "Bodh Gaya",
        [("EN", "Bodh Gaya"), ("BO", "Bodh Gaya in Tibetan")],
    )
    _persist_location(location_db, group_id, "Tushita", [("EN", "Tushita")])

    locations, total = get_locations(db=location_db, group_id=group_id, search="bodh")

    assert [row.id for row in locations] == [matching.id]
    assert total == 1


def test_search_paginates_while_total_reports_every_match(location_db: Session) -> None:
    group_id = uuid4()
    for name in ("Alpha", "Beta", "Gamma"):
        _persist_location(
            location_db,
            group_id,
            name,
            [("BO", f"Temple {name}")],
        )

    first_page, total = get_locations(
        db=location_db, group_id=group_id, search="Temple", skip=0, limit=2
    )
    second_page, second_total = get_locations(
        db=location_db, group_id=group_id, search="Temple", skip=2, limit=2
    )

    assert [row.name for row in first_page] == ["Alpha", "Beta"]
    assert [row.name for row in second_page] == ["Gamma"]
    assert total == 3
    assert second_total == 3


def test_update_location_returns_replacement_translations_after_refresh() -> None:
    factory = _location_sessionmaker()
    db = factory()
    group_id = uuid4()
    location = _persist_location(
        db,
        group_id,
        "Bodh Gaya",
        [("EN", "Bodh Gaya"), ("BO", "རྡོ་")],
    )
    location_id = location.id
    db.close()

    request = UpdateLocationRequest(
        translations=[
            {"language": "EN", "name": "Vajrasana"},
            {"language": "BO", "name": "རྡོ་རྗེ་གདན།"},
        ]
    )

    with patch(f"{MODULE}.validate_cms_author_details", return_value=_author()), patch(
        f"{MODULE}.require_can_create_content"
    ), patch(f"{MODULE}.SessionLocal", factory), patch(
        f"{MODULE}.get_event_count", return_value=0
    ):
        result = update_location_service(
            token="token",
            group_id=group_id,
            location_id=location_id,
            request=request,
        )

    assert [(entry.language, entry.name) for entry in result.translations] == [
        ("BO", "རྡོ་རྗེ་གདན།"),
        ("EN", "Vajrasana"),
    ]

    check = factory()
    try:
        stored = (
            check.query(LocationMetadata)
            .filter(LocationMetadata.location_id == location_id)
            .all()
        )
        assert sorted((row.language.value, row.name) for row in stored) == [
            ("BO", "རྡོ་རྗེ་གདན།"),
            ("EN", "Vajrasana"),
        ]
    finally:
        check.close()
