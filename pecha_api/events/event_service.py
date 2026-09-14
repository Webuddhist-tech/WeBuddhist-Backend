from dataclasses import dataclass
from datetime import datetime, timezone, date, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.timezone_utils import get_day_bounds_in_timezone
from pecha_api.plans.authors.plan_authors_service import (
    safe_get_image_url,
    validate_cms_author_details,
)
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
from pecha_api.plans.groups.groups_repository import get_author_group_ids, get_groups_by_ids
from pecha_api.plans.groups.follow_scope import resolve_public_group_scope
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.group_recitation_collection.repository import get_collection_by_id
from pecha_api.plans.shared.metadata_utils import (
    filter_by_language_with_fallback,
    format_metadata_response,
)
from pecha_api.accumulator.accumulator_service import (
    resolve_mala_image_fields,
    _pick_mantra_metadata,
)
from pecha_api.plans.shared.permissions import (
    require_can_create_content,
    require_can_read_group_content,
    require_cms_write_access,
    require_group_member,
    require_can_change_status,
    is_reviewer,
    is_super_admin,
)
from pecha_api.users.users_service import validate_and_extract_user_details

from .event_model import Event
from .event_enums import EventLinkType
from .event_response_models import (
    CreateEventRequest,
    UpdateEventRequest,
    EventDTO,
    EventFormat,
    EventMetadataDTO,
    EventLinkDTO,
    EventYoutubeDTO,
    EventsResponse,
    LinkedResourceDTO,
    RecurrenceDTO,
    _validate_date_range,
)
from .recurrence_service import (
    compute_initial_dates,
    resolve_next_occurrence,
    resolve_current_or_next_occurrence,
    expand_occurrences,
    combine_date_with_time_of_day,
    combine_occurrence_window,
)
from .notification_dispatch_service import enqueue_event_notification
from .event_reminder_service import (
    cancel_event_reminders,
    reschedule_event_reminders,
    schedule_event_reminders,
)
from .event_repository import (
    save_event,
    get_event_by_id,
    update_event,
    delete_event,
    get_events,
    get_featured_events,
    get_featured_recurring_events,
    get_recurring_events,
)
from .event_participant_repository import (
    get_event_participant_count,
    get_event_participant_counts,
    get_joined_event_ids_by_user,
    is_user_joined_event,
)
from .location_repository import get_location_without_group_filter
from .location_response_models import LocationDTO

_CONTENT_EDIT_ROLES = {
    AuthorGroupMemberRole.OWNER,
    AuthorGroupMemberRole.ADMIN,
    AuthorGroupMemberRole.AUTHOR,
}


def _language_value(language) -> str:
    if hasattr(language, "value"):
        return language.value
    return str(language)


def _metadata_to_dtos(
    entries, language: Optional[str] = None, fallback: bool = False
) -> List[EventMetadataDTO]:
    if not entries:
        return []
    if fallback:
        entries = filter_by_language_with_fallback(
            entries=list(entries),
            language=language,
            language_of=lambda entry: _language_value(entry.language),
        )
    elif language:
        language_upper = language.upper()
        entries = [
            entry for entry in entries
            if _language_value(entry.language).upper() == language_upper
        ]
    return sorted(
        [
            EventMetadataDTO(
                id=entry.id,
                name=entry.name,
                description=entry.description,
                language=_language_value(entry.language),
            )
            for entry in entries
        ],
        key=lambda metadata_dto: metadata_dto.language,
    )


def _metadata_response(entries, language: Optional[str] = None, fallback: bool = False):
    return format_metadata_response(
        _metadata_to_dtos(entries, language=language, fallback=fallback),
        language=language,
    )


def _is_youtube_link(link) -> bool:
    return (link.type or "").strip().lower() == EventLinkType.YOUTUBE.value


def _filter_link_entries(entries: List, language: Optional[str] = None, fallback: bool = False) -> List:
    if not entries:
        return []
    if fallback:
        return filter_by_language_with_fallback(
            entries=list(entries),
            language=language,
            language_of=lambda entry: _language_value(entry.language),
        )
    if language:
        language_upper = language.upper()
        return [
            entry for entry in entries
            if _language_value(entry.language).upper() == language_upper
        ]
    return list(entries)


def _links_to_dtos(
    links: Optional[List], language: Optional[str] = None, fallback: bool = False
) -> List[EventLinkDTO]:
    other_entries = [link for link in (links or []) if not _is_youtube_link(link)]
    filtered = _filter_link_entries(other_entries, language=language, fallback=fallback)
    return [
        EventLinkDTO(
            id=link.id,
            type=link.type,
            url=link.url,
            label=link.label,
            language=_language_value(link.language),
            display_order=link.display_order,
        )
        for link in sorted(filtered, key=lambda link: link.display_order)
    ]


