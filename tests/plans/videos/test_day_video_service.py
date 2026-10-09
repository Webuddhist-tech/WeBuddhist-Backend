from typing import Optional
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.tasks.plan_tasks_models import PlanTask
from pecha_api.plans.videos.day_video_models import DayVideo
from pecha_api.plans.videos.day_video_response_models import CreateDayVideoRequest
from pecha_api.plans.videos.day_video_service import (
    add_day_video,
    ensure_day_video_durations,
    list_day_videos,
)

SERVICE = "pecha_api.plans.videos.day_video_service"


def _video(*, duration_seconds: Optional[int] = None, video_id: str = "AAAAAAAAAAA") -> MagicMock:
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


def test_add_day_video_saves_link_when_youtube_response_is_malformed():
    day_id = uuid4()
    created = _video(duration_seconds=None)
    db = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = db
    session.__exit__.return_value = False

    with patch(f"{SERVICE}.SessionLocal", return_value=session), patch(
        f"{SERVICE}.validate_cms_author_details", return_value=MagicMock(email="a@x.com")
    ), patch(f"{SERVICE}._get_author_plan_item_by_day_id"), patch(
        f"{SERVICE}.get_next_display_order", return_value=0
    ), patch(
        f"{SERVICE}.lookup_youtube_duration_seconds", return_value=None
    ), patch(f"{SERVICE}.create_day_video", return_value=created) as create:
        result = add_day_video(
            token="tok",
            day_id=day_id,
            request=CreateDayVideoRequest(url="https://youtu.be/AAAAAAAAAAA"),
        )

    create.assert_called_once()
    assert create.call_args.kwargs["day_video"].duration_seconds is None
    assert result.duration_seconds is None


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
    db.commit.assert_not_called()


def test_ensure_day_video_durations_does_not_expire_attached_plan_item_tasks():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    PlanItem.__table__.create(bind=engine)
    PlanTask.__table__.create(bind=engine)
    DayVideo.__table__.create(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=True)

    plan_item_id = uuid4()
    plan_id = uuid4()

    with session_factory() as db:
        plan_item = PlanItem(
            id=plan_item_id,
            plan_id=plan_id,
            day_number=1,
            created_by="test@example.com",
        )
        task = PlanTask(
            plan_item_id=plan_item_id,
            display_order=0,
            created_by="test@example.com",
            title="Morning reading",
        )
        video = DayVideo(
            day_id=plan_item_id,
            url="https://youtu.be/AAAAAAAAAAA",
            video_id="AAAAAAAAAAA",
            display_order=0,
            created_by="test@example.com",
        )
        db.add_all([plan_item, task, video])
        db.commit()

    with patch(f"{SERVICE}.durations_for_video_ids", return_value={"AAAAAAAAAAA": 120}), patch(
        f"{SERVICE}.SessionLocal", session_factory
    ):
        with session_factory() as db:
            loaded_item = db.get(PlanItem, plan_item_id)
            assert loaded_item is not None
            _ = loaded_item.tasks
            ensure_day_video_durations(db=db, videos=list(loaded_item.videos))

    assert loaded_item.tasks[0].title == "Morning reading"
    assert loaded_item.videos[0].duration_seconds == 120
