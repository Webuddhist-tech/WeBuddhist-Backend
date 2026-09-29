from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

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


def _link(url, language="EN", type_="youtube"):
    return SimpleNamespace(type=type_, url=url, label=None, language=language)


def _plan(language):
    return SimpleNamespace(id=uuid4(), language=language)


def _event(links, days_since_start=2, series_id=None):
    return SimpleNamespace(
        id=uuid4(),
        plan_id=uuid4(),
        series_id=series_id,
        timezone="UTC",
        start_date=datetime.now(timezone.utc) - timedelta(days=days_since_start),
        links=links,
    )


def _db(plans, day_by_plan_id=None):
    """First db.query(...) returns the linked plans, later ones the plan day."""
    db = MagicMock()
    plan_query = MagicMock()
    plan_query.filter.return_value.all.return_value = plans
    day_query = MagicMock()
    days = day_by_plan_id or {}
    day_query.filter.side_effect = lambda plan_cond, _day: SimpleNamespace(
        first=lambda: days.get(plan_cond.right.value)
    )
    db.query.side_effect = lambda model: plan_query if model.__name__ == "Plan" else day_query
    db.day_query = day_query
    return db


def _added_videos(db):
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], DayVideo)]


def _run(db, event, previous=frozenset(), existing=()):
    with patch(f"{MODULE}.get_day_videos_by_day_id", return_value=list(existing)), patch(
        f"{MODULE}.get_next_display_order", return_value=0
    ):
        sync_event_youtube_to_plan_day(db, event, previous, "author@x.com")


def test_youtube_video_keys_of_event_pairs_video_and_language():
    event = _event([_link(VIDEO_A, "en"), _link("https://example.com", type_="website")])
    assert youtube_video_keys_of_event(event) == {("AAAAAAAAAAA", "EN")}


def test_video_is_added_to_todays_day_of_same_language_plan():
    plan = _plan("EN")
    day = SimpleNamespace(id=uuid4())
    db = _db([plan], {plan.id: day})

    _run(db, _event([_link(VIDEO_A, "EN")], days_since_start=2))

    (video,) = _added_videos(db)
    assert video.day_id == day.id
    assert video.video_id == "AAAAAAAAAAA"
    db.commit.assert_called_once()


def test_todays_day_number_counts_from_event_start():
    plan = _plan("EN")
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})

    _run(db, _event([_link(VIDEO_A)], days_since_start=4))

    # Started four days ago, so today is day 5.
    assert db.day_query.filter.call_args.args[1].right.value == 5


def test_video_in_other_language_is_not_added():
    plan = _plan("EN")
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})

    _run(db, _event([_link(VIDEO_A, "BO"), _link(VIDEO_B, "ZH")]))

    assert _added_videos(db) == []
    db.commit.assert_not_called()


def test_each_language_goes_to_its_own_series_plan():
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


def test_video_already_on_the_day_is_skipped():
    plan = _plan("EN")
    db = _db([plan], {plan.id: SimpleNamespace(id=uuid4())})
    existing = SimpleNamespace(video_id="AAAAAAAAAAA", url=VIDEO_A)

    _run(db, _event([_link(VIDEO_A_SHORT, "EN")]), existing=[existing])

    assert _added_videos(db) == []
    db.commit.assert_not_called()


def test_links_the_event_already_had_are_not_resynced():
    db = _db([_plan("EN")])

    _run(db, _event([_link(VIDEO_A, "EN")]), previous={("AAAAAAAAAAA", "EN")})

    db.query.assert_not_called()


def test_missing_day_does_nothing():
    db = _db([_plan("EN")], {})
    _run(db, _event([_link(VIDEO_A, "EN")]))
    db.add.assert_not_called()


def test_event_without_linked_plan_does_nothing():
    event = _event([_link(VIDEO_A)])
    event.plan_id = None
    db = MagicMock()
    _run(db, event)
    db.add.assert_not_called()


def test_failure_is_rolled_back_and_not_raised():
    db = MagicMock()
    db.query.side_effect = RuntimeError("db down")

    _run(db, _event([_link(VIDEO_A)]))

    db.rollback.assert_called_once()