def _youtube_to_dtos(
    links: Optional[List], language: Optional[str] = None, fallback: bool = False
) -> List[EventYoutubeDTO]:
    youtube_entries = [link for link in (links or []) if _is_youtube_link(link)]
    filtered = _filter_link_entries(youtube_entries, language=language, fallback=fallback)
    return [
        EventYoutubeDTO(
            id=link.id,
            url=link.url,
            label=link.label,
            language=_language_value(link.language),
            display_order=link.display_order,
        )
        for link in sorted(filtered, key=lambda link: link.display_order)
    ]


def _location_to_dto(event: Event) -> Optional[LocationDTO]:
    location = event.location
    if location is None:
        return None
    return LocationDTO(
        id=location.id,
        group_id=location.group_id,
        name=location.name,
        latitude=location.latitude,
        longitude=location.longitude,
    )


def _presign_image_url(image_url: Optional[str]) -> Optional[str]:
    if not image_url:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=image_url,
        )
    except Exception:
        return None


def _plan_to_linked_resource(event: Event) -> Optional[LinkedResourceDTO]:
    plan = getattr(event, "plan", None)
    if plan is None:
        return None
    return LinkedResourceDTO(
        id=plan.id,
        name=plan.title,
        image_url=_presign_image_url(plan.image_url),
    )


def _series_to_linked_resource(
    event: Event, language: Optional[str] = None
) -> Optional[LinkedResourceDTO]:
    series = getattr(event, "series", None)
    if series is None:
        return None
    metadata = _pick_mantra_metadata(series.metadata_entries, language)
    return LinkedResourceDTO(
        id=series.id,
        name=metadata.title if metadata else None,
        image_url=_presign_image_url(series.image),
    )


def _accumulator_to_linked_resource(
    event: Event, language: Optional[str] = None
) -> Optional[LinkedResourceDTO]:
    accumulator = getattr(event, "accumulator", None)
    if accumulator is None:
        return None
    metadata = _pick_mantra_metadata(accumulator.metadata_entries, language)
    _, mala_image_url = resolve_mala_image_fields(accumulator)
    return LinkedResourceDTO(
        id=accumulator.id,
        name=metadata.name if metadata else None,
        image_url=mala_image_url,
    )


def _group_accumulator_to_linked_resource(
    event: Event,
) -> Optional[LinkedResourceDTO]:
    group_accumulator = getattr(event, "group_accumulator", None)
    if group_accumulator is None:
        return None
    return LinkedResourceDTO(
        id=group_accumulator.id,
        name=group_accumulator.title,
        image_url=_presign_image_url(group_accumulator.image_key),
    )


def _mantra_to_linked_resource(
    event: Event, language: Optional[str] = None
) -> Optional[LinkedResourceDTO]:
    mantra = getattr(event, "mantra", None)
    if mantra is None:
        return None
    metadata = _pick_mantra_metadata(mantra.metadata_entries, language)
    _, mala_image_url = resolve_mala_image_fields(mantra)
    return LinkedResourceDTO(
        id=mantra.id,
        name=metadata.title if metadata else None,
        image_url=mala_image_url,
    )


def _timer_to_linked_resource(event: Event) -> Optional[LinkedResourceDTO]:
    timer = getattr(event, "timer", None)
    if timer is None:
        return None
    return LinkedResourceDTO(id=timer.id, name=timer.name, image_url=None)


def _group_recitation_collection_to_linked_resource(
    event: Event,
) -> Optional[LinkedResourceDTO]:
    collection = getattr(event, "group_recitation_collection", None)
    if collection is None:
        return None
    return LinkedResourceDTO(
        id=collection.id,
        name=collection.name,
        image_url=_presign_image_url(collection.img_url),
    )


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


def _group_display_name(group) -> Optional[str]:
    entries = group.metadata_entries or []
    if not entries:
        return group.slug

    def _lang(entry) -> str:
        value = entry.language
        return value.value if hasattr(value, "value") else str(value)

    for entry in entries:
        if _lang(entry).upper() == "EN":
            return entry.title
    return entries[0].title


def _group_card_map(db, group_ids: List[UUID]) -> dict:
    """Map group_id -> (group_name, group_avatar_url), batched."""
    groups = get_groups_by_ids(db=db, group_ids=list(set(group_ids)))
    return {
        group.id: (_group_display_name(group), _group_avatar_url(group.avatar_key))
        for group in groups
    }


