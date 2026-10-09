from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pecha_api.events.youtube_live_sync_response_models import (
    RunYoutubeLiveSyncRequest,
    UpdateYoutubeLiveSyncRequest,
)
from pecha_api.events.youtube_live_sync_service import (
    SyncOutcome,
    due_slot,
    latest_slot_at_or_before,
    run_due_youtube_live_syncs,
    sync_group_live_streams,
)
from pecha_api.external_clients.gemini_client import parse_live_stream_languages_payload
from pecha_api.external_clients.youtube_channel_client import (
    YoutubeChannelError,
    YoutubeLiveVideo,
    find_group_channel_url,
    parse_channel_url,
)
from pecha_api.plans.plans_enums import LanguageCode

MODULE = "pecha_api.events.youtube_live_sync_service"
IST = "Asia/Kolkata"
GROUP_ID = uuid4()


def _utc(hour: int, minute: int = 0, day: int = 9) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc)


# 08:30 in Kolkata
NOW_UTC = _utc(3, 0)


# ----------------------------------------------------------------- schedule


def test_slot_is_found_in_the_group_timezone():
    # 08:30 IST is 03:00 UTC and 14:00 IST is 08:30 UTC.
    assert latest_slot_at_or_before(["08:30", "14:00"], IST, _utc(3, 4)) == _utc(3, 0)
    assert latest_slot_at_or_before(["08:30", "14:00"], IST, _utc(9, 0)) == _utc(8, 30)


def test_slot_from_yesterday_is_found_just_after_midnight():
    slot = latest_slot_at_or_before(["23:50"], "UTC", _utc(0, 5, day=10))
    assert slot == _utc(23, 50, day=9)


def test_no_times_means_no_slot():
    assert latest_slot_at_or_before([], "UTC", NOW_UTC) is None


def test_due_slot_runs_each_time_once():
    times = ["08:30", "14:00"]
    first = due_slot(times, IST, _utc(3, 1), None, grace_seconds=600)
    assert first == _utc(3, 0)
    # The same time is not due again once claimed.
    assert due_slot(times, IST, _utc(3, 2), first, grace_seconds=600) is None
    # 14:00 IST (08:30 UTC) is a separate run.
    second = due_slot(times, IST, _utc(8, 31), first, grace_seconds=600)
    assert second == _utc(8, 30)


def test_missed_time_beyond_grace_is_skipped():
    assert due_slot(["08:30"], IST, _utc(3, 11), None, grace_seconds=600) is None
    assert due_slot(["08:30"], IST, _utc(3, 10), None, grace_seconds=600) == _utc(3, 0)


def test_unreadable_stored_time_is_ignored():
    assert due_slot(["bogus", "08:30"], IST, _utc(3, 1), None, grace_seconds=600) == _utc(3, 0)


def test_naive_last_slot_is_read_as_utc():
    naive = datetime(2026, 10, 9, 3, 0)
    assert due_slot(["08:30"], IST, _utc(3, 1), naive, grace_seconds=600) is None


# ------------------------------------------------------------ request model

EVENT_A, EVENT_B = uuid4(), uuid4()


def test_request_normalizes_sorts_and_dedupes_times():
    request = UpdateYoutubeLiveSyncRequest(
        event_ids=[EVENT_A], run_times=["14:00", "8:30", "08:30"], timezone=" Asia/Kolkata "
    )
    assert request.run_times == ["08:30", "14:00"]
    assert request.timezone == "Asia/Kolkata"


@pytest.mark.parametrize("bad", ["25:00", "8", "08:60", "ab:cd", "8:30pm"])
def test_request_rejects_bad_times(bad):
    with pytest.raises(ValidationError):
        UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_A], run_times=[bad])


def test_request_rejects_unknown_timezone():
    with pytest.raises(ValidationError):
        UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_A], run_times=["08:30"], timezone="Mars/Olympus")


def test_request_must_name_events():
    with pytest.raises(ValidationError):
        UpdateYoutubeLiveSyncRequest(event_ids=[], run_times=["08:30"])
    with pytest.raises(ValidationError):
        RunYoutubeLiveSyncRequest(event_ids=[])


