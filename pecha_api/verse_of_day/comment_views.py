from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.verse_of_day.comment_response_models import (
    CreateVerseOfDayCommentRequest,
    VerseOfDayCommentDTO,
    VerseOfDayCommentsResponse,
)
from pecha_api.verse_of_day.comment_service import (
    create_verse_comment_service,
    delete_verse_comment_service,
    list_verse_comments_service,
)

oauth2_scheme = HTTPBearer()

verse_of_day_comments_router = APIRouter(
    prefix="/verse-of-day/{verse_id}/comments",
    tags=["Verse of Day"],
)

verse_of_day_comment_actions_router = APIRouter(
    prefix="/verse-of-day/comments",
    tags=["Verse of Day"],
)


@verse_of_day_comments_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayCommentsResponse,
)
async def list_verse_comments(
    verse_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> VerseOfDayCommentsResponse:
    """List comments on a verse of the day (newest first)."""
    return await list_verse_comments_service(
        verse_id=verse_id,
        skip=skip,
        limit=limit,
    )


@verse_of_day_comments_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=VerseOfDayCommentDTO,
)
async def create_verse_comment(
    verse_id: UUID,
    request: CreateVerseOfDayCommentRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> VerseOfDayCommentDTO:
    """Create a comment on a verse of the day (requires authentication)."""
    user = await run_in_threadpool(
        validate_and_extract_user_details,
        token=authentication_credential.credentials,
    )
    return await create_verse_comment_service(
        verse_id=verse_id,
        user_id=user.id,
        text=request.text,
    )


@verse_of_day_comment_actions_router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_verse_comment(
    comment_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    """Delete a comment (only the author can delete)."""
    user = await run_in_threadpool(
        validate_and_extract_user_details,
        token=authentication_credential.credentials,
    )
    await delete_verse_comment_service(comment_id=comment_id, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