def _display_occurrence_for_event(
    event: Event,
) -> tuple[datetime, datetime, Optional[datetime]]:
    """Dates to surface on event detail so they match the list.

    Recurring templates store a rule plus a time-of-day, not necessarily the
    next occurrence. List endpoints expand that rule; detail must do the same
    or the two screens disagree about the start date.
    """
    if not event.is_recurring:
        return event.start_date, event.end_date, None

    now = datetime.now(timezone.utc)
    from_date = now.date()
    to_date = (now + timedelta(days=365)).date()
    occurrences = expand_occurrences(event, from_date, to_date)
    if occurrences:
        start_d, end_d = occurrences[0]
    else:
        result = resolve_current_or_next_occurrence(event, after=from_date)
        if not result:
            return event.start_date, event.end_date, None
        start_d, end_d, _is_active = result

    start, end = combine_occurrence_window(
        start_d, end_d, event.start_date, event.end_date
    )
    return start, end, start


def _event_to_dto(
    event: Event,
    language: Optional[str] = None,
    fallback: bool = False,
    participant_count: int = 0,
    is_joined: Optional[bool] = None,
    group_name: Optional[str] = None,
    group_avatar_url: Optional[str] = None,
    occurrence_date: Optional[datetime] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> EventDTO:
    recurrence_dto = None
    if event.is_recurring:
        recurrence_dto = RecurrenceDTO(
            frequency=event.recurrence_frequency,
            date_system=event.recurrence_date_system,
            calendar_type=event.recurrence_calendar_type,
            month=event.recurrence_month,
            day=event.recurrence_day,
            day_of_week=event.recurrence_day_of_week,
            duration_days=event.duration_days,
        )

    dto_start = start_date if start_date is not None else event.start_date
    dto_end = end_date if end_date is not None else event.end_date
    
    return EventDTO(
        id=event.id,
        plan_id=event.plan_id,
        plan=_plan_to_linked_resource(event),
        series_id=getattr(event, "series_id", None),
        series=_series_to_linked_resource(event, language=language),
        accumulator_id=event.accumulator_id,
        accumulator=_accumulator_to_linked_resource(event, language=language),
        group_accumulator_id=getattr(event, "group_accumulator_id", None),
        group_accumulator=_group_accumulator_to_linked_resource(event),
        mantra_id=event.mantra_id,
        mantra=_mantra_to_linked_resource(event, language=language),
        timer_id=event.timer_id,
        timer=_timer_to_linked_resource(event),
        group_recitation_collection_id=event.group_recitation_collection_id,
        group_recitation_collection=_group_recitation_collection_to_linked_resource(event),
        group_id=event.group_id,
        location_id=event.location_id,
        location=_location_to_dto(event),
        start_date=dto_start,
        end_date=dto_end,
        timezone=getattr(event, "timezone", None),
        is_one_day=dto_end.date() == dto_start.date(),
        featured=event.featured,
        is_recurring=event.is_recurring,
        recurrence=recurrence_dto,
        occurrence_date=occurrence_date,
        event_format=event.event_format,
        metadata=_metadata_response(
            event.metadata_entries, language=language, fallback=fallback
        ),
        youtube=_youtube_to_dtos(event.links, language=language, fallback=fallback),
        links=_links_to_dtos(event.links, language=language, fallback=fallback),
        image=safe_get_image_url(
            event.image_url, resource_id=event.id, resource_type="event"
        ),
        image_url=event.image_url,
        group_name=group_name,
        group_avatar_url=group_avatar_url,
        participant_count=participant_count,
        is_joined=is_joined,
        created_at=event.created_at,
        created_by=event.created_by,
        updated_at=event.updated_at,
    )


def _require_can_edit_event(db, group_id: UUID, author) -> None:
    require_cms_write_access(author)
    if is_super_admin(author):
        return
    require_group_member(
        db=db,
        group_id=group_id,
        author=author,
        allowed_roles=_CONTENT_EDIT_ROLES,
    )


def _validate_group_recitation_collection(
    db, collection_id: Optional[UUID], group_id: UUID
) -> None:
    if collection_id is None:
        return
    collection = get_collection_by_id(
        db=db, collection_id=collection_id, group_id=group_id
    )
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Group recitation collection '{collection_id}' not found "
                f"or does not belong to group '{group_id}'"
            ),
        )


def _validate_location(db, location_id: Optional[UUID], group_id: UUID) -> None:
    if location_id is None:
        return
    location = get_location_without_group_filter(db=db, location_id=location_id)
    if location is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with id '{location_id}' not found",
        )
    if location.group_id != group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "LOCATION_GROUP_MISMATCH",
                "message": (
                    f"Location '{location_id}' does not belong to group '{group_id}'"
                ),
            },
        )


@dataclass(frozen=True)
class EventContentFilter:
    """Which content association(s) events must be linked to, for querying."""
    group_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    accumulator_id: Optional[UUID] = None
    mantra_id: Optional[UUID] = None
    timer_id: Optional[UUID] = None
    group_recitation_collection_id: Optional[UUID] = None
    event_format: Optional[EventFormat] = None


