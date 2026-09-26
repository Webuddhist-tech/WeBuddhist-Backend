from pecha_api.cache.cache_invalidation_deps import invalidate_caller_on_write
from pecha_api.group_posts.posts_cache_service import POST_CACHE_TYPES
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.group_posts.like_response_models import (
    LikePostResponse,
    PostLikersResponse,
)
from pecha_api.group_posts.like_service import (
    like_post_service,
    unlike_post_service,
    list_post_likers_service,
)
from pecha_api.users.users_service import validate_and_extract_user_details

oauth2_scheme = HTTPBearer()
oauth2_scheme_optional = HTTPBearer(auto_error=False)

public_group_post_likes_router = APIRouter(
    prefix="/groups/author/posts/{post_id}/likes",
    tags=["Public Group Post Likes"],
    # A like or comment changes liked_by_me for the caller; counts follow the timeout.
    dependencies=[Depends(invalidate_caller_on_write(*POST_CACHE_TYPES))],
)


@public_group_post_likes_router.post(
    "",
    response_model=LikePostResponse,
)
def like_post(
    post_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    response: Response,
) -> LikePostResponse:
    """Like a post (requires authentication). Returns 201 if newly created, 200 if already liked."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    result = like_post_service(
        post_id=post_id,
        user_id=user.id,
    )
    response.status_code = status.HTTP_201_CREATED if result.is_new else status.HTTP_200_OK
    return result


@public_group_post_likes_router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unlike_post(
    post_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    """Unlike a post (requires authentication). Idempotent - succeeds even if not liked."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    unlike_post_service(
        post_id=post_id,
        user_id=user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_group_post_likes_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=PostLikersResponse,
)
def list_post_likers(
    post_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(oauth2_scheme_optional)
    ] = None,
) -> PostLikersResponse:
    """List users who liked a post (public, no auth required)."""
    user_id = None
    if authentication_credential:
        try:
            user = validate_and_extract_user_details(
                token=authentication_credential.credentials
            )
            user_id = user.id
        except Exception:
            pass
    return list_post_likers_service(
        post_id=post_id,
        skip=skip,
        limit=limit,
        user_id=user_id,
    )
