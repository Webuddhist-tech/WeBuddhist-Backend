from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.verse_of_day.like_response_models import (
    LikeVerseOfDayResponse,
    VerseOfDayLikersResponse,
    VerseOfDayLikesResponse,
)
from pecha_api.verse_of_day.like_service import (
    get_verse_likes_service,
    like_verse_of_day_service,
    list_verse_likers_service,
    unlike_verse_of_day_service,
)

oauth2_scheme = HTTPBearer()
oauth2_scheme_optional = HTTPBearer(auto_error=False)

verse_of_day_likes_router = APIRouter(
    prefix="/verse-of-day/{verse_id}/likes",
    tags=["Verse of Day"],
)


@verse_of_day_likes_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayLikesResponse,
)
async def get_verse_likes(
    verse_id: UUID,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(oauth2_scheme_optional)
    ] = None,
) -> VerseOfDayLikesResponse:
    """Read like count and whether the caller liked this verse (optional auth)."""
    user_id = None
    if authentication_credential:
        try:
            user = await run_in_threadpool(
                validate_and_extract_user_details,
                token=authentication_credential.credentials,
            )
            user_id = user.id
        except HTTPException as exc:
            if exc.status_code != status.HTTP_401_UNAUTHORIZED:
                raise
    return await get_verse_likes_service(verse_id=verse_id, user_id=user_id)


@verse_of_day_likes_router.get(
    "/users",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayLikersResponse,
)
async def list_verse_likers(
    verse_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> VerseOfDayLikersResponse:
    """List users who liked this verse (newest first). Signed-in users only:
    it names individual users and when they liked it."""
    await run_in_threadpool(
        validate_and_extract_user_details,
        token=authentication_credential.credentials,
    )
    return await list_verse_likers_service(verse_id=verse_id, skip=skip, limit=limit)


@verse_of_day_likes_router.post(
    "",
    response_model=LikeVerseOfDayResponse,
    responses={
        status.HTTP_201_CREATED: {"description": "New like created"},
        status.HTTP_200_OK: {"description": "Verse was already liked"},
    },
)
async def like_verse_of_day(
    verse_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    response: Response,
) -> LikeVerseOfDayResponse:
    """Like a verse of the day. Returns 201 if newly created, 200 if already liked."""
    user = await run_in_threadpool(
        validate_and_extract_user_details,
        token=authentication_credential.credentials,
    )
    result = await like_verse_of_day_service(verse_id=verse_id, user_id=user.id)
    response.status_code = status.HTTP_201_CREATED if result.is_new else status.HTTP_200_OK
    return result


@verse_of_day_likes_router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlike_verse_of_day(
    verse_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    """Unlike a verse of the day. Idempotent — succeeds even if not liked."""
    user = await run_in_threadpool(
        validate_and_extract_user_details,
        token=authentication_credential.credentials,
    )
    await unlike_verse_of_day_service(verse_id=verse_id, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
