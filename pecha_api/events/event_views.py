from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette import status

from .event_response_models import (
    EventFormat,
    EventsResponse,
    EventDTO,
    EventParticipantsResponse,
    JoinEventRequest,
    UpdateParticipationTypeRequest,
)
from .event_service import (
    EventContentFilter,
    get_events_service,
    get_events_today_service,
    get_event_by_id_service,
    get_featured_events_service,
)
from .event_participant_service import (
    join_event_service,
    leave_event_service,
    update_participation_type_service,
    get_event_participants_service,
)

oauth2_scheme = HTTPBearer()
optional_oauth2_scheme = HTTPBearer(auto_error=False)

from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_invalidation_deps import invalidate_caller_on_write
from pecha_api.events.events_cache_service import (
    EVENT_CACHE_TYPES,
    get_event_by_id_service_cached,
    get_events_service_cached,
    get_events_today_service_cached,
    get_featured_events_service_cached,
)

events_router = APIRouter(
    prefix="/events",
    tags=["Events"],
    # Joining or leaving changes is_joined for the caller alone, so only
    # their entries are evicted; counts follow the short timeout.
    dependencies=[Depends(invalidate_caller_on_write(*EVENT_CACHE_TYPES))],
)


@events_router.get("", status_code=status.HTTP_200_OK, response_model=EventsResponse, response_model_exclude_none=True)
async def get_events_endpoint(
    group_id: Annotated[Optional[UUID], Query(description="Filter by group ID")] = None,
    plan_id: Annotated[Optional[UUID], Query(description="Filter by plan ID")] = None,
    accumulator_id: Annotated[Optional[UUID], Query(description="Filter by accumulator ID")] = None,
    mantra_id: Annotated[Optional[UUID], Query(description="Filter by mantra ID")] = None,
    timer_id: Annotated[Optional[UUID], Query(description="Filter by timer ID")] = None,
    group_recitation_collection_id: Annotated[Optional[UUID], Query(description="Filter by group recitation collection ID")] = None,
    event_format: Annotated[Optional[EventFormat], Query(description="Filter by event format")] = None,
    from_date: Annotated[Optional[datetime], Query(description="Filter events ending on or after this date")] = None,
    to_date: Annotated[Optional[datetime], Query(description="Filter events starting on or before this date")] = None,
    language: Annotated[Optional[str], Query(description="Filter metadata by language code")] = None,
    should_include_unfollowed: Annotated[
        bool,
        Query(
            alias="include_unfollowed",
            description=(
                "For authenticated users, events are listed from published "
                "public groups and joined groups even when false."
            ),
        ),
    ] = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(optional_oauth2_scheme),
    ] = None,
) -> EventsResponse:
    return await get_events_service_cached(
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
        fallback=True,
        should_include_unfollowed=should_include_unfollowed,
        skip=skip,
        limit=limit,
        token=credentials.credentials if credentials else None,
    )


@events_router.get("/today", status_code=status.HTTP_200_OK, response_model=EventsResponse, response_model_exclude_none=True)
async def get_events_today_endpoint(
    group_id: Annotated[Optional[UUID], Query(description="Filter by group ID")] = None,
    language: Annotated[Optional[str], Query(description="Filter metadata by language code")] = None,
    should_include_unfollowed: Annotated[
        bool,
        Query(
            alias="include_unfollowed",
            description=(
                "For authenticated users, events are listed from published "
                "public groups and joined groups even when false."
            ),
        ),
    ] = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone for determining today's date."),
    ] = None,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(optional_oauth2_scheme),
    ] = None,
) -> EventsResponse:
    return await get_events_today_service_cached(
        timezone=x_timezone,
        group_id=group_id,
        language=language,
        should_include_unfollowed=should_include_unfollowed,
        skip=skip,
        limit=limit,
        token=credentials.credentials if credentials else None,
    )


@events_router.get("/featured", status_code=status.HTTP_200_OK, response_model=list[EventDTO], response_model_exclude_none=True)
async def get_featured_events_endpoint(
    language: Annotated[Optional[str], Query(description="Filter metadata by language code")] = "en",
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(optional_oauth2_scheme),
    ] = None,
) -> list[EventDTO]:
    return await get_featured_events_service_cached(
        language=language,
        limit=limit,
        token=credentials.credentials if credentials else None,
    )


@events_router.post(
    "/{event_id}/participants",
    status_code=status.HTTP_204_NO_CONTENT,
)
def join_event_endpoint(
    event_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    payload: Annotated[Optional[JoinEventRequest], Body()] = None,
) -> None:
    """Join an event. Idempotent: joining again succeeds without creating a duplicate.

    The body is optional. With `participation_type` set, it also records how
    the user attends - and re-sending it on an existing participation updates
    the choice. Online-only and offline-only events fill it in themselves and
    reject the other value with a 400."""
    join_event_service(
        token=credentials.credentials,
        event_id=event_id,
        participation_type=payload.participation_type if payload else None,
    )


@events_router.patch(
    "/{event_id}/participants/me",
    status_code=status.HTTP_204_NO_CONTENT,
)
def update_participation_type_endpoint(
    event_id: UUID,
    payload: UpdateParticipationTypeRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> None:
    """Switch how the caller attends an event: 'online' or 'offline'.

    An upsert: a caller who has not joined yet is joined by this call, and
    joining an event also joins its group. 400 when the event only runs the
    other way."""
    update_participation_type_service(
        token=credentials.credentials,
        event_id=event_id,
        participation_type=payload.participation_type,
    )


@events_router.delete(
    "/{event_id}/participants/me",
    status_code=status.HTTP_204_NO_CONTENT,
)
def leave_event_endpoint(
    event_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> None:
    leave_event_service(token=credentials.credentials, event_id=event_id)


@events_router.get(
    "/{event_id}/participants",
    status_code=status.HTTP_200_OK,
    response_model=EventParticipantsResponse,
    response_model_exclude_none=True,
)
def get_event_participants_endpoint(
    event_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EventParticipantsResponse:
    return get_event_participants_service(event_id=event_id, skip=skip, limit=limit)


@events_router.get("/{event_id}", status_code=status.HTTP_200_OK, response_model=EventDTO, response_model_exclude_none=True)
async def get_event_by_id_endpoint(
    event_id: UUID,
    language: Annotated[Optional[str], Query(description="Filter metadata by language code")] = None,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(optional_oauth2_scheme),
    ] = None,
) -> EventDTO:
    return await get_event_by_id_service_cached(
        event_id=event_id,
        language=language,
        token=credentials.credentials if credentials else None,
    )
