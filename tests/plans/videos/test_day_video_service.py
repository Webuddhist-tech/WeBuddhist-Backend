from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.plans.videos.day_video_response_models import CreateDayVideoRequest
from pecha_api.plans.videos.day_video_service import (
    add_day_video,
    ensure_day_video_durations,
    list_day_videos,
)

SERVICE = "pecha_api.plans.videos.day_video_service"


def _video(*, duration_seconds=None, video_id="AAAAAAAAAAA"):
    video = MagicMock()
    video.id = uuid4()
    video.day_id = uuid4()
    video.url = f"https://youtu.be/{video_id}"
    video.video_id = video_id
    video.title = None
    video.duration_seconds = duration_seconds
    video.display_order = 0
    video.created_at = None
    return video


def test_ensure_skips_youtube_when_duration_already_stored():
    db = MagicMock()
    video = _video(duration_seconds=90)

    with patch(f"{SERVICE}.durations_for_video_ids") as fetch:
        ensure_day_video_durations(db=db, videos=[video])

    fetch.assert_not_called()
    db.commit.assert_not_called()


def test_ensure_fetches_persists_and_returns_missing_duration():
    db = MagicMock()
    video = _video(duration_seconds=None)

    with patch(f"{SERVICE}.durations_for_video_ids", return_value={"AAAAAAAAAAA": 253}), patch(
        f"{SERVICE}._persist_day_video_duration_updates"
    ) as persist:
        ensure_day_video_durations(db=db, videos=[video])

    persist.assert_called_once()

    assert video.duration_seconds == 253
    db.commit.assert_not_called()


def test_ensure_leaves_null_duration_when_youtube_fails():
    db = MagicMock()
    video = _video(duration_seconds=None)

    with patch(f"{SERVICE}.durations_for_video_ids", return_value={}):
        ensure_day_video_durations(db=db, videos=[video])

    assert video.duration_seconds is None
    db.commit.assert_not_called()


def test_add_day_video_stores_youtube_duration():
    day_id = uuid4()
    created = _video(duration_seconds=253)
    db = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = db
    session.__exit__.return_value = False

    with patch(f"{SERVICE}.SessionLocal", return_value=session), patch(
        f"{SERVICE}.validate_cms_author_details", return_value=MagicMock(email="a@x.com")
    ), patch(f"{SERVICE}._get_author_plan_item_by_day_id"), patch(
        f"{SERVICE}.get_next_display_order", return_value=0
    ), patch(
        f"{SERVICE}.lookup_youtube_duration_seconds", return_value=253
    ) as lookup, patch(
        f"{SERVICE}.create_day_video", return_value=created
    ) as create:
        result = add_day_video(
            token="tok",
            day_id=day_id,
            request=CreateDayVideoRequest(url="https://youtu.be/AAAAAAAAAAA"),
        )

    lookup.assert_called_once_with("AAAAAAAAAAA")
    assert create.call_args.kwargs["day_video"].duration_seconds == 253
    assert result.duration_seconds == 253


def test_list_day_videos_backfills_missing_duration():
    day_id = uuid4()
    video = _video(duration_seconds=None)
    db = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = db
    session.__exit__.return_value = False

    with patch(f"{SERVICE}.SessionLocal", return_value=session), patch(
        f"{SERVICE}.validate_cms_author_details", return_value=MagicMock(email="a@x.com")
    ), patch(f"{SERVICE}._get_author_plan_item_by_day_id"), patch(
        f"{SERVICE}.get_day_videos_by_day_id", return_value=[video]
    ), patch(
        f"{SERVICE}.durations_for_video_ids", return_value={"AAAAAAAAAAA": 12}
    ), patch(f"{SERVICE}._persist_day_video_duration_updates") as persist:
        result = list_day_videos(token="tok", day_id=day_id)

    assert result.videos[0].duration_seconds == 12
    persist.assert_called_once()
