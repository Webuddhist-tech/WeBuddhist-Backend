"""Coverage for the event <-> linked resource (plan/accumulator/mantra/timer/
group recitation collection) DTO builders added to event_service.py, so an
event's detail response actually carries the linked resource's id/name/image
instead of just its bare *_id."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from pecha_api.events.event_service import (
    _accumulator_to_linked_resource,
    _event_to_dto,
    _group_accumulator_to_linked_resource,
    _group_recitation_collection_to_linked_resource,
    _mantra_to_linked_resource,
    _plan_to_linked_resource,
    _presign_image_url,
    _timer_to_linked_resource,
)

MODULE = "pecha_api.events.event_service"


def _event(**overrides):
    now = datetime.now(timezone.utc)
    base = dict(
        id=uuid4(),
        plan_id=None,
        plan=None,
        accumulator_id=None,
        accumulator=None,
        mantra_id=None,
        mantra=None,
        timer_id=None,
        timer=None,
        group_recitation_collection_id=None,
        group_recitation_collection=None,
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
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------- _presign_image_url ---------------------------


def test_presign_image_url_returns_none_for_missing_value():
    assert _presign_image_url(None) is None
    assert _presign_image_url("") is None


@patch(f"{MODULE}.generate_presigned_access_url")
def test_presign_image_url_returns_presigned_url(mock_presign):
    mock_presign.return_value = "https://cdn.example.com/signed.jpg"

    assert _presign_image_url("images/plan.jpg") == "https://cdn.example.com/signed.jpg"


@patch(f"{MODULE}.generate_presigned_access_url")
def test_presign_image_url_swallows_errors(mock_presign):
    mock_presign.side_effect = Exception("boom")

    assert _presign_image_url("images/plan.jpg") is None


# --------------------------- plan ---------------------------


def test_plan_to_linked_resource_none_when_not_linked():
    assert _plan_to_linked_resource(_event()) is None


@patch(f"{MODULE}.generate_presigned_access_url")
def test_plan_to_linked_resource_populates_fields(mock_presign):
    mock_presign.return_value = "https://cdn.example.com/plan.jpg"
    plan = SimpleNamespace(id=uuid4(), title="21 Tara Practice", image_url="images/plan.jpg")

    resource = _plan_to_linked_resource(_event(plan=plan))

    assert resource.id == plan.id
    assert resource.name == "21 Tara Practice"
    assert resource.image_url == "https://cdn.example.com/plan.jpg"


# --------------------------- accumulator ---------------------------


def test_accumulator_to_linked_resource_none_when_not_linked():
    assert _accumulator_to_linked_resource(_event()) is None


def test_accumulator_to_linked_resource_populates_fields():
    metadata = SimpleNamespace(language="EN", name="Green Tara Mantra")
    accumulator = SimpleNamespace(id=uuid4(), metadata_entries=[metadata], mala=None)

    resource = _accumulator_to_linked_resource(_event(accumulator=accumulator))

    assert resource.id == accumulator.id
    assert resource.name == "Green Tara Mantra"
    assert resource.image_url is None


def test_accumulator_to_linked_resource_name_none_when_no_metadata():
    accumulator = SimpleNamespace(id=uuid4(), metadata_entries=[], mala=None)

    resource = _accumulator_to_linked_resource(_event(accumulator=accumulator))

    assert resource.name is None


# --------------------------- mantra ---------------------------


def test_mantra_to_linked_resource_none_when_not_linked():
    assert _mantra_to_linked_resource(_event()) is None


def test_mantra_to_linked_resource_populates_fields():
    metadata = SimpleNamespace(language="EN", title="Om Mani Padme Hum")
    mantra = SimpleNamespace(id=uuid4(), metadata_entries=[metadata], mala=None)

    resource = _mantra_to_linked_resource(_event(mantra=mantra))

    assert resource.id == mantra.id
    assert resource.name == "Om Mani Padme Hum"
    assert resource.image_url is None


def test_mantra_to_linked_resource_name_none_when_no_metadata():
    mantra = SimpleNamespace(id=uuid4(), metadata_entries=[], mala=None)

    resource = _mantra_to_linked_resource(_event(mantra=mantra))

    assert resource.name is None


# --------------------------- timer ---------------------------


def test_timer_to_linked_resource_none_when_not_linked():
    assert _timer_to_linked_resource(_event()) is None


def test_timer_to_linked_resource_populates_fields():
    timer = SimpleNamespace(id=uuid4(), name="Morning Meditation")

    resource = _timer_to_linked_resource(_event(timer=timer))

    assert resource.id == timer.id
    assert resource.name == "Morning Meditation"
    assert resource.image_url is None


# --------------------------- group accumulator ---------------------------


def test_group_accumulator_to_linked_resource_none_when_not_linked():
    assert _group_accumulator_to_linked_resource(_event()) is None


@patch(f"{MODULE}.generate_presigned_access_url")
def test_group_accumulator_uses_localized_title(mock_presign):
    mock_presign.return_value = "https://cdn.example.com/accumulation.jpg"
    group_accumulator = SimpleNamespace(
        id=uuid4(),
        title="Green Tara Accumulation",
        image_key="images/accumulation.jpg",
        metadata_entries=[
            SimpleNamespace(language="EN", title="Green Tara Accumulation"),
            SimpleNamespace(language="BO", title="སྒྲོལ་མའི་བསགས་པ།"),
        ],
    )

    resource = _group_accumulator_to_linked_resource(
        _event(group_accumulator=group_accumulator), language="bo"
    )

    assert resource.id == group_accumulator.id
    assert resource.name == "སྒྲོལ་མའི་བསགས་པ།"
    assert resource.image_url == "https://cdn.example.com/accumulation.jpg"


def test_group_accumulator_falls_back_to_row_title_when_language_is_missing():
    group_accumulator = SimpleNamespace(
        id=uuid4(),
        title="Green Tara Accumulation",
        image_key=None,
        metadata_entries=[
            SimpleNamespace(language="EN", title="Green Tara Accumulation"),
        ],
    )

    resource = _group_accumulator_to_linked_resource(
        _event(group_accumulator=group_accumulator), language="bo"
    )

    assert resource.name == "Green Tara Accumulation"


def test_group_accumulator_uses_row_title_when_there_is_no_metadata():
    group_accumulator = SimpleNamespace(
        id=uuid4(),
        title="Green Tara Accumulation",
        image_key=None,
        metadata_entries=[],
    )

    resource = _group_accumulator_to_linked_resource(
        _event(group_accumulator=group_accumulator), language="bo"
    )

    assert resource.name == "Green Tara Accumulation"


def test_event_to_dto_passes_language_to_group_accumulator_name():
    group_accumulator = SimpleNamespace(
        id=uuid4(),
        title="English title",
        image_key=None,
        metadata_entries=[
            SimpleNamespace(language="EN", title="English title"),
            SimpleNamespace(language="BO", title="བོད་ཡིག"),
        ],
    )

    dto = _event_to_dto(
        _event(group_accumulator=group_accumulator, group_accumulator_id=group_accumulator.id),
        language="bo",
    )

    assert dto.group_accumulator.name == "བོད་ཡིག"


# --------------------------- group recitation collection ---------------------------


def test_group_recitation_collection_to_linked_resource_none_when_not_linked():
    assert _group_recitation_collection_to_linked_resource(_event()) is None


@patch(f"{MODULE}.generate_presigned_access_url")
def test_group_recitation_collection_to_linked_resource_populates_fields(mock_presign):
    mock_presign.return_value = "https://cdn.example.com/collection.jpg"
    collection = SimpleNamespace(id=uuid4(), name="Daily Chants", img_url="images/collection.jpg")

    resource = _group_recitation_collection_to_linked_resource(
        _event(group_recitation_collection=collection)
    )

    assert resource.id == collection.id
    assert resource.name == "Daily Chants"
    assert resource.image_url == "https://cdn.example.com/collection.jpg"


# --------------------------- integration via _event_to_dto ---------------------------


@patch(f"{MODULE}.generate_presigned_access_url")
def test_event_to_dto_includes_every_linked_resource(mock_presign):
    mock_presign.return_value = "https://cdn.example.com/img.jpg"
    plan = SimpleNamespace(id=uuid4(), title="Plan", image_url="images/plan.jpg")
    accumulator = SimpleNamespace(
        id=uuid4(),
        metadata_entries=[SimpleNamespace(language="EN", name="Accumulator")],
        mala=None,
    )
    mantra = SimpleNamespace(
        id=uuid4(),
        metadata_entries=[SimpleNamespace(language="EN", title="Mantra")],
        mala=None,
    )
    timer = SimpleNamespace(id=uuid4(), name="Timer")
    collection = SimpleNamespace(id=uuid4(), name="Collection", img_url="images/collection.jpg")

    event = _event(
        plan=plan,
        accumulator=accumulator,
        mantra=mantra,
        timer=timer,
        group_recitation_collection=collection,
    )

    dto = _event_to_dto(event)

    assert dto.plan.id == plan.id and dto.plan.name == "Plan"
    assert dto.accumulator.id == accumulator.id and dto.accumulator.name == "Accumulator"
    assert dto.mantra.id == mantra.id and dto.mantra.name == "Mantra"
    assert dto.timer.id == timer.id and dto.timer.name == "Timer"
    assert dto.group_recitation_collection.id == collection.id
    assert dto.group_recitation_collection.name == "Collection"


def test_event_to_dto_all_linked_resources_none_when_event_has_no_links():
    dto = _event_to_dto(_event())

    assert dto.plan is None
    assert dto.accumulator is None
    assert dto.mantra is None
    assert dto.timer is None
    assert dto.group_recitation_collection is None
