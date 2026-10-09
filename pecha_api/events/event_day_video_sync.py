import logging
from datetime import date, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.public.plans_cache_service import schedule_invalidate_plan_day_cache
from pecha_api.plans.shared.permissions import require_can_edit_content
from pecha_api.plans.videos.day_video_models import DayVideo
from pecha_api.plans.videos.day_video_repository import (
    get_day_videos_by_day_id,
    get_next_display_order,
)
from pecha_api.plans.videos.youtube_utils import (
    durations_for_video_ids,
    extract_youtube_video_id,
)
from pecha_api.timezone_utils import get_date_in_timezone

from .event_enums import EventLinkType
from .event_link_model import EventLink
from .event_model import Event

logger = logging.getLogger(__name__)

# (YouTube video id, upper-case language code)
VideoKey = Tuple[str, str]
# (plan id, day number) of a plan day that received videos
ChangedDay = Tuple[object, int]

# Intentionally best effort. The sync runs after the event is committed and
# is kept out of the event's transaction, so a failed video copy never fails
# the event save. That means a failed attempt cannot be re-driven by
# resubmitting the event (its links are no longer new), so a second attempt
# covers transient failures (lock timeout, dropped connection). If both fail,
# the missing video ids are logged and can be added through the day-video
# endpoint. A durable retry (job queue / outbox) is deliberately out of scope.
_SYNC_ATTEMPTS = 2


def _language_code(language: object) -> str:
    return str(getattr(language, "value", language) or "").upper()


def _youtube_links_with_keys(event: Event) -> List[Tuple[EventLink, VideoKey]]:
    links = []
    for link in event.links or []:
        if (link.type or "").strip().lower() != EventLinkType.YOUTUBE.value:
            continue
        video_id = extract_youtube_video_id(link.url or "")
        if video_id:
            links.append((link, (video_id, _language_code(link.language))))
    return links


def youtube_video_keys_of_event(event: Optional[Event]) -> Set[VideoKey]:
    """(video id, language) pairs currently on the event, used to tell which
    links an update newly added (update_event replaces every YouTube row)."""
    if event is None:
        return set()
    return {key for _, key in _youtube_links_with_keys(event)}


def _plan_start_date(event: Event, plan: Plan) -> date:
    """Day 1 of the plan: its own start date, as the series schedule counts
    it, falling back to the event's start when the plan has none. Read in the
    event's timezone, like today's date, so the two are the same calendar."""
    if plan.start_date is not None:
        start = plan.start_date
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return get_date_in_timezone(event.timezone, at=start)
    return get_date_in_timezone(event.timezone, at=event.start_date)


def _current_plan_day_number(event: Event, plan: Plan) -> int:
    """Day of the plan the author is on right now, 1-based. Today is read in
    the event's own timezone so a late-evening save doesn't land on tomorrow."""
    today = get_date_in_timezone(event.timezone)
    return (today - _plan_start_date(event, plan)).days + 1


def _author_can_edit_plan(db: Session, plan: Plan, author: Author) -> bool:
    """Same gate the day-video endpoints apply before writing to a plan day."""
    try:
        require_can_edit_content(
            db=db,
            group_id=plan.group_id,
            author=author,
            content_status=plan.status,
        )
    except HTTPException:
        return False
    return True


def _linked_plans_by_language(db: Session, event: Event, author: Author) -> Dict[str, List[Plan]]:
    """The event's plan, plus every plan of its series (one per language),
    limited to plans of the event's own group that the author may edit."""
    conditions = []
    if event.plan_id:
        conditions.append(Plan.id == event.plan_id)
    if getattr(event, "series_id", None):
        conditions.append(Plan.series_id == event.series_id)
    if not conditions:
        return {}
    plans = (
        db.query(Plan)
        .filter(
            or_(*conditions),
            Plan.group_id == event.group_id,
            Plan.deleted_at.is_(None),
        )
        .all()
    )
    by_language: Dict[str, List[Plan]] = {}
    for plan in plans:
        if not _author_can_edit_plan(db, plan, author):
            logger.info(
                "Event %s: author %s cannot edit plan %s, YouTube links not added",
                event.id, author.email, plan.id,
            )
            continue
        by_language.setdefault(_language_code(plan.language), []).append(plan)
    return by_language


