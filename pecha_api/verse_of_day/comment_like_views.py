from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.verse_of_day.comment_like_response_models import (
    LikeVerseOfDayCommentResponse,
    VerseOfDayCommentLikersResponse,
)
from pecha_api.verse_of_day.comment_like_service import (
    like_verse_comment_service,
    list_verse_comment_likers_service,
    unlike_verse_comment_service,
)

oauth2_scheme = HTTPBearer()

verse_of_day_comment_likes_router = APIRouter(
    prefix="/verse-of-day/comments/{comment_id}/likes",
    tags=["Verse of Day"],
)


@verse_of_day_comment_likes_router.post(
    "",
    response_model=LikeVerseOfDayCommentResponse,
)
async def like_verse_comment(
    comment_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    response: Response,
) -> LikeVerseOfDayCommentResponse:
    """Like a verse comment. Returns 201 if newly created, 200 if already liked."""
    user = await run_in_threadpool(
        validate_and_extract_user_details,
        token=authentication_credential.credentials,
    )
    result = await like_verse_comment_service(comment_id=comment_id, user_id=user.id)
    response.status_code = status.HTTP_201_CREATED if result.is_new else status.HTTP_200_OK
    return result


@verse_of_day_comment_likes_router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlike_verse_comment(
    comment_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    """Unlike a verse comment. Idempotent — succeeds even if not liked."""
    user = await run_in_threadpool(
        validate_and_extract_user_details,
        token=authentication_credential.credentials,
    )
    await unlike_verse_comment_service(comment_id=comment_id, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@verse_of_day_comment_likes_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayCommentLikersResponse,
)
async def list_verse_comment_likers(
    comment_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> VerseOfDayCommentLikersResponse:
    """List users who liked a verse comment (public, no auth required)."""
    return await list_verse_comment_likers_service(
        comment_id=comment_id,
        skip=skip,
        limit=limit,
    )
