from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.verse_of_day.like_response_models import LikeVerseOfDayResponse
from pecha_api.verse_of_day.like_service import (
    like_verse_of_day_service,
    unlike_verse_of_day_service,
)

oauth2_scheme = HTTPBearer()

verse_of_day_likes_router = APIRouter(
    prefix="/verse-of-day/{verse_id}/likes",
    tags=["Verse of Day"],
)


@verse_of_day_likes_router.post(
    "",
    response_model=LikeVerseOfDayResponse,
)
def like_verse_of_day(
    verse_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    response: Response,
) -> LikeVerseOfDayResponse:
    """Like a verse of the day. Returns 201 if newly created, 200 if already liked."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    result = like_verse_of_day_service(verse_id=verse_id, user_id=user.id)
    response.status_code = status.HTTP_201_CREATED if result.is_new else status.HTTP_200_OK
    return result


@verse_of_day_likes_router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unlike_verse_of_day(
    verse_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    """Unlike a verse of the day. Idempotent — succeeds even if not liked."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    unlike_verse_of_day_service(verse_id=verse_id, user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
