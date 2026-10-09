from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.events import in_person_count_service as service
from pecha_api.events.in_person_count_response_models import (
    CreateInPersonCountRequest,
    InPersonCountDTO,
    InPersonCountsResponse,
    UpdateInPersonCountRequest,
)

_SVC = "pecha_api.events.in_person_count_service"
_VIEWS = "pecha_api.events.in_person_count_views"
_AUTH = {"Authorization": "Bearer dummy"}
IN_PERSON = UUID("7cafd4eb-d996-437f-83f7-d9359c7ef40f")

client = TestClient(api)


def _event(group_accumulator_id="default", tz="Asia/Kolkata"):
    return SimpleNamespace(
        id=uuid4(),
        group_id=uuid4(),
        group_accumulator_id=uuid4() if group_accumulator_id == "default" else group_accumulator_id,
        timezone=tz,
    )


def _row(count=108, created_at=datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc), group_accumulator_id=None):
    return SimpleNamespace(
        id=uuid4(),
        group_accumulator_id=group_accumulator_id or uuid4(),
        count=count,
        created_at=created_at,
        updated_at=None,
    )


def _legacy_resolve_target(_db, event, event_accumulation_id=None):
    if event.group_accumulator_id is None:
        raise HTTPException(status_code=409, detail="EVENT_HAS_NO_GROUP_ACCUMULATOR")
    return None, event.group_accumulator_id


@pytest.fixture
def ctx():
    """Patches auth, the session and the event lookup; yields the event."""
    event = _event()
    with patch(f"{_SVC}.validate_cms_author_details"), patch(f"{_SVC}.SessionLocal"), patch(
        f"{_SVC}._require_can_edit_event"
    ) as mock_perm, patch(f"{_SVC}.get_event_by_id", return_value=event), patch(
        f"{_SVC}.resolve_manual_in_person_target", side_effect=_legacy_resolve_target
    ):
        yield SimpleNamespace(event=event, perm=mock_perm)


def test_in_person_user_id_comes_from_config():
    assert service.in_person_user_id() == IN_PERSON


class TestList:
    def test_lists_the_in_person_rows_by_event_day(self, ctx):
        row = _row(created_at=datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc))  # 1 Oct 01:30 IST
        group_accumulator = SimpleNamespace(
            id=uuid4(), metadata_entries=[], title="Om Mani Padme Hum", target_count=100_000_000, image_key="ga/original.jpg"
        )
        with patch(f"{_SVC}.list_in_person_counts", return_value=([row], 7, 5000)) as mock_list, patch(
            f"{_SVC}.get_group_accumulator_by_id", return_value=group_accumulator
        ), patch(f"{_SVC}.get_group_accumulator_total_count", return_value=1_234_567), patch(
            f"{_SVC}.safe_get_image_url", return_value={"thumbnail": "t", "medium": "m", "original": "o"}
        ) as mock_image:
            response = service.list_in_person_counts_service(token="t", event_id=ctx.event.id, skip=20, limit=10)

        kwargs = mock_list.call_args.kwargs
        assert kwargs["user_id"] == IN_PERSON
        assert kwargs["group_accumulator_id"] == ctx.event.group_accumulator_id
        assert (kwargs["skip"], kwargs["limit"]) == (20, 10)
        assert response.items[0].day == date(2026, 10, 1)
        assert (response.total, response.total_count, response.timezone) == (7, 5000, "Asia/Kolkata")
        assert response.group_accumulator_title == "Om Mani Padme Hum"
        assert response.group_accumulator_total_count == 1_234_567
        assert response.group_accumulator_target_count == 100_000_000
        assert response.group_accumulator_image.medium == "m"
        assert mock_image.call_args.args[0] == "ga/original.jpg"
        ctx.perm.assert_called_once()

    def test_event_without_group_accumulator_is_409(self, ctx):
        ctx.event.group_accumulator_id = None
        with patch(f"{_SVC}.list_in_person_counts") as mock_list, pytest.raises(HTTPException) as exc:
            service.list_in_person_counts_service(token="t", event_id=ctx.event.id, skip=0, limit=20)
        mock_list.assert_not_called()
        assert exc.value.status_code == 409

    def test_missing_event_is_404(self):
        with patch(f"{_SVC}.validate_cms_author_details"), patch(f"{_SVC}.SessionLocal"), patch(
            f"{_SVC}.get_event_by_id", return_value=None
        ), pytest.raises(HTTPException) as exc:
            service.list_in_person_counts_service(token="t", event_id=uuid4(), skip=0, limit=20)
        assert exc.value.status_code == 404


