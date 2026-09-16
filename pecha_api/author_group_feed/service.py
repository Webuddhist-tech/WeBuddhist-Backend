from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from pecha_api.config import get
from pecha_api.events.event_participant_repository import (
    get_event_participant_counts,
    get_joined_event_ids_by_user,
    get_participation_types_by_user,
)
from pecha_api.events.event_repository import get_events, get_recurring_events
from pecha_api.events.event_service import _event_to_dto
from pecha_api.events.recurrence_service import (
    resolve_current_or_next_occurrence,
    combine_occurrence_window,
)
from pecha_api.group_posts.enums import GroupPostStatus
from pecha_api.group_posts.repository import get_posts_for_group_ids
from pecha_api.group_posts.service import build_post_dtos
from pecha_api.plans.groups.groups_models import AuthorGroup
from pecha_api.plans.groups.follow_scope import resolve_public_group_scope
from pecha_api.plans.groups.groups_repository import get_groups_by_ids
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.users.users_service import validate_and_extract_user_details

from pecha_api.author_group_feed.response_models import (
    AuthorGroupFeedItemDTO,
    AuthorGroupFeedItemType,
    AuthorGroupFeedResponse,
)


def _as_aware_utc(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    return _as_aware_utc(value).isoformat()


def _group_avatar_url(avatar_key: Optional[str]) -> Optional[str]:
    if not avatar_key:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=avatar_key,
        )
    except Exception:
        return None


def _group_display_name(group: AuthorGroup, language: Optional[str] = None) -> str:
    entries = group.metadata_entries or []
    if not entries:
        return group.slug or "Group"

    def _lang(entry) -> str:
        value = entry.language
        return value.value if hasattr(value, "value") else str(value)

    if language:
        requested = language.upper()
        for entry in entries:
            if _lang(entry).upper() == requested:
                return entry.title

    for entry in entries:
        if _lang(entry).upper() == "EN":
            return entry.title
    return entries[0].title


def _build_group_card_map(
    db: Session,
    group_ids: List[UUID],
    language: Optional[str],
) -> Dict[UUID, dict]:
    groups = get_groups_by_ids(db=db, group_ids=group_ids)
    return {
        group.id: {
            "group_id": group.id,
            "group_name": _group_display_name(group, language=language),
            "group_slug": group.slug,
            "group_avatar_url": _group_avatar_url(group.avatar_key),
        }
        for group in groups
    }


def _expand_recurring_occurrences(recurring_templates, today) -> List[Dict]:
    """The current (active) or next upcoming occurrence per recurring template.

    Templates with no occurrence in the resolver's horizon are dropped, so the
    result is not parallel to the input.
    """
    expanded_recurring = []
    for template in recurring_templates:
        result = resolve_current_or_next_occurrence(template, after=today)
        if not result:
            continue
        start_d, end_d, is_active = result
        # Carry the template's own time-of-day onto the occurrence,
        # instead of defaulting to midnight / end-of-day.
        occurrence_start, occurrence_end = combine_occurrence_window(
            start_d, end_d, template.start_date, template.end_date
        )
        expanded_recurring.append({
            'event': template,
            'start_date': occurrence_start,
            'end_date': occurrence_end,
            'is_active': is_active,
        })
    return expanded_recurring


