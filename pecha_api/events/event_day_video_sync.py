import logging
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.videos.day_video_models import DayVideo
from pecha_api.plans.videos.day_video_repository import (
    get_day_videos_by_day_id,
    get_next_display_order,
)
from pecha_api.plans.videos.youtube_utils import extract_youtube_video_id
from pecha_api.timezone_utils import get_date_in_timezone

from .event_enums import EventLinkType
from .event_model import Event

logger = logging.getLogger(__name__)

# (YouTube video id, upper-case language code)
VideoKey = Tuple[str, str]


def _language_code(language) -> str:
    return str(getattr(language, "value", language) or "").upper()


def _youtube_links_with_keys(event: Event) -> List[Tuple[object, VideoKey]]:
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


def _current_plan_day_number(event: Event) -> int:
    """Day of the event the author is on right now, 1-based, counted in the
    event's own timezone so a late-evening save doesn't land on tomorrow."""
    today = get_date_in_timezone(event.timezone)
    start = get_date_in_timezone(event.timezone, at=event.start_date)
    return (today - start).days + 1


def _linked_plans_by_language(db: Session, event: Event) -> Dict[str, List[Plan]]:
    """The event's plan, plus every plan of its series (one per language)."""
    conditions = []
    if event.plan_id:
        conditions.append(Plan.id == event.plan_id)
    if getattr(event, "series_id", None):
        conditions.append(Plan.series_id == event.series_id)
    if not conditions:
        return {}
    plans = db.query(Plan).filter(or_(*conditions), Plan.deleted_at.is_(None)).all()
    by_language: Dict[str, List[Plan]] = {}
    for plan in plans:
        by_language.setdefault(_language_code(plan.language), []).append(plan)
    return by_language


def _add_to_plan_day(
    db: Session, plan: Plan, day_number: int, links: List[Tuple[object, str]], author_email: str
) -> int:
    day = (
        db.query(PlanItem)
        .filter(PlanItem.plan_id == plan.id, PlanItem.day_number == day_number)
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
    added = 0
    for link, video_id in links:
        if video_id in existing_ids:
            continue
        db.add(
            DayVideo(
                day_id=day.id,
                url=link.url,
                video_id=video_id,
                display_order=display_order,
                created_by=author_email,
            )
        )
        existing_ids.add(video_id)
        display_order += 1
        added += 1
    return added


def _sync(db: Session, event: Event, previous_keys: Set[VideoKey], author_email: str) -> None:
    new_links_by_language: Dict[str, List[Tuple[object, str]]] = {}
    seen = set(previous_keys)
    for link, key in _youtube_links_with_keys(event):
        if key in seen:
            continue
        seen.add(key)
        video_id, language = key
        new_links_by_language.setdefault(language, []).append((link, video_id))
    if not new_links_by_language:
        return

    plans_by_language = _linked_plans_by_language(db, event)
    day_number = _current_plan_day_number(event)
    added = 0
    for language, links in new_links_by_language.items():
        # A video only belongs on a plan in its own language.
        for plan in plans_by_language.get(language, []):
            added += _add_to_plan_day(db, plan, day_number, links, author_email)
    if added:
        db.commit()


def sync_event_youtube_to_plan_day(
    db: Session,
    event: Event,
    previous_keys: Iterable[VideoKey],
    author_email: str,
) -> None:
    """Copy YouTube links newly added to an event onto today's day of the
    linked plan in the same language, skipping videos that day already has.

    Best effort: runs after the event is committed, and any failure is
    logged and rolled back without failing the event save.
    """
    try:
        _sync(db, event, set(previous_keys), author_email)
    except Exception:
        db.rollback()
        logger.exception("Event %s: failed to add YouTube links to plan day", getattr(event, "id", None))
