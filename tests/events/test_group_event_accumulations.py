"""Junction table sync and in-person resolution for event accumulations."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.events.event_accumulation_in_person import (
    EVENT_ACCUMULATION_ID_REQUIRED,
    NO_MANUAL_EVENT_ACCUMULATION,
    resolve_manual_in_person_target,
)
from pecha_api.events.event_enums import EventAccumulationCountMode
from pecha_api.events.event_service import _accumulation_links_to_dtos
from pecha_api.events.group_event_accumulation_repository import (
    EventAccumulationSyncInput,
    sync_event_accumulations,
    upsert_legacy_single_accumulation,
)


def test_resolve_requires_event_accumulation_id_when_multiple_manual_links():
    event = MagicMock()
    event.id = uuid4()
    event.group_accumulator_id = uuid4()
    link_a = MagicMock(
        id=uuid4(),
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    link_b = MagicMock(
        id=uuid4(),
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    db = MagicMock()
    with patch(
        "pecha_api.events.event_accumulation_in_person.list_accumulations_for_event",
        return_value=[link_a, link_b],
    ), pytest.raises(HTTPException) as exc:
        resolve_manual_in_person_target(db, event, event_accumulation_id=None)
    assert exc.value.detail == EVENT_ACCUMULATION_ID_REQUIRED


def test_sync_preserves_stable_ids_on_update():
    event_id = uuid4()
    group_id = uuid4()
    link_id = uuid4()
    ga_id = uuid4()
    existing = MagicMock(
        id=link_id,
        event_id=event_id,
        group_accumulator_id=ga_id,
        parent_id=None,
        event_format="hybrid",
        display_order=1,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.side_effect = [
        [existing],
        [existing],
    ]
    ga = MagicMock(group_id=group_id, deleted_at=None)
    db.query.return_value.filter.return_value.first.return_value = ga

    sync_event_accumulations(
        db,
        event_id=event_id,
        group_id=group_id,
        inputs=[
            EventAccumulationSyncInput(
                id=link_id,
                group_accumulator_id=ga_id,
                event_format="offline",
                display_order=2,
                count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
            )
        ],
    )

    assert existing.event_format == "offline"
    assert existing.display_order == 2
    db.delete.assert_not_called()


def _link(
    *,
    link_id,
    group_accumulator_id,
    count_mode,
    display_order=1,
    event_format="hybrid",
):
    ga = SimpleNamespace(id=group_accumulator_id, title="practice", image_key=None)
    return SimpleNamespace(
        id=link_id,
        group_accumulator_id=group_accumulator_id,
        parent_id=None,
        event_format=event_format,
        display_order=display_order,
        count_mode=count_mode,
        group_accumulator=ga,
    )


def test_tara_sadhana_offline_count_only_on_offline_participants_link():
    """Sadhana uses offline_participants; 21 Praise manual link has no RSVP metric."""
    sadhana_ga = uuid4()
    praise_ga = uuid4()
    sadhana_link = _link(
        link_id=uuid4(),
        group_accumulator_id=sadhana_ga,
        count_mode=EventAccumulationCountMode.OFFLINE_PARTICIPANTS.value,
        display_order=1,
        event_format="offline",
    )
    praise_link = _link(
        link_id=uuid4(),
        group_accumulator_id=praise_ga,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
        display_order=2,
        event_format="offline",
    )

    dtos = _accumulation_links_to_dtos(
        [praise_link, sadhana_link],
        language=None,
        offline_participant_count=7,
    )

    assert len(dtos) == 2
    by_ga = {dto.group_accumulator_id: dto for dto in dtos}
    assert by_ga[sadhana_ga].offline_participant_count == 7
    assert by_ga[sadhana_ga].count_mode == EventAccumulationCountMode.OFFLINE_PARTICIPANTS
    assert by_ga[praise_ga].offline_participant_count is None
    assert by_ga[praise_ga].count_mode == EventAccumulationCountMode.MANUAL_IN_PERSON


def test_in_person_rejects_offline_participants_junction_link():
    event = MagicMock()
    event.id = uuid4()
    sadhana_link_id = uuid4()
    sadhana_link = _link(
        link_id=sadhana_link_id,
        group_accumulator_id=uuid4(),
        count_mode=EventAccumulationCountMode.OFFLINE_PARTICIPANTS.value,
    )
    db = MagicMock()
    with patch(
        "pecha_api.events.event_accumulation_in_person.list_accumulations_for_event",
        return_value=[sadhana_link],
    ), pytest.raises(HTTPException) as exc:
        resolve_manual_in_person_target(db, event, event_accumulation_id=sadhana_link_id)
    assert exc.value.status_code == 409
    assert exc.value.detail == NO_MANUAL_EVENT_ACCUMULATION


def test_tara_praise_manual_in_person_resolves_independently():
    """In-person counts target the Praise junction row and its group accumulator."""
    event = MagicMock()
    event.id = uuid4()
    event.group_accumulator_id = uuid4()
    sadhana_link = _link(
        link_id=uuid4(),
        group_accumulator_id=uuid4(),
        count_mode=EventAccumulationCountMode.OFFLINE_PARTICIPANTS.value,
    )
    praise_link_id = uuid4()
    praise_ga = uuid4()
    praise_link = _link(
        link_id=praise_link_id,
        group_accumulator_id=praise_ga,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    db = MagicMock()
    with patch(
        "pecha_api.events.event_accumulation_in_person.list_accumulations_for_event",
        return_value=[sadhana_link, praise_link],
    ):
        link_id, ga_id = resolve_manual_in_person_target(
            db, event, event_accumulation_id=praise_link_id
        )
    assert link_id == praise_link_id
    assert ga_id == praise_ga


def test_upsert_legacy_does_not_delete_other_junction_links():
    event_id = uuid4()
    group_id = uuid4()
    sadhana_ga = uuid4()
    praise_ga = uuid4()
    sadhana_row = MagicMock(
        id=uuid4(),
        event_id=event_id,
        group_accumulator_id=sadhana_ga,
        display_order=1,
        event_format="offline",
        count_mode=EventAccumulationCountMode.OFFLINE_PARTICIPANTS.value,
    )
    praise_row = MagicMock(
        id=uuid4(),
        event_id=event_id,
        group_accumulator_id=praise_ga,
        display_order=2,
        event_format="offline",
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        sadhana_row,
        praise_row,
    ]
    ga = MagicMock(group_id=group_id, deleted_at=None)
    db.query.return_value.filter.return_value.first.return_value = ga

    with patch(
        "pecha_api.events.group_event_accumulation_repository.sync_event_accumulations"
    ) as mock_sync:
        upsert_legacy_single_accumulation(
            db,
            event_id=event_id,
            group_id=group_id,
            group_accumulator_id=praise_ga,
            event_format="hybrid",
        )

    mock_sync.assert_not_called()
    assert praise_row.event_format == "hybrid"
    assert praise_row.count_mode == EventAccumulationCountMode.MANUAL_IN_PERSON.value
    db.delete.assert_not_called()


def test_resolve_single_manual_link_without_event_accumulation_id():
    event = MagicMock()
    event.id = uuid4()
    praise_link_id = uuid4()
    praise_ga = uuid4()
    praise_link = _link(
        link_id=praise_link_id,
        group_accumulator_id=praise_ga,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    sadhana_link = _link(
        link_id=uuid4(),
        group_accumulator_id=uuid4(),
        count_mode=EventAccumulationCountMode.OFFLINE_PARTICIPANTS.value,
    )
    db = MagicMock()
    with patch(
        "pecha_api.events.event_accumulation_in_person.list_accumulations_for_event",
        return_value=[sadhana_link, praise_link],
    ):
        link_id, ga_id = resolve_manual_in_person_target(db, event, event_accumulation_id=None)
    assert link_id == praise_link_id
    assert ga_id == praise_ga