def test_request_dedupes_event_ids_keeping_order():
    request = UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_B, EVENT_A, EVENT_B], run_times=["08:30"])
    assert request.event_ids == [EVENT_B, EVENT_A]


def test_enabled_schedule_needs_a_time_but_a_disabled_one_may_have_none():
    with pytest.raises(ValidationError):
        UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_A], enabled=True, run_times=[])
    assert UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_A], enabled=False, run_times=[]).run_times == []


# ------------------------------------------------------------ channel urls


@pytest.mark.parametrize(
    "url, kind, value",
    [
        ("https://www.youtube.com/@group", "handle", "@group"),
        ("youtube.com/channel/UCabc123", "id", "UCabc123"),
        ("https://www.youtube.com/user/oldname", "username", "oldname"),
        ("https://www.youtube.com/c/Custom", "custom", "Custom"),
        ("https://www.youtube.com/CustomName", "custom", "CustomName"),
    ],
)
def test_parse_channel_url(url, kind, value):
    ref = parse_channel_url(url)
    assert (ref.kind, ref.value) == (kind, value)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=AAAAAAAAAAA",
        "https://youtu.be/AAAAAAAAAAA",
        "https://example.com/@x",
        "",
        "https://www.youtube.com/playlist?list=PL1",
    ],
)
def test_parse_channel_url_rejects_non_channels(url):
    assert parse_channel_url(url) is None


def test_find_group_channel_url_skips_video_links_and_other_platforms():
    links = [
        SimpleNamespace(platform="Facebook", url="https://facebook.com/x"),
        SimpleNamespace(platform="youtube", url="https://www.youtube.com/watch?v=AAAAAAAAAAA"),
        SimpleNamespace(platform="YouTube", url="https://www.youtube.com/@group"),
    ]
    assert find_group_channel_url(links) == "https://www.youtube.com/@group"
    assert find_group_channel_url([]) is None


# --------------------------------------------------------- language payload


def test_language_payload_keeps_only_asked_ids_and_supported_codes():
    payload = {"languages": {"a": "bo", "b": "FR", "c": None, "z": "EN"}}
    assert parse_live_stream_languages_payload(payload, ["a", "b", "c"]) == {"a": LanguageCode.BO}


def test_language_payload_garbage_is_empty():
    assert parse_live_stream_languages_payload(["x"], ["a"]) == {}
    assert parse_live_stream_languages_payload({"languages": "x"}, ["a"]) == {}


# --------------------------------------------------------------------- sync


def _video(video_id: str, status: str = "live", title: str = "Teaching") -> YoutubeLiveVideo:
    return YoutubeLiveVideo(
        id=video_id, title=title, url=f"https://www.youtube.com/watch?v={video_id}", status=status
    )


def _event(*youtube_ids: str) -> SimpleNamespace:
    links = [
        SimpleNamespace(
            type="youtube",
            url=f"https://www.youtube.com/watch?v={video_id}",
            display_order=n + 1,
            language="EN",
        )
        for n, video_id in enumerate(youtube_ids)
    ]
    return SimpleNamespace(id=uuid4(), created_by="a@x.com", links=links)


def _run(videos, events, languages, *, author=None):
    db = MagicMock()
    with patch(f"{MODULE}._group_channel_url", return_value="https://www.youtube.com/@g"), patch(
        f"{MODULE}.fetch_channel_live_videos", return_value=videos
    ), patch(f"{MODULE}._chosen_events", return_value=events), patch(
        f"{MODULE}.suggest_live_stream_languages", return_value=languages
    ) as suggest, patch(
        f"{MODULE}.find_author_by_email", return_value=author
    ), patch(f"{MODULE}.sync_event_youtube_to_plan_day") as plan_sync, patch(
        f"{MODULE}.schedule_invalidate_event_detail_caches"
    ) as invalidate:
        outcome = sync_group_live_streams(db, GROUP_ID, [e.id for e in events], now=NOW_UTC)
    return outcome, db, suggest, plan_sync, invalidate