def get_events_service(
    content_filter: Optional[EventContentFilter] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    language: Optional[str] = None,
    restrict_group_ids: Optional[List[UUID]] = None,
    fallback: bool = False,
    should_include_unfollowed: bool = False,
    skip: int = 0,
    limit: int = 20,
    token: Optional[str] = None,
) -> EventsResponse:
    content_filter = content_filter or EventContentFilter()
    with SessionLocal() as db:
        current_user = None
        if token:
            current_user = validate_and_extract_user_details(token=token)
            if restrict_group_ids is None:
                restrict_group_ids, _ = resolve_public_group_scope(
                    db=db,
                    user_id=current_user.id,
                    should_include_unfollowed=should_include_unfollowed,
                )

        # Default expansion window: rolling 12 months from today
        if from_date is None:
            from_date = datetime.now(timezone.utc)
        if to_date is None:
            to_date = from_date + timedelta(days=365)
        
        # Convert to date objects for recurrence expansion
        from_date_obj = from_date.date() if isinstance(from_date, datetime) else from_date
        to_date_obj = to_date.date() if isinstance(to_date, datetime) else to_date

        # Get all one-shot events for merged pagination with recurring occurrences
        # Note: We need all events to properly merge and paginate with recurring occurrences
        one_shot_events, _ = get_events(
            db,
            group_id=content_filter.group_id,
            plan_id=content_filter.plan_id,
            accumulator_id=content_filter.accumulator_id,
            mantra_id=content_filter.mantra_id,
            timer_id=content_filter.timer_id,
            group_recitation_collection_id=content_filter.group_recitation_collection_id,
            event_format=content_filter.event_format,
            from_date=from_date,
            to_date=to_date,
            restrict_group_ids=restrict_group_ids,
            skip=0,
            limit=None,
        )

        # Get recurring event templates
        recurring_templates = get_recurring_events(
            db,
            group_id=content_filter.group_id,
            plan_id=content_filter.plan_id,
            accumulator_id=content_filter.accumulator_id,
            mantra_id=content_filter.mantra_id,
            timer_id=content_filter.timer_id,
            group_recitation_collection_id=content_filter.group_recitation_collection_id,
            event_format=content_filter.event_format,
            restrict_group_ids=restrict_group_ids,
        )
        
        # Expand recurring events, keeping only each template's earliest
        # occurrence within the window so a single recurring event surfaces
        # once per listing instead of once per occurrence (e.g. 12 rows for
        # a monthly recurrence over the default 12-month window).
        expanded_occurrences = []
        for template in recurring_templates:
            occurrences = expand_occurrences(template, from_date_obj, to_date_obj)
            if not occurrences:
                continue
            start_d, end_d = occurrences[0]
            # Carry the template's own time-of-day onto the occurrence,
            # instead of defaulting to midnight / end-of-day.
            occurrence_start, occurrence_end = combine_occurrence_window(
                start_d, end_d, template.start_date, template.end_date
            )
            expanded_occurrences.append({
                'event': template,
                'start_date': occurrence_start,
                'end_date': occurrence_end,
                'occurrence_date': occurrence_start,
            })
        
        # Merge one-shot events and expanded occurrences
        all_event_items = [
            {'event': e, 'start_date': e.start_date, 'end_date': e.end_date, 'occurrence_date': None}
            for e in one_shot_events
        ] + expanded_occurrences
        
        # Sort by start_date
        all_event_items.sort(key=lambda x: x['start_date'])
        
        # Apply pagination
        total = len(all_event_items)
        paginated_items = all_event_items[skip:skip + limit]
        
        # Get participant counts for all unique event IDs
        event_ids = list({item['event'].id for item in paginated_items})
        counts_by_event = get_event_participant_counts(db=db, event_ids=event_ids)
        group_ids = list({item['event'].group_id for item in paginated_items})
        group_cards = _group_card_map(db, group_ids)

        joined_ids: set[UUID] = set()
        if current_user:
            joined_ids = set(
                get_joined_event_ids_by_user(
                    db=db,
                    user_id=current_user.id,
                    event_ids=event_ids,
                )
            )

        # Build DTOs with occurrence-specific dates
        event_dtos = []
        for item in paginated_items:
            event = item['event']
            event_dtos.append(
                _event_to_dto(
                    event,
                    language=language,
                    fallback=fallback,
                    participant_count=counts_by_event.get(event.id, 0),
                    is_joined=(event.id in joined_ids) if current_user else None,
                    group_name=group_cards.get(event.group_id, (None, None))[0],
                    group_avatar_url=group_cards.get(event.group_id, (None, None))[1],
                    occurrence_date=item['occurrence_date'],
                    start_date=item['start_date'],
                    end_date=item['end_date'],
                )
            )

        return EventsResponse(
            events=event_dtos,
            total=total,
            skip=skip,
            limit=limit,
        )


