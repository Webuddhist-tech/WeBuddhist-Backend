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
from pecha_api.events.event_service import (
    _accumulation_links_for_dto,
    _accumulation_links_to_dtos,
)
from pecha_api.events.group_event_accumulation_repository import (
    EventAccumulationSyncInput,
    resolve_primary_group_accumulator_id,
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


def test_sync_reassign_and_readd_accumulator_uses_separate_rows():
    """Moving link A off X then re-adding X must not reuse A for both inputs."""
    event_id = uuid4()
    group_id = uuid4()
    link_a_id = uuid4()
    ga_x = uuid4()
    ga_y = uuid4()
    existing_a = MagicMock(
        id=link_a_id,
        event_id=event_id,
        group_accumulator_id=ga_x,
        parent_id=None,
        event_format="hybrid",
        display_order=1,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.side_effect = [
        [existing_a],
        [existing_a],
    ]
    ga = MagicMock(group_id=group_id, deleted_at=None)
    db.query.return_value.filter.return_value.first.return_value = ga

    added_rows = []

    def capture_add(row):
        added_rows.append(row)

    db.add.side_effect = capture_add

    sync_event_accumulations(
        db,
        event_id=event_id,
        group_id=group_id,
        inputs=[
            EventAccumulationSyncInput(
                id=link_a_id,
                group_accumulator_id=ga_y,
            ),
            EventAccumulationSyncInput(
                group_accumulator_id=ga_x,
            ),
        ],
    )

    assert len(added_rows) == 1
    assert added_rows[0].group_accumulator_id == ga_x
    assert existing_a.group_accumulator_id == ga_y


def test_sync_swaps_accumulators_in_one_statement():
    event_id = uuid4()
    group_id = uuid4()
    link_a_id = uuid4()
    link_b_id = uuid4()
    ga_x = uuid4()
    ga_y = uuid4()
    existing_a = MagicMock(
        id=link_a_id,
        event_id=event_id,
        group_accumulator_id=ga_x,
        parent_id=None,
        event_format="hybrid",
        display_order=1,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    existing_b = MagicMock(
        id=link_b_id,
        event_id=event_id,
        group_accumulator_id=ga_y,
        parent_id=None,
        event_format="hybrid",
        display_order=2,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.side_effect = [
        [existing_a, existing_b],
        [existing_a, existing_b],
    ]
    ga = MagicMock(group_id=group_id, deleted_at=None)
    db.query.return_value.filter.return_value.first.return_value = ga

    sync_event_accumulations(
        db,
        event_id=event_id,
        group_id=group_id,
        inputs=[
            EventAccumulationSyncInput(
                id=link_a_id,
                group_accumulator_id=ga_y,
                display_order=1,
            ),
            EventAccumulationSyncInput(
                id=link_b_id,
                group_accumulator_id=ga_x,
                display_order=2,
            ),
        ],
    )

    db.execute.assert_called_once()
    update_params = db.execute.call_args[0][1]
    assert update_params["id_0"] == link_a_id
    assert update_params["ga_0"] == ga_y
    assert update_params["id_1"] == link_b_id
    assert update_params["ga_1"] == ga_x
    assert existing_a.group_accumulator_id == ga_y
    assert existing_b.group_accumulator_id == ga_x


def test_sync_replaces_link_before_flushing_accumulator_change():
    """Omitted links must be removed before retargeting a retained link."""
    event_id = uuid4()
    group_id = uuid4()
    link_a_id = uuid4()
    link_b_id = uuid4()
    ga_x = uuid4()
    ga_y = uuid4()
    existing_a = MagicMock(
        id=link_a_id,
        event_id=event_id,
        group_accumulator_id=ga_x,
        parent_id=None,
        event_format="hybrid",
        display_order=1,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    existing_b = MagicMock(
        id=link_b_id,
        event_id=event_id,
        group_accumulator_id=ga_y,
        parent_id=None,
        event_format="hybrid",
        display_order=2,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.side_effect = [
        [existing_a, existing_b],
        [existing_a],
    ]
    ga = MagicMock(group_id=group_id, deleted_at=None)
    db.query.return_value.filter.return_value.first.return_value = ga

    sync_event_accumulations(
        db,
        event_id=event_id,
        group_id=group_id,
        inputs=[
            EventAccumulationSyncInput(
                id=link_a_id,
                group_accumulator_id=ga_y,
            ),
        ],
    )

    db.delete.assert_called_once_with(existing_b)
    assert existing_a.group_accumulator_id == ga_y
    call_names = [call[0] for call in db.method_calls]
    delete_index = call_names.index("delete")
    first_flush_index = call_names.index("flush")
    assert delete_index < first_flush_index


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


def test_accumulation_links_for_dto_ignores_non_event_objects():
    assert _accumulation_links_for_dto(MagicMock()) == []


def test_resolve_primary_prefers_manual_in_person_link():
    manual_ga = uuid4()
    offline_ga = uuid4()
    manual = _link(
        link_id=uuid4(),
        group_accumulator_id=manual_ga,
        count_mode=EventAccumulationCountMode.MANUAL_IN_PERSON.value,
        display_order=2,
    )
    offline = _link(
        link_id=uuid4(),
        group_accumulator_id=offline_ga,
        count_mode=EventAccumulationCountMode.OFFLINE_PARTICIPANTS.value,
        display_order=1,
    )
    assert resolve_primary_group_accumulator_id([offline, manual]) == manual_ga


def test_sync_rejects_duplicate_group_accumulator_in_request():
    event_id = uuid4()
    group_id = uuid4()
    ga_id = uuid4()
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    ga = MagicMock(group_id=group_id, deleted_at=None)
    db.query.return_value.filter.return_value.first.return_value = ga

    with pytest.raises(HTTPException) as exc:
        sync_event_accumulations(
            db,
            event_id=event_id,
            group_id=group_id,
            inputs=[
                EventAccumulationSyncInput(group_accumulator_id=ga_id),
                EventAccumulationSyncInput(group_accumulator_id=ga_id),
            ],
        )
    assert exc.value.detail == "Duplicate group_accumulator_id in request"


def test_sync_clears_all_links_when_payload_empty():
    event_id = uuid4()
    existing = MagicMock(id=uuid4())
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        existing
    ]

    result = sync_event_accumulations(
        db, event_id=event_id, group_id=uuid4(), inputs=[]
    )

    assert result == []
    db.delete.assert_called_once_with(existing)
    db.flush.assert_called()