def test_live_stream_is_added_to_a_running_event_in_the_suggested_language():
    event = _event()
    outcome, db, suggest, _, invalidate = _run(
        [_video("AAAAAAAAAAA", title="Lama's teaching")], [event], {"AAAAAAAAAAA": LanguageCode.BO}
    )
    assert outcome == SyncOutcome(live_streams_found=1, events_checked=1, links_added=1)
    link = db.add.call_args.args[0]
    assert link.event_id == event.id
    assert link.type == "youtube"
    assert link.url == "https://www.youtube.com/watch?v=AAAAAAAAAAA"
    assert link.label == "Lama's teaching"
    assert link.language == LanguageCode.BO
    assert link.display_order == 1
    db.commit.assert_called_once()
    invalidate.assert_called_once_with(event.id)
    assert suggest.call_args.args[0] == {"AAAAAAAAAAA": "Lama's teaching"}


def test_stream_already_on_the_event_is_not_added_or_sent_to_the_llm():
    event = _event("AAAAAAAAAAA")
    outcome, db, suggest, _, _ = _run([_video("AAAAAAAAAAA")], [event], {})
    assert outcome.links_added == 0
    db.add.assert_not_called()
    db.commit.assert_not_called()
    suggest.assert_not_called()


def test_only_live_now_streams_are_used():
    outcome, db, _, _, _ = _run(
        [_video("AAAAAAAAAAA", "upcoming"), _video("BBBBBBBBBBB", "completed")], [_event()], {}
    )
    assert outcome == SyncOutcome()
    db.add.assert_not_called()


def test_new_link_goes_after_the_events_existing_youtube_links():
    event = _event("CCCCCCCCCCC", "DDDDDDDDDDD")
    _, db, _, _, _ = _run([_video("AAAAAAAAAAA")], [event], {"AAAAAAAAAAA": LanguageCode.EN})
    assert db.add.call_args.args[0].display_order == 3


def test_stream_with_unclear_language_is_skipped_not_guessed():
    outcome, db, _, _, _ = _run([_video("AAAAAAAAAAA")], [_event()], {})
    assert outcome.links_added == 0
    assert outcome.skipped_unknown_language == 1
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_stream_goes_to_every_chosen_event_missing_it():
    has_it, lacks_it, also_lacks = _event("AAAAAAAAAAA"), _event(), _event()
    outcome, db, suggest, _, _ = _run(
        [_video("AAAAAAAAAAA")], [has_it, lacks_it, also_lacks], {"AAAAAAAAAAA": LanguageCode.EN}
    )
    assert outcome.links_added == 2
    assert {call.args[0].event_id for call in db.add.call_args_list} == {lacks_it.id, also_lacks.id}
    # One LLM call serves all events.
    suggest.assert_called_once()


def test_added_link_is_copied_to_the_plan_day_for_the_events_author():
    author = SimpleNamespace(email="a@x.com")
    _, _, _, plan_sync, _ = _run(
        [_video("AAAAAAAAAAA")], [_event()], {"AAAAAAAAAAA": LanguageCode.EN}, author=author
    )
    plan_sync.assert_called_once()
    assert plan_sync.call_args.kwargs["author"] is author
    assert plan_sync.call_args.kwargs["previous_keys"] == set()


def test_plan_day_copy_is_skipped_when_the_creator_is_not_an_author():
    _, _, _, plan_sync, _ = _run(
        [_video("AAAAAAAAAAA")], [_event()], {"AAAAAAAAAAA": LanguageCode.EN}, author=None
    )
    plan_sync.assert_not_called()


def test_no_live_stream_means_no_event_lookup_and_no_llm():
    with patch(f"{MODULE}._group_channel_url", return_value="https://www.youtube.com/@g"), patch(
        f"{MODULE}.fetch_channel_live_videos", return_value=[_video("AAAAAAAAAAA", "completed")]
    ), patch(f"{MODULE}._chosen_events") as running, patch(
        f"{MODULE}.suggest_live_stream_languages"
    ) as suggest:
        outcome = sync_group_live_streams(MagicMock(), GROUP_ID, [uuid4()], now=NOW_UTC)
    assert outcome == SyncOutcome()
    running.assert_not_called()
    suggest.assert_not_called()