def _get_author_group_feed(
    db: Session,
    token: Optional[str],
    should_include_unfollowed: bool,
    skip: int = 0,
    limit: int = 20,
    language: Optional[str] = None,
) -> AuthorGroupFeedResponse:
    """Mixed feed of posts and events from author groups.

    Guests (no token) always see published public groups.
    Logged-in default: groups the user joined.
    With should_include_unfollowed=True: mix in other public groups.
    """
    current_user = None
    if token:
        current_user = validate_and_extract_user_details(token=token)

    group_ids, joined_group_id_set = resolve_public_group_scope(
        db=db,
        user_id=current_user.id if current_user else None,
        should_include_unfollowed=should_include_unfollowed,
    )

    if not group_ids:
        return AuthorGroupFeedResponse(
            items=[],
            skip=skip,
            limit=limit,
            total=0,
            should_include_unfollowed=should_include_unfollowed,
        )

    # Fetch enough of each type to fill the requested page after merge.
    fetch_limit = skip + limit

    posts, posts_total = get_posts_for_group_ids(
        db=db,
        group_ids=group_ids,
        skip=0,
        limit=fetch_limit,
        status=GroupPostStatus.PUBLISHED,
    )
    post_dtos = build_post_dtos(
        db, posts, user_id=current_user.id if current_user else None
    )

    # Get one-shot events
    one_shot_events, one_shot_total = get_events(
        db=db,
        restrict_group_ids=group_ids,
        skip=0,
        limit=fetch_limit,
        should_sort_newest_first=True,
    )
    
    # Get recurring events and find next occurrence for each template
    recurring_templates = get_recurring_events(
        db=db,
        restrict_group_ids=group_ids,
    )
    
    # For feed context, show the current (active) or next upcoming occurrence per template.
    # Use resolve_current_or_next_occurrence (5-year horizon) to handle sparse yearly
    # recurrences like Feb 29 and include active multi-day occurrences.
    now = datetime.now(timezone.utc)
    today = now.date()
    
    expanded_recurring = _expand_recurring_occurrences(recurring_templates, today)
    
    # Combine one-shot events with next occurrences of recurring templates
    events = one_shot_events
    events_total = one_shot_total + len(expanded_recurring)
    event_ids = [event.id for event in events] + [item['event'].id for item in expanded_recurring]
    counts_by_event = get_event_participant_counts(db=db, event_ids=event_ids)
    joined_event_ids: Set[UUID] = set()
    participation_types: Dict[UUID, str] = {}
    if current_user:
        joined_event_ids = set(
            get_joined_event_ids_by_user(
                db=db,
                user_id=current_user.id,
                event_ids=event_ids,
            )
        )
        if joined_event_ids:
            participation_types = get_participation_types_by_user(
                db=db,
                user_id=current_user.id,
                event_ids=list(joined_event_ids),
            )

    page_group_ids = list({
        *[post.group_id for post in posts],
        *[event.group_id for event in events],
        *[item['event'].group_id for item in expanded_recurring],
    })
    group_cards = _build_group_card_map(db, page_group_ids, language)

    cards: List[Tuple[datetime, AuthorGroupFeedItemDTO]] = []

    for post, post_dto in zip(posts, post_dtos):
        feed_at = _as_aware_utc(post.published_at)
        group_info = group_cards.get(post.group_id, {})
        cards.append(
            (
                feed_at,
                AuthorGroupFeedItemDTO(
                    type=AuthorGroupFeedItemType.POST,
                    feed_at=_isoformat(feed_at),
                    is_joined=post.group_id in joined_group_id_set,
                    group_id=post.group_id,
                    group_name=group_info.get("group_name"),
                    group_slug=group_info.get("group_slug"),
                    group_avatar_url=group_info.get("group_avatar_url"),
                    post=post_dto,
                ),
            )
        )

    # Add one-shot events to feed
    for event in events:
        feed_at = _as_aware_utc(event.created_at)
        group_info = group_cards.get(event.group_id, {})
        cards.append(
            (
                feed_at,
                AuthorGroupFeedItemDTO(
                    type=AuthorGroupFeedItemType.EVENT,
                    feed_at=_isoformat(feed_at),
                    is_joined=event.group_id in joined_group_id_set,
                    group_id=event.group_id,
                    group_name=group_info.get("group_name"),
                    group_slug=group_info.get("group_slug"),
                    group_avatar_url=group_info.get("group_avatar_url"),
                    event=_event_to_dto(
                        event,
                        language=language,
                        participant_count=counts_by_event.get(event.id, 0),
                        is_joined=event.id in joined_event_ids,
                        my_participation_type=participation_types.get(event.id),
                    ),
                ),
            )
        )
    
    # Add expanded recurring event occurrences to feed.
    # Non-active (not yet started) occurrences are ranked by proximity to "now"
    # rather than by the template's created_at: for a future occurrence,
    # occurrence_date > now > created_at always holds, which made
    # min(created_at, occurrence_date) collapse to created_at and let a
    # freshly-created template with a far-future occurrence outrank genuinely
    # recent content. Mirroring the occurrence date around "now"
    # (now - (occurrence_date - now)) keeps imminent occurrences competitive
    # with recent content while distant ones sink below it. Active events rank
    # by their start_date (not now) so multiple active events don't all tie at
    # the top.
    for item in expanded_recurring:
        event = item['event']
        if item.get('is_active'):
            feed_at = item['start_date']  # Active events rank by when they started
        else:
            occurrence_at = item['start_date']
            feed_at = now - (occurrence_at - now)
        group_info = group_cards.get(event.group_id, {})
        # Temporarily override dates for DTO
        original_start = event.start_date
        original_end = event.end_date
        event.start_date = item['start_date']
        event.end_date = item['end_date']
        cards.append(
            (
                feed_at,
                AuthorGroupFeedItemDTO(
                    type=AuthorGroupFeedItemType.EVENT,
                    feed_at=_isoformat(feed_at),
                    is_joined=event.group_id in joined_group_id_set,
                    group_id=event.group_id,
                    group_name=group_info.get("group_name"),
                    group_slug=group_info.get("group_slug"),
                    group_avatar_url=group_info.get("group_avatar_url"),
                    event=_event_to_dto(
                        event,
                        language=language,
                        participant_count=counts_by_event.get(event.id, 0),
                        is_joined=event.id in joined_event_ids,
                        my_participation_type=participation_types.get(event.id),
                        occurrence_date=item['start_date'],
                    ),
                ),
            )
        )
        event.start_date = original_start
        event.end_date = original_end

    cards.sort(key=lambda entry: (entry[0], entry[1].type.value), reverse=True)
    total = posts_total + events_total
    page = [card for _, card in cards[skip:skip + limit]]

    return AuthorGroupFeedResponse(
        items=page,
        skip=skip,
        limit=limit,
        total=total,
        should_include_unfollowed=should_include_unfollowed,
    )


async def get_author_group_feed_service(
    db: Session,
    token: Optional[str] = None,
    should_include_unfollowed: bool = False,
    skip: int = 0,
    limit: int = 20,
    language: Optional[str] = None,
) -> AuthorGroupFeedResponse:
    """Build the feed without blocking the application's event loop."""
    return await run_in_threadpool(
        _get_author_group_feed,
        db=db,
        token=token,
        should_include_unfollowed=should_include_unfollowed,
        skip=skip,
        limit=limit,
        language=language,
    )
