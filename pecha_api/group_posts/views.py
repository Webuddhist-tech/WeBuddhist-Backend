from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.group_posts.response_models import GroupPostDTO, GroupPostsResponse
from pecha_api.group_posts.service import (
    get_group_post_detail_service,
    list_group_posts_service,
    list_public_group_posts_service,
)
from pecha_api.users.users_service import validate_and_extract_user_details

oauth2_scheme_optional = HTTPBearer(auto_error=False)

from pecha_api.group_posts.posts_cache_service import (
    get_group_post_detail_cached,
    list_group_posts_cached,
    list_public_group_posts_cached,
)

public_group_posts_list_router = APIRouter(
    prefix="/groups/author/{group_id}/posts",
    tags=["Public Group Posts"],
)

public_group_posts_detail_router = APIRouter(
    prefix="/groups/author/posts",
    tags=["Public Group Posts"],
)


@public_group_posts_list_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostsResponse,
)
async def list_group_posts(
    group_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(oauth2_scheme_optional)
    ] = None,
):
    """Chronological feed of published posts for a public group. Optional auth for liked_by_me."""
    return await list_group_posts_cached(
        group_id=group_id,
        skip=skip,
        limit=limit,
        token=authentication_credential.credentials if authentication_credential else None,
    )


@public_group_posts_detail_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostsResponse,
)
async def list_public_group_posts(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    should_include_unfollowed: Annotated[
        bool,
        Query(
            alias="include_unfollowed",
            description=(
                "For authenticated users, false = joined groups only; "
                "true = all public groups"
            ),
        ),
    ] = False,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(oauth2_scheme_optional)
    ] = None,
) -> GroupPostsResponse:
    """Chronological published posts across public author groups."""
    return await list_public_group_posts_cached(
        skip=skip,
        limit=limit,
        should_include_unfollowed=should_include_unfollowed,
        token=authentication_credential.credentials if authentication_credential else None,
    )


@public_group_posts_detail_router.get(
    "/{post_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostDTO,
)
async def get_group_post_detail(
    post_id: UUID,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(oauth2_scheme_optional)
    ] = None,
):
    """Get a published post with presigned media URLs. Optional auth for liked_by_me."""
    return await get_group_post_detail_cached(
        post_id=post_id,
        token=authentication_credential.credentials if authentication_credential else None,
    )