def test_group_without_a_channel_link_is_an_error():
    with patch(f"{MODULE}._group_channel_url", return_value=None):
        with pytest.raises(YoutubeChannelError):
            sync_group_live_streams(MagicMock(), GROUP_ID, [uuid4()], now=NOW_UTC)


# ---------------------------------------------------------------- job entry


def _session_with_schedules(rows):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = rows
    session = MagicMock()
    session.__enter__.return_value = db
    return session


def _run_job(rows, *, now, claim_result=True, run_side_effect=None):
    with patch(f"{MODULE}.SessionLocal", return_value=_session_with_schedules(rows)), patch(
        f"{MODULE}.datetime"
    ) as dt, patch(f"{MODULE}._claim_slot", return_value=claim_result) as claim, patch(
        f"{MODULE}.run_group_sync", side_effect=run_side_effect
    ) as run, patch(f"{MODULE}.config.get_int", return_value=600):
        dt.now.return_value = now
        dt.combine = datetime.combine
        ran = run_due_youtube_live_syncs()
    return ran, claim, run


def _schedule(group_id, event_id, times, last_slot_at=None, tz=IST):
    return (uuid4(), group_id, event_id, times, tz, last_slot_at)


def test_job_runs_only_the_events_whose_time_has_come():
    due_event, later_event = uuid4(), uuid4()
    rows = [
        _schedule(GROUP_ID, due_event, ["08:30"]),
        _schedule(GROUP_ID, later_event, ["14:00"]),
    ]
    ran, claim, run = _run_job(rows, now=_utc(3, 2))
    assert ran == 1
    run.assert_called_once_with(GROUP_ID, [due_event])
    assert claim.call_args.args[2] == _utc(3, 0)


def test_job_does_one_run_per_group_for_all_its_due_events():
    other_group = uuid4()
    e1, e2, e3 = uuid4(), uuid4(), uuid4()
    rows = [
        _schedule(GROUP_ID, e1, ["08:30"]),
        _schedule(GROUP_ID, e2, ["08:30"]),
        _schedule(other_group, e3, ["08:30"]),
    ]
    ran, _, run = _run_job(rows, now=_utc(3, 2))
    assert ran == 3
    assert sorted((call.args[0], tuple(call.args[1])) for call in run.call_args_list) == sorted(
        [(GROUP_ID, (e1, e2)), (other_group, (e3,))]
    )


def test_job_does_nothing_when_nothing_is_scheduled():
    ran, claim, run = _run_job([], now=_utc(3, 2))
    assert ran == 0
    claim.assert_not_called()
    run.assert_not_called()


def test_job_skips_a_schedule_another_instance_already_claimed():
    ran, _, run = _run_job(
        [_schedule(GROUP_ID, uuid4(), ["08:30"])], now=_utc(3, 2), claim_result=False
    )
    assert ran == 0
    run.assert_not_called()


def test_job_does_not_rerun_a_time_that_already_ran():
    rows = [_schedule(GROUP_ID, uuid4(), ["08:30"], last_slot_at=_utc(3, 0))]
    ran, claim, run = _run_job(rows, now=_utc(3, 2))
    assert ran == 0
    claim.assert_not_called()


def test_one_groups_failure_does_not_stop_the_others():
    other_group = uuid4()
    rows = [
        _schedule(GROUP_ID, uuid4(), ["08:30"]),
        _schedule(other_group, uuid4(), ["08:30"]),
    ]
    ran, _, run = _run_job(rows, now=_utc(3, 2), run_side_effect=[RuntimeError("boom"), None])
    assert ran == 2
    assert [call.args[0] for call in run.call_args_list] == [GROUP_ID, other_group]


# ------------------------------------------------------------ CMS settings