def get_cms_events_service(
    token: str,
    group_id: Optional[UUID] = None,
    plan_id: Optional[UUID] = None,
    accumulator_id: Optional[UUID] = None,
    mantra_id: Optional[UUID] = None,
    timer_id: Optional[UUID] = None,
    group_recitation_collection_id: Optional[UUID] = None,
    event_format: Optional[EventFormat] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> EventsResponse:
    current_author = validate_cms_author_details(token=token)

    restrict_group_ids: Optional[List[UUID]] = None
    if not is_super_admin(current_author) and not is_reviewer(current_author):
        with SessionLocal() as db:
            member_group_ids = get_author_group_ids(db=db, author_id=current_author.id)
        if not member_group_ids:
            return EventsResponse(events=[], total=0, skip=skip, limit=limit)
        restrict_group_ids = member_group_ids

    return get_events_service(
        content_filter=EventContentFilter(
            group_id=group_id,
            plan_id=plan_id,
            accumulator_id=accumulator_id,
            mantra_id=mantra_id,
            timer_id=timer_id,
            group_recitation_collection_id=group_recitation_collection_id,
            event_format=event_format,
        ),
        from_date=from_date,
        to_date=to_date,
        language=language,
        restrict_group_ids=restrict_group_ids,
        skip=skip,
        limit=limit,
    )


def get_cms_event_by_id_service(
    token: str, event_id: UUID, language: Optional[str] = None
) -> EventDTO:
    current_author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        event = get_event_by_id(db, event_id)
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event with id '{event_id}' not found",
            )
        require_can_read_group_content(db=db, group_id=event.group_id, author=current_author)
        participant_count = get_event_participant_count(db=db, event_id=event_id)
        start_date, end_date, occurrence_date = _display_occurrence_for_event(event)
        return _event_to_dto(
            event,
            language=language,
            participant_count=participant_count,
            occurrence_date=occurrence_date,
            start_date=start_date,
            end_date=end_date,
        )


def get_events_today_service(
    timezone: Optional[str] = None,
    group_id: Optional[UUID] = None,
    language: Optional[str] = None,
    should_include_unfollowed: bool = False,
    skip: int = 0,
    limit: int = 20,
    token: Optional[str] = None,
) -> EventsResponse:
    from_date, to_date = get_day_bounds_in_timezone(timezone)
    return get_events_service(
        content_filter=EventContentFilter(group_id=group_id),
        from_date=from_date,
        to_date=to_date,
        language=language,
        fallback=True,
        should_include_unfollowed=should_include_unfollowed,
        skip=skip,
        limit=limit,
        token=token,
    )


def get_event_by_id_service(
    event_id: UUID,
    language: Optional[str] = None,
    token: Optional[str] = None,
) -> EventDTO:
    with SessionLocal() as db:
        event = get_event_by_id(db, event_id)
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event with id '{event_id}' not found",
            )
        participant_count = get_event_participant_count(db=db, event_id=event_id)
        is_joined = None
        if token:
            current_user = validate_and_extract_user_details(token=token)
            is_joined = is_user_joined_event(
                db=db, event_id=event_id, user_id=current_user.id
            )
        group_name, group_avatar_url = _group_card_map(db, [event.group_id]).get(
            event.group_id, (None, None)
        )
        start_date, end_date, occurrence_date = _display_occurrence_for_event(event)
        return _event_to_dto(
            event,
            language=language,
            fallback=True,
            participant_count=participant_count,
            is_joined=is_joined,
            group_name=group_name,
            group_avatar_url=group_avatar_url,
            occurrence_date=occurrence_date,
            start_date=start_date,
            end_date=end_date,
        )