def _add_to_plan_day(
    db: Session,
    plan: Plan,
    day_number: int,
    links: List[Tuple[EventLink, str]],
    author_email: str,
    *,
    durations: Dict[str, int],
) -> int:
    # Locking the day serialises concurrent event saves on it, so the second
    # one sees the first one's videos and display order instead of racing it.
    day = (
        db.query(PlanItem)
        .filter(PlanItem.plan_id == plan.id, PlanItem.day_number == day_number)
        .with_for_update()
        .first()
    )
    if not day:
        logger.info("Plan %s has no day %s, YouTube links not added", plan.id, day_number)
        return 0

    existing_ids = {
        video.video_id or extract_youtube_video_id(video.url or "")
        for video in get_day_videos_by_day_id(db=db, day_id=day.id)
    }
    display_order = get_next_display_order(db=db, day_id=day.id)
    new_links = [
        (link, video_id) for link, video_id in links if video_id not in existing_ids
    ]
    added = 0
    for link, video_id in new_links:
        db.add(
            DayVideo(
                day_id=day.id,
                url=link.url,
                video_id=video_id,
                duration_seconds=durations.get(video_id),
                display_order=display_order,
                created_by=author_email,
            )
        )
        existing_ids.add(video_id)
        display_order += 1
        added += 1
    return added


def _sync(db: Session, event: Event, previous_keys: Set[VideoKey], author: Author) -> List[ChangedDay]:
    new_links_by_language: Dict[str, List[Tuple[EventLink, str]]] = {}
    seen = set(previous_keys)
    for link, key in _youtube_links_with_keys(event):
        if key in seen:
            continue
        seen.add(key)
        video_id, language = key
        new_links_by_language.setdefault(language, []).append((link, video_id))
    if not new_links_by_language:
        return []

    video_ids = {
        video_id
        for links in new_links_by_language.values()
        for _, video_id in links
    }
    try:
        durations = durations_for_video_ids(video_ids)
    except Exception as error:
        logger.warning(
            "YouTube duration lookup failed while syncing event links error=%s",
            type(error).__name__,
        )
        durations = {}

    plans_by_language = _linked_plans_by_language(db, event, author)
    changed_days: List[ChangedDay] = []
    for language, links in new_links_by_language.items():
        # A video only belongs on a plan in its own language.
        for plan in plans_by_language.get(language, []):
            day_number = _current_plan_day_number(event, plan)
            if _add_to_plan_day(
                db, plan, day_number, links, author.email, durations=durations
            ):
                changed_days.append((plan.id, day_number))
    if changed_days:
        db.commit()
    return changed_days


def sync_event_youtube_to_plan_day(
    db: Session,
    event: Event,
    previous_keys: Iterable[VideoKey],
    author: Author,
) -> None:
    """Copy YouTube links newly added to an event onto today's day of the
    linked plan in the same language, skipping videos that day already has.

    Best effort: runs after the event is committed, and any failure is
    logged and rolled back without failing the event save.
    """
    previous = set(previous_keys)
    for attempt in range(1, _SYNC_ATTEMPTS + 1):
        try:
            changed_days = _sync(db, event, previous, author)
        except Exception:
            db.rollback()
            if attempt < _SYNC_ATTEMPTS:
                logger.warning(
                    "Event %s: adding YouTube links to plan day failed, retrying",
                    getattr(event, "id", None),
                )
                continue
            logger.exception(
                "Event %s: failed to add YouTube links %s to plan day",
                getattr(event, "id", None),
                sorted(youtube_video_keys_of_event(event) - previous),
            )
            return
        # Readers of these days would otherwise keep the old video list until
        # the cache expires.
        for plan_id, day_number in changed_days:
            schedule_invalidate_plan_day_cache(plan_id=plan_id, day_number=day_number)
        return
