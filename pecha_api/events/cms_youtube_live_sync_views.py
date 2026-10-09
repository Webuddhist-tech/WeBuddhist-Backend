from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status
from starlette.concurrency import run_in_threadpool

from .youtube_live_sync_response_models import (
    RunYoutubeLiveSyncRequest,
    UpdateYoutubeLiveSyncRequest,
    YoutubeLiveSyncListDTO,
    YoutubeLiveSyncRunDTO,
)
from .youtube_live_sync_service import (
    delete_youtube_live_sync_service,
    get_youtube_live_sync_service,
    run_youtube_live_sync_now_service,
    update_youtube_live_sync_service,
)

oauth2_scheme = HTTPBearer()

cms_youtube_live_sync_router = APIRouter(
    prefix="/cms/groups/{group_id}/youtube-live-sync",
    tags=["CMS Events"],
)


@cms_youtube_live_sync_router.get("", status_code=status.HTTP_200_OK, response_model=YoutubeLiveSyncListDTO)
async def get_youtube_live_sync_endpoint(
    group_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> YoutubeLiveSyncListDTO:
    """The live sync schedules of this group's events, and the channel they read."""
    return await run_in_threadpool(
        get_youtube_live_sync_service, token=credentials.credentials, group_id=group_id
    )


@cms_youtube_live_sync_router.put("", status_code=status.HTTP_200_OK, response_model=YoutubeLiveSyncListDTO)
async def put_youtube_live_sync_endpoint(
    group_id: UUID,
    request: UpdateYoutubeLiveSyncRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> YoutubeLiveSyncListDTO:
    """Set one schedule on each of the listed events. Other events are not touched."""
    return await run_in_threadpool(
        update_youtube_live_sync_service,
        token=credentials.credentials,
        group_id=group_id,
        request=request,
    )


@cms_youtube_live_sync_router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_youtube_live_sync_endpoint(
    group_id: UUID,
    event_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    await run_in_threadpool(
        delete_youtube_live_sync_service,
        token=credentials.credentials,
        group_id=group_id,
        event_id=event_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@cms_youtube_live_sync_router.post("/run", status_code=status.HTTP_200_OK, response_model=YoutubeLiveSyncRunDTO)
async def run_youtube_live_sync_endpoint(
    group_id: UUID,
    request: RunYoutubeLiveSyncRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> YoutubeLiveSyncRunDTO:
    """Check the channel now and add its live stream to the listed events."""
    return await run_in_threadpool(
        run_youtube_live_sync_now_service,
        token=credentials.credentials,
        group_id=group_id,
        request=request,
    )
