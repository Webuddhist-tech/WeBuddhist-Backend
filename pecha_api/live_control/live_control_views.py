from typing import Annotated, Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.events.recitation_live_service import assert_live_event
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details

from .live_control_auth import verify_event_controller_token
from .live_control_import_service import (
    export_file,
    import_file,
    sample_file,
    suggest_short_titles_service,
    template_file,
)
from .live_control_models import EventLiveController
from .live_control_plan_texts import get_plan_texts
from .live_control_room_state import (
    RoomStateDTO,
    RoomStatePatch,
    get_room_state,
    update_room_state,
)
from .live_control_response_models import (
    ControllerDTO,
    ControllersResponse,
    ControllerSelfDTO,
    ControllerWithTokenDTO,
    CreateControllerRequest,
    EditionLiveSettingsDTO,
    EditionLiveSettingsInput,
    EventLiveSettingsDTO,
    EventLiveSettingsInput,
    ImportReport,
    PlanTextsResponse,
    ShortTitleSuggestionsResponse,
    UpdateControllerRequest,
)
from .live_control_service import (
    create_controller_service,
    get_event_settings_service,
    list_controllers_service,
    read_edition_settings,
    read_event_settings,
    read_section_order,
    revoke_controller_service,
    update_controller_service,
    update_edition_settings_service,
    update_event_settings_service,
    write_section_order,
)

oauth2_scheme = HTTPBearer()
Credentials = Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]

cms_live_control_router = APIRouter(prefix="/cms", tags=["CMS Live Control"])
live_control_router = APIRouter(prefix="/events", tags=["Live Recitation"])


# --- Studio: per event ---------------------------------------------------------


@cms_live_control_router.get("/events/{event_id}/live-control/settings")
async def get_event_live_settings(event_id: UUID, credentials: Credentials) -> EventLiveSettingsDTO:
    return await run_in_threadpool(get_event_settings_service, credentials.credentials, event_id)


@cms_live_control_router.put("/events/{event_id}/live-control/settings")
async def put_event_live_settings(
    event_id: UUID, request: EventLiveSettingsInput, credentials: Credentials
) -> EventLiveSettingsDTO:
    return await run_in_threadpool(
        update_event_settings_service, credentials.credentials, event_id, request
    )


@cms_live_control_router.get("/events/{event_id}/live-control/controllers")
async def get_event_controllers(event_id: UUID, credentials: Credentials) -> ControllersResponse:
    return await run_in_threadpool(list_controllers_service, credentials.credentials, event_id)


@cms_live_control_router.post(
    "/events/{event_id}/live-control/controllers", status_code=status.HTTP_201_CREATED
)
async def post_event_controller(
    event_id: UUID, request: CreateControllerRequest, credentials: Credentials
) -> ControllerWithTokenDTO:
    """The token is in this response only: the backend keeps its hash."""
    return await run_in_threadpool(
        create_controller_service, credentials.credentials, event_id, request
    )


@cms_live_control_router.patch("/events/{event_id}/live-control/controllers/{controller_id}")
async def patch_event_controller(
    event_id: UUID,
    controller_id: UUID,
    request: UpdateControllerRequest,
    credentials: Credentials,
) -> ControllerWithTokenDTO | ControllerDTO:
    """Rename, change the default text, or set a new token. A new token comes
    back in this response, and only here."""
    return await run_in_threadpool(
        update_controller_service, credentials.credentials, event_id, controller_id, request
    )