def create_event_service(token: str, request: CreateEventRequest) -> EventDTO:
    current_author = validate_cms_author_details(token=token)

    if request.recurrence:
        start_date, end_date = compute_initial_dates(request.recurrence)
        # The recurrence rule only pins a day/month; the time-of-day rides
        # along on start_date/end_date if the client sent them.
        if request.start_date is not None:
            start_date = combine_date_with_time_of_day(start_date.date(), request.start_date)
        if request.end_date is not None:
            end_date = combine_date_with_time_of_day(end_date.date(), request.end_date)
        # A single-day occurrence (duration_days == 1) lands both times on the
        # same calendar day, so an end time earlier than the start time would
        # otherwise persist as an inverted range once expanded for reads.
        _validate_date_range(start_date, end_date)
        is_recurring = True
        recurrence_frequency = request.recurrence.frequency.value
        recurrence_date_system = request.recurrence.date_system.value
        recurrence_calendar_type = request.recurrence.calendar_type
        recurrence_month = request.recurrence.month
        recurrence_day = request.recurrence.day
        recurrence_day_of_week = request.recurrence.day_of_week
        duration_days = request.recurrence.duration_days
    else:
        start_date = request.start_date
        end_date = request.end_date
        is_recurring = False
        recurrence_frequency = None
        recurrence_date_system = None
        recurrence_calendar_type = None
        recurrence_month = None
        recurrence_day = None
        recurrence_day_of_week = None
        duration_days = 1

    event = Event(
        plan_id=request.plan_id,
        series_id=request.series_id,
        accumulator_id=request.accumulator_id,
        group_accumulator_id=request.group_accumulator_id,
        mantra_id=request.mantra_id,
        timer_id=request.timer_id,
        group_recitation_collection_id=request.group_recitation_collection_id,
        group_id=request.group_id,
        location_id=request.location_id,
        start_date=start_date,
        end_date=end_date,
        timezone=request.timezone,
        image_url=request.image_url,
        event_format=request.event_format,
        is_recurring=is_recurring,
        recurrence_frequency=recurrence_frequency,
        recurrence_date_system=recurrence_date_system,
        recurrence_calendar_type=recurrence_calendar_type,
        recurrence_month=recurrence_month,
        recurrence_day=recurrence_day,
        recurrence_day_of_week=recurrence_day_of_week,
        duration_days=duration_days,
        created_by=current_author.email,
    )

    with SessionLocal() as db:
        require_can_create_content(
            db=db,
            group_id=request.group_id,
            author=current_author,
        )
        _validate_group_recitation_collection(
            db=db,
            collection_id=request.group_recitation_collection_id,
            group_id=request.group_id,
        )
        _validate_location(
            db=db, location_id=request.location_id, group_id=request.group_id
        )
        def _schedule_reminders_after_flush(flushed_event: Event) -> None:
            # Runs after the event is flushed (so its id/FK target exists)
            # but before save_event's commit, so a reminder failure rolls
            # back the event too instead of leaving it persisted without
            # reminders.
            if not is_recurring:
                schedule_event_reminders(db, flushed_event.id, flushed_event.start_date)

        saved = save_event(
            db, event, request.metadata, request.links,
            youtube_entries=request.youtube,
            after_flush=_schedule_reminders_after_flush,
        )
        enqueue_event_notification(saved.id)
        return _event_to_dto(saved)


def _resolve_recurrence_time_window(
    event: Event,
    request: UpdateEventRequest,
    start_date: datetime,
    end_date: datetime,
) -> tuple[datetime, datetime]:
    """Combine a freshly-resolved recurrence occurrence with its time-of-day.

    The recurrence rule only pins a day/month; the time-of-day rides along
    on start_date/end_date if the client sent them, falling back to the
    event's own current time-of-day when it didn't — otherwise every
    recurrence update would silently reset a timed event to midnight.
    """
    start_time_source = (
        request.start_date if request.start_date is not None else event.start_date
    )
    end_time_source = (
        request.end_date if request.end_date is not None else event.end_date
    )
    start_date = combine_date_with_time_of_day(start_date.date(), start_time_source)
    end_date = combine_date_with_time_of_day(end_date.date(), end_time_source)

    if request.start_date is not None or request.end_date is not None:
        # The author supplied new time-of-day input, so an inverted window
        # is theirs to fix — reject it outright.
        _validate_date_range(start_date, end_date)
    elif end_date < start_date:
        # Both times were inherited from the existing template. A
        # recurrence-only update (e.g. changing the day) that happens to
        # inherit an already-invalid legacy window (a one-day occurrence
        # whose end time preceded its start time, from before this
        # validation existed) must still succeed — the author never touched
        # the dates — so clamp instead of raising, matching how reads
        # already guard against it via combine_occurrence_window.
        end_date = start_date

    return start_date, end_date


def _apply_recurrence_update(event: Event, request: UpdateEventRequest) -> tuple[bool, bool]:
    start_date, end_date = compute_initial_dates(request.recurrence)
    event.start_date, event.end_date = _resolve_recurrence_time_window(
        event, request, start_date, end_date
    )
    event.is_recurring = True
    event.recurrence_frequency = request.recurrence.frequency.value
    event.recurrence_date_system = request.recurrence.date_system.value
    event.recurrence_calendar_type = request.recurrence.calendar_type
    event.recurrence_month = request.recurrence.month
    event.recurrence_day = request.recurrence.day
    event.recurrence_day_of_week = request.recurrence.day_of_week
    event.duration_days = request.recurrence.duration_days
    # Reminders are out of scope for recurring events.
    return True, False


def _apply_date_only_update(event: Event, request: UpdateEventRequest) -> tuple[bool, bool]:
    start_date = request.start_date if request.start_date is not None else event.start_date
    end_date = request.end_date if request.end_date is not None else event.end_date
    start_date_changed = (
        request.start_date is not None and request.start_date != event.start_date
    )
    if request.start_date is not None or request.end_date is not None:
        _validate_date_range(start_date, end_date)
        if request.start_date is not None:
            event.start_date = request.start_date
        if request.end_date is not None:
            event.end_date = request.end_date

    should_reschedule_reminders = start_date_changed and not event.is_recurring
    return False, should_reschedule_reminders