def _settings_session(existing=None, events_in_group=None):
    """A session whose schedule query returns `existing` and whose event
    lookup returns `events_in_group` (a list of ids)."""
    from pecha_api.events.youtube_live_sync_model import EventYoutubeLiveSync
    from pecha_api.events.event_model import Event

    db = MagicMock()

    def query(*entities):
        q = MagicMock()
        first = entities[0]
        if first is EventYoutubeLiveSync:
            q.filter.return_value.all.return_value = existing or []
        elif first is Event.id:
            q.filter.return_value.all.return_value = [(i,) for i in (events_in_group or [])]
        return q

    db.query.side_effect = query
    session = MagicMock()
    session.__enter__.return_value = db
    return session, db


def test_update_rejects_an_event_that_is_not_in_the_group():
    from fastapi import HTTPException

    from pecha_api.events.youtube_live_sync_service import update_youtube_live_sync_service

    session, db = _settings_session(events_in_group=[EVENT_A])  # EVENT_B is elsewhere
    request = UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_A, EVENT_B], run_times=["08:30"])
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
        f"{MODULE}._authorize", return_value=SimpleNamespace(email="admin@x.com")
    ):
        with pytest.raises(HTTPException) as caught:
            update_youtube_live_sync_service("t", GROUP_ID, request)
    assert caught.value.status_code == 404
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_update_creates_a_schedule_only_for_the_listed_events():
    from pecha_api.events.youtube_live_sync_service import update_youtube_live_sync_service

    session, db = _settings_session(events_in_group=[EVENT_A])
    request = UpdateYoutubeLiveSyncRequest(
        event_ids=[EVENT_A], run_times=["08:30", "14:00"], timezone=IST
    )
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
        f"{MODULE}._authorize", return_value=SimpleNamespace(email="admin@x.com")
    ), patch(f"{MODULE}._list_dto") as list_dto:
        update_youtube_live_sync_service("t", GROUP_ID, request)
    assert db.add.call_count == 1
    schedule = db.add.call_args.args[0]
    assert (schedule.event_id, schedule.group_id) == (EVENT_A, GROUP_ID)
    assert schedule.run_times == ["08:30", "14:00"]
    assert schedule.timezone == IST
    assert schedule.enabled is True
    db.commit.assert_called_once()
    list_dto.assert_called_once()


def test_update_changes_an_existing_schedule_in_place_and_does_not_fire_a_past_time():
    from pecha_api.events.youtube_live_sync_model import EventYoutubeLiveSync
    from pecha_api.events.youtube_live_sync_service import update_youtube_live_sync_service

    current = EventYoutubeLiveSync(event_id=EVENT_A, group_id=GROUP_ID, run_times=["06:00"], enabled=False)
    session, db = _settings_session(existing=[current], events_in_group=[EVENT_A])
    request = UpdateYoutubeLiveSyncRequest(event_ids=[EVENT_A], run_times=["00:00"], timezone="UTC")
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(
        f"{MODULE}._authorize", return_value=SimpleNamespace(email="admin@x.com")
    ), patch(f"{MODULE}._list_dto"):
        update_youtube_live_sync_service("t", GROUP_ID, request)
    db.add.assert_not_called()
    assert current.run_times == ["00:00"] and current.enabled is True
    # 00:00 UTC today has already passed, so it is marked as handled.
    assert current.last_slot_at is not None
    assert due_slot(current.run_times, "UTC", datetime.now(timezone.utc), current.last_slot_at, 600) is None


def test_run_now_is_refused_for_an_event_outside_the_group():
    from fastapi import HTTPException

    from pecha_api.events.youtube_live_sync_service import run_youtube_live_sync_now_service

    session, _ = _settings_session(events_in_group=[])
    with patch(f"{MODULE}.SessionLocal", return_value=session), patch(f"{MODULE}._authorize"), patch(
        f"{MODULE}.sync_group_live_streams"
    ) as sync:
        with pytest.raises(HTTPException):
            run_youtube_live_sync_now_service(
                "t", GROUP_ID, RunYoutubeLiveSyncRequest(event_ids=[EVENT_A])
            )
    sync.assert_not_called()