@cms_live_control_router.delete(
    "/events/{event_id}/live-control/controllers/{controller_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_event_controller(
    event_id: UUID, controller_id: UUID, credentials: Credentials
) -> Response:
    """Revokes the controller: its token stops working at once."""
    await run_in_threadpool(
        revoke_controller_service, credentials.credentials, event_id, controller_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@cms_live_control_router.get("/events/{event_id}/live-control/export")
async def get_event_live_control_export(event_id: UUID, credentials: Credentials) -> Dict[str, Any]:
    return await run_in_threadpool(export_file, credentials.credentials, event_id)


# --- Studio: per edition and import -------------------------------------------


@cms_live_control_router.get("/live-control/settings/sample")
async def get_live_control_sample() -> Dict[str, Any]:
    return sample_file()


@cms_live_control_router.post("/live-control/import")
async def post_live_control_import(
    credentials: Credentials,
    payload: Annotated[Any, Body(description="A live control settings file")],
    event_id: Annotated[Optional[UUID], Query(description="Event the file's room settings apply to")] = None,
    dry_run: Annotated[bool, Query(description="Check only; write nothing")] = False,
) -> ImportReport:
    """Always answers with a report. Nothing is written unless the whole file
    passes its check and `dry_run` is false."""
    return await import_file(credentials.credentials, payload, event_id, dry_run)


@cms_live_control_router.get("/live-control/editions/{edition_id}")
async def get_edition_live_settings(edition_id: str, credentials: Credentials) -> EditionLiveSettingsDTO:
    await run_in_threadpool(validate_cms_author_details, token=credentials.credentials)
    return await run_in_threadpool(read_edition_settings, edition_id)


@cms_live_control_router.put("/live-control/editions/{edition_id}")
async def put_edition_live_settings(
    edition_id: str, request: EditionLiveSettingsInput, credentials: Credentials
) -> EditionLiveSettingsDTO:
    """Each list sent replaces the stored one; a list left out is kept."""
    return await update_edition_settings_service(credentials.credentials, edition_id, request)


@cms_live_control_router.get("/live-control/editions/{edition_id}/template")
async def get_edition_live_template(edition_id: str, credentials: Credentials) -> Dict[str, Any]:
    return await template_file(credentials.credentials, edition_id)


@cms_live_control_router.post("/live-control/editions/{edition_id}/short-titles/suggest")
async def post_short_title_suggestions(
    edition_id: str, credentials: Credentials
) -> ShortTitleSuggestionsResponse:
    """Suggestions only: nothing is saved."""
    return await suggest_short_titles_service(credentials.credentials, edition_id)


# --- The live controller ------------------------------------------------------


@live_control_router.get("/{event_id}/recitation/texts")
async def get_event_recitation_texts(event_id: UUID) -> PlanTextsResponse:
    """The texts in the event's plan, or its series' plans, in plan order.

    Public: text ids and titles of a public plan, nothing that moves a room."""
    return await get_plan_texts(event_id)


@live_control_router.get("/{event_id}/recitation/settings")
async def get_event_recitation_settings(event_id: UUID) -> EventLiveSettingsDTO:
    return await run_in_threadpool(read_event_settings, event_id)


@live_control_router.get("/recitation/editions/{edition_id}/settings")
async def get_edition_recitation_settings(edition_id: str) -> EditionLiveSettingsDTO:
    """Short titles, repeated segments and return jumps of one edition."""
    return await run_in_threadpool(read_edition_settings, edition_id)


@live_control_router.get("/{event_id}/recitation/controller")
async def get_recitation_controller(
    event_id: UUID,
    controller: Annotated[Optional[EventLiveController], Depends(verify_event_controller_token)],
) -> ControllerSelfDTO:
    """Who this token is: also how a controller checks a token it was given."""
    await run_in_threadpool(assert_live_event, event_id=event_id)
    if controller is None:
        return ControllerSelfDTO(event_id=event_id)
    return ControllerSelfDTO(
        id=controller.id,
        event_id=event_id,
        name=controller.name,
        default_text_id=controller.default_text_id,
    )


@live_control_router.get(
    "/{event_id}/recitation/state",
    dependencies=[Depends(verify_event_controller_token)],
)
async def get_recitation_room_state(event_id: UUID) -> RoomStateDTO:
    """Open text, who is on air and today's return counts: what a controller
    reads on load, then follows as `room_state` frames on its socket."""
    return await get_room_state(event_id)


@live_control_router.patch("/{event_id}/recitation/state")
async def patch_recitation_room_state(
    event_id: UUID,
    patch: RoomStatePatch,
    controller: Annotated[Optional[EventLiveController], Depends(verify_event_controller_token)],
) -> RoomStateDTO:
    """`on_air` applies to the controller whose token sent it."""
    return await update_room_state(event_id, controller.id if controller else None, patch)


class SectionOrder(BaseModel):
    section_ids: List[str] = Field(default_factory=list, max_length=500)


@live_control_router.get("/{event_id}/recitation/section-order/{edition_id}")
async def get_recitation_section_order(event_id: UUID, edition_id: str) -> SectionOrder:
    """Empty: the table of contents' own order."""
    return SectionOrder(
        section_ids=await run_in_threadpool(read_section_order, event_id, edition_id)
    )


@live_control_router.put(
    "/{event_id}/recitation/section-order/{edition_id}",
    dependencies=[Depends(verify_event_controller_token)],
)
async def put_recitation_section_order(
    event_id: UUID, edition_id: str, request: SectionOrder
) -> SectionOrder:
    """Set by dragging the titles on the controller. An empty list goes back to
    the table of contents' order."""
    return SectionOrder(
        section_ids=await run_in_threadpool(
            write_section_order, event_id, edition_id, request.section_ids
        )
    )