def _clear_recurrence_fields(event: Event) -> None:
    event.is_recurring = False
    event.recurrence_frequency = None
    event.recurrence_date_system = None
    event.recurrence_calendar_type = None
    event.recurrence_month = None
    event.recurrence_day = None
    event.recurrence_day_of_week = None
    event.duration_days = 1


def _apply_clear_recurrence(event: Event, request: UpdateEventRequest) -> tuple[bool, bool]:
    """Handle an explicit `recurrence: null`.

    For a recurring template this is a conversion to a one-time event, and
    dates are required so it is not left on a stale rule-derived occurrence.
    For an event that is already one-time it is a no-op, so the rest of the
    update proceeds normally rather than demanding dates it does not need.
    """
    if not event.is_recurring:
        _clear_recurrence_fields(event)
        return _apply_date_only_update(event, request)

    # Falling back to the template's stored dates would silently pin the
    # event to an old, possibly past occurrence and reschedule reminders for
    # it, so the caller must name the one-time date explicitly.
    if request.start_date is None or request.end_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date and end_date are required when converting to a one-time event",
        )
    _validate_date_range(request.start_date, request.end_date)
    event.start_date = request.start_date
    event.end_date = request.end_date
    _clear_recurrence_fields(event)
    # Leaving a recurring series always invalidates the reminders it spawned,
    # whether or not the caller also moved the date.
    return False, True


def _apply_recurrence_or_dates(event: Event, request: UpdateEventRequest) -> tuple[bool, bool]:
    """Applies recurrence/date changes to `event`.

    Returns (should_cancel_reminders, should_reschedule_reminders).
    An explicit `recurrence: null` clears the rule and keeps the event one-time.
    Omitting `recurrence` leaves the existing rule (or lack of one) untouched.
    """
    if "recurrence" in request.model_fields_set:
        if request.recurrence is None:
            return _apply_clear_recurrence(event, request)
        return _apply_recurrence_update(event, request)
    return _apply_date_only_update(event, request)


def _apply_simple_field_updates(event: Event, request: UpdateEventRequest) -> None:
    fields_set = request.model_fields_set
    if request.timezone is not None:
        event.timezone = request.timezone
    if request.group_id is not None:
        event.group_id = request.group_id
    # plan_id/series_id/accumulator_id/group_accumulator_id/mantra_id/timer_id use
    # model_fields_set (not `is not None`) so an explicit null in the request
    # unlinks the field instead of being indistinguishable from "omitted".
    if "plan_id" in fields_set:
        event.plan_id = request.plan_id
    if "series_id" in fields_set:
        event.series_id = request.series_id
    if "accumulator_id" in fields_set:
        event.accumulator_id = request.accumulator_id
    if "group_accumulator_id" in fields_set:
        event.group_accumulator_id = request.group_accumulator_id
    if "mantra_id" in fields_set:
        event.mantra_id = request.mantra_id
    if "timer_id" in fields_set:
        event.timer_id = request.timer_id
    if request.image_url is not None:
        event.image_url = request.image_url
    if "event_format" in fields_set:
        event.event_format = request.event_format


def _apply_relational_field_updates(db, event: Event, request: UpdateEventRequest) -> None:
    if "group_recitation_collection_id" in request.model_fields_set:
        _validate_group_recitation_collection(
            db=db,
            collection_id=request.group_recitation_collection_id,
            group_id=event.group_id,
        )
        event.group_recitation_collection_id = request.group_recitation_collection_id
    if "location_id" in request.model_fields_set:
        _validate_location(
            db=db, location_id=request.location_id, group_id=event.group_id
        )
        event.location_id = request.location_id


def _sync_event_reminders(db, event: Event, should_cancel: bool, should_reschedule: bool) -> None:
    if should_cancel:
        cancel_event_reminders(db, event.id)
    elif should_reschedule:
        reschedule_event_reminders(db, event.id, event.start_date)


def update_event_service(token: str, event_id: UUID, request: UpdateEventRequest) -> EventDTO:
    current_author = validate_cms_author_details(token=token)

    with SessionLocal() as db:
        event = get_event_by_id(db, event_id)
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event with id '{event_id}' not found",
            )

        _require_can_edit_event(db, event.group_id, current_author)

        should_cancel_reminders, should_reschedule_reminders = _apply_recurrence_or_dates(
            event, request
        )
        _apply_simple_field_updates(event, request)
        _apply_relational_field_updates(db, event, request)

        event.updated_at = datetime.now(timezone.utc)

        # Queued in the same session as the event write below (not committed
        # here) so a later validation or persistence failure rolls back the
        # reminder change along with the event, instead of leaving reminders
        # stale/canceled against an unchanged event.
        _sync_event_reminders(db, event, should_cancel_reminders, should_reschedule_reminders)

        saved = update_event(
            db, event,
            metadata_entries=request.metadata,
            link_entries=request.links,
            youtube_entries=request.youtube,
        )
        return _event_to_dto(saved)


