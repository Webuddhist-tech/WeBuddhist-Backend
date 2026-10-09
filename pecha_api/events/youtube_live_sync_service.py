"""Add a group's live YouTube stream to the events an admin chose.

In Studio an admin picks events and the times of day for each (see the
`event_youtube_live_sync` table). A job wakes up every minute and finds the
schedules whose time has come. For each group with something due it looks at
the group's YouTube channel once, and adds a stream that is live right now to
the scheduled events that do not already have it, in the language an LLM reads
from the stream's title. Events nobody scheduled are never touched.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.orm import Session, selectinload
from starlette import status

from pecha_api import config
from pecha_api.db.database import SessionLocal
from pecha_api.external_clients.gemini_client import suggest_live_stream_languages
from pecha_api.external_clients.youtube_channel_client import (
    YoutubeChannelError,
    YoutubeLiveVideo,
    fetch_channel_live_videos,
    find_group_channel_url,
)
from pecha_api.plans.authors.plan_authors_repository import find_author_by_email
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
from pecha_api.plans.groups.groups_models import AuthorGroup, AuthorGroupSocialLink
from pecha_api.plans.shared.permissions import (
    require_can_read_group_content,
    require_cms_write_access,
    require_group_member,
)
from pecha_api.plans.videos.youtube_utils import extract_youtube_video_id

from .event_day_video_sync import sync_event_youtube_to_plan_day, youtube_video_keys_of_event
from .event_enums import EventLinkType
from .event_link_model import EventLink
from .event_model import Event
from .events_cache_service import schedule_invalidate_event_detail_caches
from .youtube_live_sync_model import EventYoutubeLiveSync
from .youtube_live_sync_response_models import (
    RunYoutubeLiveSyncRequest,
    UpdateYoutubeLiveSyncRequest,
    YoutubeLiveSyncListDTO,
    YoutubeLiveSyncRunDTO,
    YoutubeLiveSyncScheduleDTO,
)

logger = logging.getLogger(__name__)

_SETTINGS_ROLES = {AuthorGroupMemberRole.OWNER, AuthorGroupMemberRole.ADMIN}
_GROUP_NOT_FOUND = "Group not found"
_EVENT_NOT_FOUND = "Event not found in this group"
_SCHEDULE_NOT_FOUND = "No live sync schedule on this event"
_MAX_LABEL_LENGTH = 255
_MAX_ERROR_LENGTH = 500


@dataclass
class SyncOutcome:
    live_streams_found: int = 0
    events_checked: int = 0
    links_added: int = 0
    skipped_unknown_language: int = 0


# ---------------------------------------------------------------- schedule


def _zone(timezone_name: Optional[str]) -> ZoneInfo:
    for candidate in (timezone_name, config.get("DEFAULT_EVENT_TIMEZONE")):
        try:
            if candidate:
                return ZoneInfo(candidate.strip())
        except (ZoneInfoNotFoundError, ValueError):
            continue
    return ZoneInfo("UTC")


def effective_timezone_name(timezone_name: Optional[str]) -> str:
    return _zone(timezone_name).key


def _parse_run_times(run_times: Sequence[str]) -> List[time]:
    parsed: List[time] = []
    for value in run_times or []:
        try:
            hour, minute = str(value).split(":")
            parsed.append(time(int(hour), int(minute)))
        except ValueError:
            logger.warning("Ignoring unreadable YouTube live sync time %r", value)
    return parsed


def latest_slot_at_or_before(
    run_times: Sequence[str], timezone_name: Optional[str], now: datetime
) -> Optional[datetime]:
    """The most recent scheduled moment (UTC) that is not after `now`. Yesterday
    is looked at too, so a 23:50 slot is still found just after midnight."""
    zone = _zone(timezone_name)
    today: date = now.astimezone(zone).date()
    slots = [
        datetime.combine(day, run_time, tzinfo=zone).astimezone(timezone.utc)
        for day in (today - timedelta(days=1), today)
        for run_time in _parse_run_times(run_times)
    ]
    reached = [slot for slot in slots if slot <= now]
    return max(reached) if reached else None


def due_slot(
    run_times: Sequence[str],
    timezone_name: Optional[str],
    now: datetime,
    last_slot_at: Optional[datetime],
    grace_seconds: int,
) -> Optional[datetime]:
    """The scheduled moment that should run now, if any.

    It is the latest time that has been reached and not yet run. A time the
    job missed by more than `grace_seconds` (the app was down, say) is skipped
    rather than run late: a stream that was live hours ago says little about
    what is live now, and the next time covers it."""
    slot = latest_slot_at_or_before(run_times, timezone_name, now)
    if slot is None or (now - slot).total_seconds() > grace_seconds:
        return None
    if last_slot_at is not None:
        if last_slot_at.tzinfo is None:
            last_slot_at = last_slot_at.replace(tzinfo=timezone.utc)
        if last_slot_at >= slot:
            return None
    return slot


# -------------------------------------------------------------------- sync


def _existing_video_ids(event: Event) -> Set[str]:
    ids: Set[str] = set()
    for link in event.links or []:
        if (link.type or "").strip().lower() != EventLinkType.YOUTUBE.value:
            continue
        video_id = extract_youtube_video_id(link.url or "")
        if video_id:
            ids.add(video_id)
    return ids


def _next_youtube_display_order(event: Event) -> int:
    orders = [
        link.display_order or 0
        for link in event.links or []
        if (link.type or "").strip().lower() == EventLinkType.YOUTUBE.value
    ]
    return max(orders, default=0) + 1


def _chosen_events(
    db: Session, group_id: UUID, event_ids: Sequence[UUID], now: datetime
) -> List[Event]:
    """Only the events asked for, and only those of this group. An event that
    has already ended is left alone (a recurring one has no end of its own)."""
    return (
        db.query(Event)
        .options(selectinload(Event.links))
        .filter(
            Event.id.in_(list(event_ids)),
            Event.group_id == group_id,
            or_(Event.is_recurring.is_(True), Event.end_date >= now),
        )
        .all()
    )


def _group_channel_url(db: Session, group_id: UUID) -> Optional[str]:
    links = (
        db.query(AuthorGroupSocialLink)
        .filter(AuthorGroupSocialLink.group_id == group_id)
        .all()
    )
    return find_group_channel_url(links)


def _after_links_added(
    db: Session, event: Event, keys_before: Set[Tuple[str, str]]
) -> None:
    """Same follow-ups as when an author adds the link by hand. Best effort: the
    link is already saved, and neither step may fail the run."""
    try:
        schedule_invalidate_event_detail_caches(event.id)
    except Exception:
        logger.exception("Event %s: could not invalidate event caches", event.id)
    author = find_author_by_email(db=db, email=event.created_by or "")
    if author is None:
        logger.info(
            "Event %s: creator %s is not an author, live link not copied to the plan day",
            event.id, event.created_by,
        )
        return
    sync_event_youtube_to_plan_day(db, event, previous_keys=keys_before, author=author)


def sync_group_live_streams(
    db: Session,
    group_id: UUID,
    event_ids: Sequence[UUID],
    *,
    now: Optional[datetime] = None,
) -> SyncOutcome:
    """Add the channel's live-now streams to the given events of the group.

    Raises YoutubeChannelError when the channel cannot be read."""
    now = now or datetime.now(timezone.utc)
    outcome = SyncOutcome()

    channel_url = _group_channel_url(db, group_id)
    if channel_url is None:
        raise YoutubeChannelError("The group has no YouTube channel link")

    live = [v for v in fetch_channel_live_videos(channel_url) if v.status == "live"]
    outcome.live_streams_found = len(live)
    if not live:
        return outcome

    events = _chosen_events(db, group_id, event_ids, now)
    outcome.events_checked = len(events)
    missing: Dict[UUID, List[YoutubeLiveVideo]] = {}
    for event in events:
        have = _existing_video_ids(event)
        todo = [video for video in live if video.id not in have]
        if todo:
            missing[event.id] = todo
    if not missing:
        return outcome

    needed = {video.id: video for videos in missing.values() for video in videos}
    languages = suggest_live_stream_languages(
        {video_id: video.title for video_id, video in needed.items()}
    )

    keys_before: Dict[UUID, Set[Tuple[str, str]]] = {}
    changed: List[Event] = []
    for event in events:
        added_here = 0
        for video in missing.get(event.id, []):
            language = languages.get(video.id)
            if language is None:
                outcome.skipped_unknown_language += 1
                logger.info(
                    "Event %s: live stream %s not added, language unclear from its title",
                    event.id, video.id,
                )
                continue
            if added_here == 0:
                keys_before[event.id] = youtube_video_keys_of_event(event)
            db.add(
                EventLink(
                    event_id=event.id,
                    type=EventLinkType.YOUTUBE.value,
                    url=video.url,
                    label=video.title[:_MAX_LABEL_LENGTH],
                    language=language,
                    display_order=_next_youtube_display_order(event) + added_here,
                )
            )
            added_here += 1
        if added_here:
            outcome.links_added += added_here
            changed.append(event)
    if changed:
        db.commit()
        for event in changed:
            _after_links_added(db, event, keys_before[event.id])
    return outcome


# --------------------------------------------------------------- scheduling


def _record_outcome(
    event_ids: Sequence[UUID], *, outcome: Optional[SyncOutcome], error: Optional[str]
) -> None:
    with SessionLocal() as db:
        db.execute(
            update(EventYoutubeLiveSync)
            .where(EventYoutubeLiveSync.event_id.in_(list(event_ids)))
            .values(
                last_run_at=datetime.now(timezone.utc),
                last_run_added=outcome.links_added if outcome else None,
                last_run_error=error[:_MAX_ERROR_LENGTH] if error else None,
            )
        )
        db.commit()


def run_group_sync(group_id: UUID, event_ids: Sequence[UUID]) -> Optional[SyncOutcome]:
    """One run for the due events of one group, in its own session. A failed
    run is logged and recorded on the schedules rather than raised."""
    try:
        with SessionLocal() as db:
            outcome = sync_group_live_streams(db, group_id, event_ids)
    except YoutubeChannelError as error:
        logger.warning("YouTube live sync for group %s: %s", group_id, error)
        _record_outcome(event_ids, outcome=None, error=str(error))
        return None
    except Exception as error:
        logger.exception("YouTube live sync for group %s failed", group_id)
        _record_outcome(event_ids, outcome=None, error=f"{type(error).__name__}: {error}")
        return None
    _record_outcome(event_ids, outcome=outcome, error=None)
    if outcome.links_added:
        logger.info(
            "YouTube live sync for group %s added %s link(s)", group_id, outcome.links_added
        )
    return outcome


def _claim_slot(db: Session, schedule_id: UUID, slot: datetime) -> bool:
    """Take this scheduled moment for this instance. The compare and the
    advance are one UPDATE, so of several app instances waking at once exactly
    one gets a row back."""
    result = db.execute(
        update(EventYoutubeLiveSync)
        .where(
            EventYoutubeLiveSync.id == schedule_id,
            or_(
                EventYoutubeLiveSync.last_slot_at.is_(None),
                EventYoutubeLiveSync.last_slot_at < slot,
            ),
        )
        .values(last_slot_at=slot)
    )
    db.commit()
    return result.rowcount == 1


def run_due_youtube_live_syncs() -> int:
    """Scheduler entry point: run every schedule whose chosen time has come.

    Waking up is a single cheap query; YouTube and Gemini are only called when
    something is due, once per group however many of its events are. Returns
    how many events were run."""
    now = datetime.now(timezone.utc)
    grace = max(config.get_int("YOUTUBE_LIVE_SYNC_GRACE_SECONDS"), 0)

    due: Dict[UUID, List[UUID]] = defaultdict(list)
    with SessionLocal() as db:
        schedules = (
            db.query(
                EventYoutubeLiveSync.id,
                EventYoutubeLiveSync.group_id,
                EventYoutubeLiveSync.event_id,
                EventYoutubeLiveSync.run_times,
                EventYoutubeLiveSync.timezone,
                EventYoutubeLiveSync.last_slot_at,
            )
            .filter(EventYoutubeLiveSync.enabled.is_(True))
            .all()
        )
        for schedule_id, group_id, event_id, run_times, tz_name, last_slot_at in schedules:
            slot = due_slot(run_times or [], tz_name, now, last_slot_at, grace)
            if slot is not None and _claim_slot(db, schedule_id, slot):
                due[group_id].append(event_id)

    for group_id, event_ids in due.items():
        # One group's failure (even to record it) must not skip the others.
        try:
            run_group_sync(group_id, event_ids)
        except Exception:
            logger.exception("YouTube live sync for group %s could not be recorded", group_id)
    return sum(len(event_ids) for event_ids in due.values())


# ------------------------------------------------------------ CMS settings


def _authorize(db: Session, token: str, group_id: UUID, *, write: bool):
    author = validate_and_extract_author_details(token=token)
    exists = (
        db.query(AuthorGroup.id)
        .filter(AuthorGroup.id == group_id, AuthorGroup.deleted_at.is_(None))
        .first()
    )
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_GROUP_NOT_FOUND)
    if write:
        require_cms_write_access(author)
        require_group_member(db=db, group_id=group_id, author=author, allowed_roles=_SETTINGS_ROLES)
    else:
        require_can_read_group_content(db=db, group_id=group_id, author=author)
    return author


def _require_events_in_group(db: Session, group_id: UUID, event_ids: Sequence[UUID]) -> None:
    found = {
        row[0]
        for row in db.query(Event.id)
        .filter(Event.id.in_(list(event_ids)), Event.group_id == group_id)
        .all()
    }
    if found != set(event_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_EVENT_NOT_FOUND)


def _to_schedule_dto(schedule: EventYoutubeLiveSync) -> YoutubeLiveSyncScheduleDTO:
    return YoutubeLiveSyncScheduleDTO(
        event_id=str(schedule.event_id),
        enabled=bool(schedule.enabled),
        run_times=list(schedule.run_times or []),
        timezone=effective_timezone_name(schedule.timezone),
        last_run_at=schedule.last_run_at,
        last_run_added=schedule.last_run_added,
        last_run_error=schedule.last_run_error,
    )


def _list_dto(db: Session, group_id: UUID) -> YoutubeLiveSyncListDTO:
    schedules = (
        db.query(EventYoutubeLiveSync)
        .filter(EventYoutubeLiveSync.group_id == group_id)
        .order_by(EventYoutubeLiveSync.created_at)
        .all()
    )
    return YoutubeLiveSyncListDTO(
        group_id=str(group_id),
        channel_url=_group_channel_url(db, group_id),
        schedules=[_to_schedule_dto(schedule) for schedule in schedules],
    )


def get_youtube_live_sync_service(token: str, group_id: UUID) -> YoutubeLiveSyncListDTO:
    with SessionLocal() as db:
        _authorize(db, token, group_id, write=False)
        return _list_dto(db, group_id)


def update_youtube_live_sync_service(
    token: str, group_id: UUID, request: UpdateYoutubeLiveSyncRequest
) -> YoutubeLiveSyncListDTO:
    with SessionLocal() as db:
        author = _authorize(db, token, group_id, write=True)
        _require_events_in_group(db, group_id, request.event_ids)
        now = datetime.now(timezone.utc)
        # Saving never fires a time that has already passed today; only the
        # times still ahead run on their own. "Run now" is for the rest.
        past = latest_slot_at_or_before(request.run_times, request.timezone, now)
        existing = {
            schedule.event_id: schedule
            for schedule in db.query(EventYoutubeLiveSync)
            .filter(EventYoutubeLiveSync.event_id.in_(request.event_ids))
            .all()
        }
        for event_id in request.event_ids:
            schedule = existing.get(event_id)
            if schedule is None:
                schedule = EventYoutubeLiveSync(
                    event_id=event_id,
                    group_id=group_id,
                    created_at=now,
                    created_by=author.email,
                )
                db.add(schedule)
            schedule.enabled = request.enabled
            schedule.run_times = list(request.run_times)
            schedule.timezone = request.timezone
            schedule.updated_at = now
            schedule.updated_by = author.email
            if past is not None and (
                schedule.last_slot_at is None
                or schedule.last_slot_at.astimezone(timezone.utc) < past
            ):
                schedule.last_slot_at = past
        db.commit()
        return _list_dto(db, group_id)


def delete_youtube_live_sync_service(token: str, group_id: UUID, event_id: UUID) -> None:
    with SessionLocal() as db:
        _authorize(db, token, group_id, write=True)
        deleted = (
            db.query(EventYoutubeLiveSync)
            .filter(
                EventYoutubeLiveSync.event_id == event_id,
                EventYoutubeLiveSync.group_id == group_id,
            )
            .delete()
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_SCHEDULE_NOT_FOUND)
        db.commit()


def run_youtube_live_sync_now_service(
    token: str, group_id: UUID, request: RunYoutubeLiveSyncRequest
) -> YoutubeLiveSyncRunDTO:
    with SessionLocal() as db:
        _authorize(db, token, group_id, write=True)
        _require_events_in_group(db, group_id, request.event_ids)
        try:
            outcome = sync_group_live_streams(db, group_id, request.event_ids)
        except YoutubeChannelError as error:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
    return YoutubeLiveSyncRunDTO(
        live_streams_found=outcome.live_streams_found,
        events_checked=outcome.events_checked,
        links_added=outcome.links_added,
        skipped_unknown_language=outcome.skipped_unknown_language,
    )
