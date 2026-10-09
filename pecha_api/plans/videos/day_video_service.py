from typing import Iterable, List, Optional, Sequence, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.cms.cms_plans_repository import get_plan_by_id
from pecha_api.plans.items.plan_items_repository import get_plan_item_by_id
from pecha_api.plans.shared.permissions import require_can_edit_content
from pecha_api.plans.response_message import (
    BAD_REQUEST,
    DAY_VIDEO_NOT_FOUND,
    INVALID_YOUTUBE_URL,
    PLAN_DAY_NOT_FOUND,
    PLAN_NOT_FOUND,
)
from pecha_api.plans.videos.day_video_models import DayVideo
from pecha_api.plans.videos.day_video_repository import (
    create_day_video,
    delete_day_video,
    get_day_video_by_id,
    get_day_videos_by_day_id,
    get_next_display_order,
    reorder_day_videos,
)
from pecha_api.plans.videos.day_video_response_models import (
    CreateDayVideoRequest,
    DayVideoDTO,
    DayVideoListResponse,
    ReorderDayVideosRequest,
)
from pecha_api.plans.videos.youtube_utils import (
    durations_for_video_ids,
    extract_youtube_video_id,
    lookup_youtube_duration_seconds,
)


def _persist_day_video_duration_updates(updates: Sequence[Tuple[UUID, int]]) -> None:
    """Persist durations outside the caller session so commit does not expire loaded rows."""
    if not updates:
        return
    with SessionLocal() as db:
        for video_id, seconds in updates:
            db.query(DayVideo).filter(DayVideo.id == video_id).update(
                {DayVideo.duration_seconds: seconds},
                synchronize_session=False,
            )
        db.commit()


def _to_dto(video: DayVideo) -> DayVideoDTO:
    return DayVideoDTO(
        id=video.id,
        day_id=video.day_id,
        url=video.url,
        video_id=video.video_id,
        title=video.title,
        duration_seconds=video.duration_seconds,
        display_order=video.display_order,
        created_at=video.created_at,
    )


def ensure_day_video_durations(
    db: Session,
    videos: Sequence[DayVideo],
    *,
    commit: bool = True,
) -> List[DayVideo]:
    """Fill missing YouTube lengths, persist any that resolve, leave the rest."""
    missing = [video for video in videos if video.duration_seconds is None and video.video_id]
    if not missing:
        return list(videos)
    durations = durations_for_video_ids(video.video_id for video in missing)
    updates: List[Tuple[UUID, int]] = []
    for video in missing:
        seconds = durations.get(video.video_id)
        if seconds is not None:
            video.duration_seconds = seconds
            updates.append((video.id, seconds))
    if updates and commit:
        _persist_day_video_duration_updates(updates)
    return list(videos)


def day_videos_with_durations(
    db: Session,
    videos: Iterable[DayVideo],
    *,
    commit: bool = True,
) -> List[DayVideo]:
    return ensure_day_video_durations(db=db, videos=list(videos), commit=commit)


def _get_author_plan_item_by_day_id(db, day_id: UUID, current_author):
    plan_item = get_plan_item_by_id(db=db, day_id=day_id)
    if not plan_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ResponseError(error=BAD_REQUEST, message=PLAN_DAY_NOT_FOUND).model_dump(),
        )
    plan = get_plan_by_id(db=db, plan_id=plan_item.plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ResponseError(error=BAD_REQUEST, message=PLAN_NOT_FOUND).model_dump(),
        )
    require_can_edit_content(
        db=db,
        group_id=plan.group_id,
        author=current_author,
        content_status=plan.status,
    )
    return plan_item


def list_day_videos(token: str, day_id: UUID) -> DayVideoListResponse:
    with SessionLocal() as db:
        current_author = validate_cms_author_details(token=token)
        _get_author_plan_item_by_day_id(db=db, day_id=day_id, current_author=current_author)
        videos = day_videos_with_durations(
            db=db, videos=get_day_videos_by_day_id(db=db, day_id=day_id)
        )
        return DayVideoListResponse(videos=[_to_dto(video) for video in videos])


def add_day_video(token: str, day_id: UUID, request: CreateDayVideoRequest) -> DayVideoDTO:
    url = request.url.strip()
    video_id = extract_youtube_video_id(url)
    if not video_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=INVALID_YOUTUBE_URL).model_dump(),
        )

    with SessionLocal() as db:
        current_author = validate_cms_author_details(token=token)
        _get_author_plan_item_by_day_id(db=db, day_id=day_id, current_author=current_author)

        display_order = get_next_display_order(db=db, day_id=day_id)
        duration_seconds: Optional[int] = lookup_youtube_duration_seconds(video_id)
        video = create_day_video(
            db=db,
            day_video=DayVideo(
                day_id=day_id,
                url=url,
                video_id=video_id,
                title=request.title,
                duration_seconds=duration_seconds,
                display_order=display_order,
                created_by=current_author.email,
            ),
        )
        return _to_dto(video)


def remove_day_video(token: str, day_id: UUID, video_id: UUID) -> None:
    with SessionLocal() as db:
        current_author = validate_cms_author_details(token=token)
        _get_author_plan_item_by_day_id(db=db, day_id=day_id, current_author=current_author)

        video = get_day_video_by_id(db=db, day_id=day_id, video_id=video_id)
        if not video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error=BAD_REQUEST, message=DAY_VIDEO_NOT_FOUND).model_dump(),
            )
        delete_day_video(db=db, day_id=day_id, video_id=video_id)


def reorder_day_videos_entries(
    token: str, day_id: UUID, request: ReorderDayVideosRequest
) -> DayVideoListResponse:
    with SessionLocal() as db:
        current_author = validate_cms_author_details(token=token)
        _get_author_plan_item_by_day_id(db=db, day_id=day_id, current_author=current_author)

        order_by_id = {item.id: item.display_order for item in request.videos}
        reorder_day_videos(db=db, day_id=day_id, order_by_id=order_by_id)

        videos = day_videos_with_durations(
            db=db, videos=get_day_videos_by_day_id(db=db, day_id=day_id)
        )
        return DayVideoListResponse(videos=[_to_dto(video) for video in videos])