def delete_event_service(token: str, event_id: UUID) -> None:
    current_author = validate_cms_author_details(token=token)

    with SessionLocal() as db:
        event = get_event_by_id(db, event_id)
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event with id '{event_id}' not found",
            )

        _require_can_edit_event(db, event.group_id, current_author)
        delete_event(db, event)


def get_featured_events_service(
    language: Optional[str] = None,
    limit: int = 10,
    token: Optional[str] = None,
) -> List[EventDTO]:
    with SessionLocal() as db:
        # Get featured one-shot events
        one_shot_events = get_featured_events(db, limit=None)
        
        # Get featured recurring events and find current/next occurrence for each
        # Use resolve_current_or_next_occurrence (5-year horizon) to include active
        # multi-day occurrences and handle sparse yearly recurrences like Feb 29
        recurring_templates = get_featured_recurring_events(db)
        
        now = datetime.now(timezone.utc)
        today = now.date()
        
        expanded_occurrences = []
        for template in recurring_templates:
            result = resolve_current_or_next_occurrence(template, after=today)
            if result:
                start_d, end_d, is_active = result
                # Carry the template's own time-of-day onto the occurrence,
                # instead of defaulting to midnight / end-of-day.
                occurrence_start, occurrence_end = combine_occurrence_window(
                    start_d, end_d, template.start_date, template.end_date
                )
                expanded_occurrences.append({
                    'event': template,
                    'start_date': occurrence_start,
                    'end_date': occurrence_end,
                    'occurrence_date': occurrence_start,
                    'is_active': is_active,
                })
        
        # Merge one-shot events and recurring occurrences.
        # Non-active (not yet started) occurrences are ranked by proximity to "now"
        # rather than by the template's created_at: for a future occurrence,
        # occurrence_date > now > created_at always holds, which made
        # min(created_at, occurrence_date) collapse to created_at and let a
        # freshly-created template with a far-future occurrence outrank genuinely
        # recent one-shot content. Mirroring the occurrence date around "now"
        # (now - (occurrence_date - now)) keeps imminent occurrences competitive
        # with recent content while distant ones sink below it, without ever
        # depending on when the template itself was created. Active events rank
        # by their start_date so multiple active events don't all tie at the top.
        def _recurring_sort_date(item):
            if item.get('is_active'):
                return item['start_date']  # Rank by when it started, not now
            return now - (item['start_date'] - now)
        
        all_event_items = [
            {'event': e, 'start_date': e.start_date, 'end_date': e.end_date, 'occurrence_date': None, 'sort_date': e.created_at}
            for e in one_shot_events
        ] + [
            {**item, 'sort_date': _recurring_sort_date(item)}
            for item in expanded_occurrences
        ]
        
        # Sort by sort_date descending
        all_event_items.sort(key=lambda x: x['sort_date'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        
        # Apply limit
        paginated_items = all_event_items[:limit]
        
        event_ids = list({item['event'].id for item in paginated_items})
        counts_by_event = get_event_participant_counts(db=db, event_ids=event_ids)
        group_cards = _group_card_map(db, [item['event'].group_id for item in paginated_items])

        joined_ids: set[UUID] = set()
        if token:
            current_user = validate_and_extract_user_details(token=token)
            joined_ids = set(
                get_joined_event_ids_by_user(
                    db=db,
                    user_id=current_user.id,
                    event_ids=event_ids,
                )
            )

        result = []
        for item in paginated_items:
            event = item['event']
            result.append(
                _event_to_dto(
                    event,
                    language=language,
                    fallback=True,
                    participant_count=counts_by_event.get(event.id, 0),
                    is_joined=(event.id in joined_ids) if token else None,
                    group_name=group_cards.get(event.group_id, (None, None))[0],
                    group_avatar_url=group_cards.get(event.group_id, (None, None))[1],
                    occurrence_date=item['occurrence_date'],
                    start_date=item['start_date'],
                    end_date=item['end_date'],
                )
            )

        return result


def update_event_featured_service(token: str, event_id: UUID) -> None:
    current_author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        event = get_event_by_id(db, event_id)
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Event with id '{event_id}' not found",
            )
        require_can_change_status(db=db, group_id=event.group_id, author=current_author)
        event.featured = not event.featured
        event.updated_at = datetime.now(timezone.utc)
        update_event(db, event)
