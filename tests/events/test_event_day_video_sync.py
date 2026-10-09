from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Dict, Iterable, List, Optional
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi import HTTPException

from pecha_api.events.event_day_video_sync import (
    sync_event_youtube_to_plan_day,
    youtube_video_keys_of_event,
)
from pecha_api.plans.videos.day_video_models import DayVideo

MODULE = "pecha_api.events.event_day_video_sync"
VIDEO_A = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
VIDEO_A_SHORT = "https://youtu.be/AAAAAAAAAAA"
VIDEO_B = "https://www.youtube.com/watch?v=BBBBBBBBBBB"
VIDEO_C = "https://www.youtube.com/watch?v=CCCCCCCCCCC"
GROUP_ID = uuid4()
AUTHOR = SimpleNamespace(id=uuid4(), email="author@x.com")


def _link(url: str, language: str = "EN", type_: str = "youtube") -> SimpleNamespace:
    return SimpleNamespace(type=type_, url=url, label=None, language=language)


def _plan(
    language: str,
    days_since_start: Optional[int] = None,
    group_id: UUID = GROUP_ID,
) -> SimpleNamespace:
    start = (
        None
        if days_since_start is None
        else datetime.now(timezone.utc) - timedelta(days=days_since_start)
    )
    return SimpleNamespace(
        id=uuid4(), language=language, group_id=group_id, status="DRAFT", start_date=start
    )


def _event(
    links: List[SimpleNamespace],
    days_since_start: int = 2,
    series_id: Optional[UUID] = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        plan_id=uuid4(),
        series_id=series_id,
        group_id=GROUP_ID,
        timezone="UTC",
        start_date=datetime.now(timezone.utc) - timedelta(days=days_since_start),
        links=links,
    )


def _db(
    plans: List[SimpleNamespace],
    day_by_plan_id: Optional[Dict[UUID, SimpleNamespace]] = None,
) -> MagicMock:
    """db.query(Plan) returns the linked plans, db.query(PlanItem) the plan day."""
    db = MagicMock()
    plan_query = MagicMock()
    plan_query.filter.return_value.all.return_value = plans
    day_query = MagicMock()
    days = day_by_plan_id or {}
    day_query.filter.side_effect = lambda plan_cond, _day: SimpleNamespace(
        with_for_update=lambda: SimpleNamespace(first=lambda: days.get(plan_cond.right.value))
    )
    db.query.side_effect = lambda model: plan_query if model.__name__ == "Plan" else day_query
    db.plan_query = plan_query
    db.day_query = day_query
    return db


def _added_videos(db: MagicMock) -> List[DayVideo]:
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], DayVideo)]


def _run(
    db: MagicMock,
    event: SimpleNamespace,
    previous: Iterable = frozenset(),
    existing: Iterable = (),
    can_edit: bool = True,
) -> MagicMock:
    def _permission(**_kwargs: object) -> None:
        if not can_edit:
            raise HTTPException(status_code=403, detail="NO_GROUP_MEMBERSHIP")

    with patch(f"{MODULE}.get_day_videos_by_day_id", return_value=list(existing)), patch(
        f"{MODULE}.get_next_display_order", return_value=0
    ), patch(f"{MODULE}.require_can_edit_content", side_effect=_permission), patch(
        f"{MODULE}.schedule_invalidate_plan_day_cache"
    ) as invalidate:
        sync_event_youtube_to_plan_day(db, event, previous, AUTHOR)
    return invalidate


def test_youtube_video_keys_of_event_pairs_video_and_language() -> None:
    event = _event([_link(VIDEO_A, "en"), _link("https://example.com", type_="website")])
    assert youtube_video_keys_of_event(event) == {("AAAAAAAAAAA", "EN")}


def test_video_is_added_to_todays_day_of_same_language_plan() -> None:
    plan = _plan("EN")
    day = SimpleNamespace(id=uuid4())
    db = _db([plan], {plan.id: day})

    _run(db, _event([_link(VIDEO_A, "EN")], days_since_start=2))

    (video,) = _added_videos(db)
    assert video.day_id == day.id
    assert video.video_id == "AAAAAAAAAAA"
    assert video.created_by == AUTHOR.email
    db.commit.assert_called_once()


def test_added_video_stores_youtube_duration() -> None:
    plan = _plan("EN")
    day = SimpleNamespace(id=uuid4())
    db = _db([plan], {plan.id: day})

    with patch(f"{MODULE}.durations_for_video_ids", return_value={"AAAAAAAAAAA": 253}):
        _run(db, _event([_link(VIDEO_A, "EN")], days_since_start=2))

    assert _added_videos(db)[0].duration_seconds == 253


def test_video_is_added_when_youtube_duration_lookup_fails() -> None:
    plan = _plan("EN")
    day = SimpleNamespace(id=uuid4())
    db = _db([plan], {plan.id: day})

    with patch(f"{MODULE}.durations_for_video_ids", side_effect=RuntimeError("youtube down")):
        _run(db, _event([_link(VIDEO_A, "EN")], days_since_start=2))

    (video,) = _added_videos(db)
    assert video.video_id == "AAAAAAAAAAA"
    assert video.duration_seconds is None
    db.commit.assert_called_once()


