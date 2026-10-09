from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.author_group_feed.response_models import AuthorGroupFeedResponse
from pecha_api.author_group_feed.service import get_author_group_feed_service
from pecha_api.db.database import get_db

optional_oauth2_scheme = HTTPBearer(auto_error=False)

author_group_feed_router = APIRouter(
    prefix="/author/groups/feeds",
    tags=["Public Author Groups"],
)


@author_group_feed_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=AuthorGroupFeedResponse,
)
async def get_author_group_feed(
    db: Annotated[Session, Depends(get_db)],
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    should_include_unfollowed: Annotated[
        bool,
        Query(
            alias="include_unfollowed",
            description=(
                "false = posts from joined groups only (My tab); "
                "events still include all public groups. "
                "true = posts from public groups too (Discover tab). "
                "Guests always see public groups."
            ),
        ),
    ] = False,
    language: Annotated[
        Optional[str],
        Query(description="Preferred language for event metadata"),
    ] = None,
    x_timezone: Annotated[
        Optional[str],
        Header(
            alias="X-Timezone",
            description=(
                "IANA timezone (e.g. Asia/Shanghai). "
                "Restricted plans are hidden for Chinese timezones."
            ),
        ),
    ] = None,
) -> AuthorGroupFeedResponse:
    """Mixed chronological feed of posts and events from author groups.

    Optional auth. Guests see published public groups. Logged-in users default
    to joined groups for posts; events include public groups without join.
    Pass ``include_unfollowed=true`` to mix public posts in too.
    """
    return await get_author_group_feed_service(
        db=db,
        token=authentication_credential.credentials if authentication_credential else None,
        should_include_unfollowed=should_include_unfollowed,
        skip=skip,
        limit=limit,
        language=language,
        timezone_name=x_timezone,
    )
