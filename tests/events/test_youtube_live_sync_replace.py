from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events import youtube_live_sync_service as svc
from pecha_api.events.youtube_live_sync_service import SyncOutcome, sync_group_live_streams
from pecha_api.external_clients.youtube_channel_client import YoutubeLiveVideo
from pecha_api.plans.plans_enums import LanguageCode

MODULE = svc.__name__
GROUP_ID = uuid4()
NOW = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc)
OLD, NEW, OTHER = "OLDOLDOLD00", "NEWNEWNEW00", "OTHEROTHER0"


def _url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _link(video_id: str, language: str, order: int, type_: str = "youtube") -> SimpleNamespace:
    return SimpleNamespace(
        type=type_,
        url=_url(video_id),
        label=f"label {video_id}",
        language=language,
        display_order=order,
        updated_at=None,
    )


def _video(video_id: str, title: str = "Live teaching") -> YoutubeLiveVideo:
    return YoutubeLiveVideo(id=video_id, title=title, url=_url(video_id), status="live")


def _run(videos, events, languages, author=None):
    db = MagicMock()
    with patch(f"{MODULE}._group_channel_url", return_value="https://www.youtube.com/@g"), patch(
        f"{MODULE}.fetch_channel_live_videos", return_value=videos
    ), patch(f"{MODULE}._chosen_events", return_value=events), patch(
        f"{MODULE}.suggest_live_stream_languages", return_value=languages
    ), patch(f"{MODULE}.find_author_by_email", return_value=author), patch(
        f"{MODULE}.sync_event_youtube_to_plan_day"
    ) as plan_sync, patch(f"{MODULE}.schedule_invalidate_event_detail_caches"):
        outcome = sync_group_live_streams(db, GROUP_ID, [e.id for e in events], now=NOW)
    return outcome, db, plan_sync


def _event(*links) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), created_by="a@x.com", links=list(links))


def test_a_new_stream_replaces_the_events_link_in_the_same_language():
    old = _link(OLD, "BO", 1)
    event = _event(old)
    outcome, db, _ = _run([_video(NEW, "Teaching today")], [event], {NEW: LanguageCode.BO})

    assert outcome == SyncOutcome(live_streams_found=1, events_checked=1, links_replaced=1)
    assert old.url == _url(NEW)
    assert old.label == "Teaching today"
    assert old.updated_at == NOW
    # The same row is switched over: no extra link, and its place in the list is kept.
    assert old.display_order == 1
    db.add.assert_not_called()
    db.commit.assert_called_once()


def test_links_in_other_languages_are_left_alone():
    tibetan = _link(OLD, "BO", 1)
    english = _link(OTHER, "EN", 2)
    chinese = _link("CHINESE0000", "ZH", 3)
    event = _event(tibetan, english, chinese)
    _run([_video(NEW)], [event], {NEW: LanguageCode.BO})

    assert tibetan.url == _url(NEW)
    assert english.url == _url(OTHER) and english.label == f"label {OTHER}"
    assert chinese.url == _url("CHINESE0000")


def test_a_stream_the_event_already_has_changes_nothing():
    old = _link(NEW, "BO", 1)
    event = _event(old)
    outcome, db, suggest_calls = _run([_video(NEW)], [event], {NEW: LanguageCode.BO})
    assert outcome.links_added == 0 and outcome.links_replaced == 0
    assert old.updated_at is None
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_a_language_with_no_link_yet_gets_one_added():
    event = _event(_link(OLD, "EN", 1))
    outcome, db, _ = _run([_video(NEW)], [event], {NEW: LanguageCode.BO})
    assert (outcome.links_added, outcome.links_replaced) == (1, 0)
    assert db.add.call_args.args[0].language == LanguageCode.BO
    assert db.add.call_args.args[0].display_order == 2


def test_when_several_links_share_the_language_the_first_in_the_list_is_replaced():
    first = _link(OLD, "BO", 1)
    second = _link(OTHER, "BO", 2)
    event = _event(second, first)  # stored out of order
    _run([_video(NEW)], [event], {NEW: LanguageCode.BO})
    assert first.url == _url(NEW)
    assert second.url == _url(OTHER)


def test_a_non_youtube_link_in_the_language_is_never_replaced():
    web = _link("webwebweb00", "BO", 1, type_="web")
    event = _event(web)
    outcome, db, _ = _run([_video(NEW)], [event], {NEW: LanguageCode.BO})
    assert web.url == _url("webwebweb00")
    assert (outcome.links_added, outcome.links_replaced) == (1, 0)


def test_two_streams_live_in_one_language_both_end_up_on_the_event():
    old = _link(OLD, "BO", 1)
    event = _event(old)
    outcome, db, _ = _run(
        [_video(NEW, "Morning"), _video(OTHER, "Evening")],
        [event],
        {NEW: LanguageCode.BO, OTHER: LanguageCode.BO},
    )
    # The first swaps in over the old link; the second sits beside it rather
    # than swapping the first straight back out.
    assert old.url == _url(NEW)
    assert outcome.links_replaced == 1 and outcome.links_added == 1
    assert db.add.call_args.args[0].url == _url(OTHER)


def test_each_event_is_handled_on_its_own():
    with_link = _event(_link(OLD, "BO", 1))
    without = _event()
    outcome, db, _ = _run([_video(NEW)], [with_link, without], {NEW: LanguageCode.BO})
    assert with_link.links[0].url == _url(NEW)
    assert (outcome.links_replaced, outcome.links_added) == (1, 1)
    assert db.add.call_args.args[0].event_id == without.id


def test_a_replaced_link_is_copied_to_the_plan_day_as_a_new_video():
    event = _event(_link(OLD, "BO", 1))
    author = SimpleNamespace(email="a@x.com")
    _, _, plan_sync = _run([_video(NEW)], [event], {NEW: LanguageCode.BO}, author=author)
    plan_sync.assert_called_once()
    # What the event had before the swap, so only the new stream counts as new.
    assert plan_sync.call_args.kwargs["previous_keys"] == {(OLD, "BO")}


def test_an_unclear_language_replaces_nothing():
    old = _link(OLD, "BO", 1)
    outcome, db, _ = _run([_video(NEW)], [_event(old)], {})
    assert outcome.skipped_unknown_language == 1
    assert old.url == _url(OLD)
    db.commit.assert_not_called()


def test_the_last_run_count_includes_replacements():
    session = MagicMock()
    db = MagicMock()
    session.__enter__.return_value = db
    with patch(f"{MODULE}.SessionLocal", return_value=session):
        svc._record_outcome(
            [uuid4()], outcome=SyncOutcome(links_added=1, links_replaced=2), error=None
        )
    assert db.execute.call_args.args[0].compile().params["last_run_added"] == 3