def test_day_number_falls_back_to_event_start_when_plan_has_none() -> None:
    plan = _plan("EN")
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})

    _run(db, _event([_link(VIDEO_A)], days_since_start=4))

    # Started four days ago, so today is day 5.
    assert db.day_query.filter.call_args.args[1].right.value == 5


def test_day_number_counts_from_the_plans_own_start_date() -> None:
    plan = _plan("EN", days_since_start=9)
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})

    # The event started two days ago, but the plan's day 1 was nine days ago.
    _run(db, _event([_link(VIDEO_A)], days_since_start=2))

    assert db.day_query.filter.call_args.args[1].right.value == 10


def test_plans_are_limited_to_the_events_group() -> None:
    db = _db([])
    event = _event([_link(VIDEO_A)])

    _run(db, event)

    conditions = [str(c) for c in db.plan_query.filter.call_args.args]
    assert "plans.group_id = :group_id_1" in conditions


def test_plan_the_author_cannot_edit_is_skipped() -> None:
    plan = _plan("EN")
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})

    _run(db, _event([_link(VIDEO_A)]), can_edit=False)

    assert _added_videos(db) == []
    db.commit.assert_not_called()


def test_plan_day_is_locked_before_reading_its_videos() -> None:
    plan = _plan("EN")
    db = _db([plan])
    lock = MagicMock()
    lock.return_value.first.return_value = None
    db.day_query.filter.side_effect = lambda *_: SimpleNamespace(with_for_update=lock)

    _run(db, _event([_link(VIDEO_A)]))

    lock.assert_called_once()


def test_changed_plan_day_cache_is_invalidated() -> None:
    plan = _plan("EN")
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})

    invalidate = _run(db, _event([_link(VIDEO_A)], days_since_start=4))

    invalidate.assert_called_once_with(plan_id=plan.id, day_number=5)


def test_video_in_other_language_is_not_added() -> None:
    plan = _plan("EN")
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})

    invalidate = _run(db, _event([_link(VIDEO_A, "BO"), _link(VIDEO_B, "ZH")]))

    assert _added_videos(db) == []
    db.commit.assert_not_called()
    invalidate.assert_not_called()


def test_each_language_goes_to_its_own_series_plan() -> None:
    en, bo = _plan("EN"), _plan("BO")
    en_day, bo_day = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    db = _db([en, bo], {en.id: en_day, bo.id: bo_day})
    event = _event(
        [_link(VIDEO_A, "EN"), _link(VIDEO_B, "BO"), _link(VIDEO_C, "ZH")],
        series_id=uuid4(),
    )

    _run(db, event)

    added = {(v.day_id, v.video_id) for v in _added_videos(db)}
    assert added == {(en_day.id, "AAAAAAAAAAA"), (bo_day.id, "BBBBBBBBBBB")}


def test_video_already_on_the_day_is_skipped() -> None:
    plan = _plan("EN")
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})
    existing = SimpleNamespace(video_id="AAAAAAAAAAA", url=VIDEO_A)

    _run(db, _event([_link(VIDEO_A_SHORT, "EN")]), existing=[existing])

    assert _added_videos(db) == []
    db.commit.assert_not_called()


def test_links_the_event_already_had_are_not_resynced() -> None:
    db = _db([_plan("EN")])

    _run(db, _event([_link(VIDEO_A, "EN")]), previous={("AAAAAAAAAAA", "EN")})

    db.query.assert_not_called()


def test_missing_day_does_nothing() -> None:
    db = _db([_plan("EN")], {})
    _run(db, _event([_link(VIDEO_A, "EN")]))
    db.add.assert_not_called()


def test_event_without_linked_plan_does_nothing() -> None:
    event = _event([_link(VIDEO_A)])
    event.plan_id = None
    db = MagicMock()
    _run(db, event)
    db.add.assert_not_called()


def test_transient_failure_is_retried() -> None:
    plan = _plan("EN")
    day = SimpleNamespace(id=uuid4())
    db = _db([plan], {plan.id: day})
    working_query = db.query.side_effect
    calls = {"count": 0}

    def _flaky(model: type) -> MagicMock:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("lock timeout")
        return working_query(model)

    db.query.side_effect = _flaky

    _run(db, _event([_link(VIDEO_A)]))

    db.rollback.assert_called_once()
    (video,) = _added_videos(db)
    assert video.day_id == day.id
    db.commit.assert_called_once()


def test_failure_is_rolled_back_and_not_raised() -> None:
    db = MagicMock()
    db.query.side_effect = RuntimeError("db down")

    invalidate = _run(db, _event([_link(VIDEO_A)]))

    assert db.rollback.call_count == 2
    invalidate.assert_not_called()


def test_plan_start_date_is_read_in_the_events_timezone() -> None:
    from pecha_api.events.event_day_video_sync import _plan_start_date

    # 20:00 UTC on 1 Oct is already 2 Oct in Asia/Kolkata (+05:30), the same
    # calendar the event's "today" is read in.
    plan = SimpleNamespace(start_date=datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc))
    event = SimpleNamespace(timezone="Asia/Kolkata", start_date=None)

    assert _plan_start_date(event, plan).isoformat() == "2026-10-02"