class TestCreate:
    def test_records_at_midday_of_the_event_day(self, ctx):
        with patch(f"{_SVC}.user_exists", return_value=True), patch(
            f"{_SVC}.find_in_person_count_in_range", return_value=None
        ) as mock_find, patch(
            f"{_SVC}.add_in_person_count", side_effect=lambda db, **kw: _row(count=kw["count"], created_at=kw["created_at"])
        ) as mock_add:
            dto = service.create_in_person_count_service(
                token="t", event_id=ctx.event.id, request=CreateInPersonCountRequest(day=date(2026, 10, 1), count=1080)
            )

        add = mock_add.call_args.kwargs
        assert add["user_id"] == IN_PERSON
        assert add["group_accumulator_id"] == ctx.event.group_accumulator_id
        assert add["created_at"] == datetime(2026, 10, 1, 6, 30, tzinfo=timezone.utc)
        find = mock_find.call_args.kwargs
        assert find["start_utc"] == datetime(2026, 9, 30, 18, 30, tzinfo=timezone.utc)
        assert (dto.day, dto.count) == (date(2026, 10, 1), 1080)

    def test_one_count_per_day(self, ctx):
        with patch(f"{_SVC}.user_exists", return_value=True), patch(
            f"{_SVC}.find_in_person_count_in_range", return_value=_row()
        ), patch(f"{_SVC}.add_in_person_count") as mock_add, pytest.raises(HTTPException) as exc:
            service.create_in_person_count_service(
                token="t", event_id=ctx.event.id, request=CreateInPersonCountRequest(day=date(2026, 10, 1), count=1)
            )
        assert (exc.value.status_code, exc.value.detail) == (409, service.IN_PERSON_COUNT_EXISTS)
        mock_add.assert_not_called()

    def test_needs_a_linked_group_accumulator(self, ctx):
        ctx.event.group_accumulator_id = None
        with pytest.raises(HTTPException) as exc:
            service.create_in_person_count_service(
                token="t", event_id=ctx.event.id, request=CreateInPersonCountRequest(day=date(2026, 10, 1), count=1)
            )
        assert exc.value.detail == "EVENT_HAS_NO_GROUP_ACCUMULATOR"

    def test_missing_in_person_user(self, ctx):
        with patch(f"{_SVC}.user_exists", return_value=False), pytest.raises(HTTPException) as exc:
            service.create_in_person_count_service(
                token="t", event_id=ctx.event.id, request=CreateInPersonCountRequest(day=date(2026, 10, 1), count=1)
            )
        assert exc.value.detail == service.IN_PERSON_USER_NOT_FOUND


class TestUpdateDelete:
    def test_updates_count_and_moves_day(self, ctx):
        row = _row()
        with patch(f"{_SVC}.get_in_person_count", return_value=row) as mock_get, patch(
            f"{_SVC}.find_in_person_count_in_range", return_value=None
        ) as mock_find, patch(f"{_SVC}.save_in_person_count", side_effect=lambda db, r: r):
            dto = service.update_in_person_count_service(
                token="t",
                event_id=ctx.event.id,
                history_id=row.id,
                request=UpdateInPersonCountRequest(count=500, day=date(2026, 10, 2)),
            )
        assert mock_get.call_args.kwargs["user_id"] == IN_PERSON
        assert mock_find.call_args.kwargs["exclude_id"] == row.id
        assert (dto.count, dto.day) == (500, date(2026, 10, 2))

    def test_same_day_skips_the_clash_check(self, ctx):
        row = _row()
        with patch(f"{_SVC}.get_in_person_count", return_value=row), patch(
            f"{_SVC}.find_in_person_count_in_range"
        ) as mock_find, patch(f"{_SVC}.save_in_person_count", side_effect=lambda db, r: r):
            service.update_in_person_count_service(
                token="t",
                event_id=ctx.event.id,
                history_id=row.id,
                request=UpdateInPersonCountRequest(count=5, day=date(2026, 10, 1)),
            )
        mock_find.assert_not_called()
        assert row.count == 5

    def test_unknown_row_is_404(self, ctx):
        with patch(f"{_SVC}.get_in_person_count", return_value=None), pytest.raises(HTTPException) as exc:
            service.delete_in_person_count_service(token="t", event_id=ctx.event.id, history_id=uuid4())
        assert exc.value.status_code == 404

    def test_deletes(self, ctx):
        row = _row()
        with patch(f"{_SVC}.get_in_person_count", return_value=row), patch(
            f"{_SVC}.delete_in_person_count"
        ) as mock_delete:
            service.delete_in_person_count_service(token="t", event_id=ctx.event.id, history_id=row.id)
        assert mock_delete.call_args.args[1] is row


class TestViews:
    def test_list(self):
        event_id = uuid4()
        body = InPersonCountsResponse(items=[], total=0, skip=0, limit=20, total_count=0, timezone="UTC")
        with patch(f"{_VIEWS}.list_in_person_counts_service", return_value=body) as mock_list:
            response = client.get(f"/cms/events/{event_id}/in-person-counts", headers=_AUTH)
        assert response.status_code == 200
        mock_list.assert_called_once_with(
            token="dummy",
            event_id=event_id,
            skip=0,
            limit=20,
            event_accumulation_id=None,
        )

    def test_create_validates_count(self):
        event_id = uuid4()
        for body in ({"day": "2026-10-01", "count": 0}, {"day": "someday", "count": 5}, {"count": 5}):
            response = client.post(f"/cms/events/{event_id}/in-person-counts", headers=_AUTH, json=body)
            assert response.status_code == 422, body

    def test_create_update_delete(self):
        event_id, history_id = uuid4(), uuid4()
        dto = InPersonCountDTO(id=history_id, day=date(2026, 10, 1), count=9, created_at=datetime.now(timezone.utc))
        with patch(f"{_VIEWS}.create_in_person_count_service", return_value=dto):
            assert client.post(
                f"/cms/events/{event_id}/in-person-counts", headers=_AUTH, json={"day": "2026-10-01", "count": 9}
            ).status_code == 201
        with patch(f"{_VIEWS}.update_in_person_count_service", return_value=dto) as mock_put:
            assert client.put(
                f"/cms/events/{event_id}/in-person-counts/{history_id}", headers=_AUTH, json={"count": 9}
            ).status_code == 200
        assert mock_put.call_args.kwargs["request"].day is None
        with patch(f"{_VIEWS}.delete_in_person_count_service") as mock_delete:
            assert client.delete(f"/cms/events/{event_id}/in-person-counts/{history_id}", headers=_AUTH).status_code == 204
        mock_delete.assert_called_once_with(
            token="dummy",
            event_id=event_id,
            history_id=history_id,
            event_accumulation_id=None,
        )

    def test_requires_auth(self):
        assert client.get(f"/cms/events/{uuid4()}/in-person-counts").status_code == 403
