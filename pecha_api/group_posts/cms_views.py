from pecha_api.cache.cache_invalidation_deps import invalidate_on_write
from pecha_api.group_posts.posts_cache_service import POST_CACHE_TYPES
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.group_posts.cms_service import (
    cms_create_group_post_service,
    cms_delete_group_post_service,
    cms_get_group_post_detail_service,
    cms_list_group_posts_service,
    cms_replace_group_post_links_service,
    cms_replace_group_post_media_service,
    cms_update_group_post_service,
)
from pecha_api.group_posts.enums import GroupPostStatus
from pecha_api.group_posts.response_models import (
    CreateGroupPostRequest,
    GroupPostDTO,
    GroupPostsResponse,
    ReplaceGroupPostLinksRequest,
    ReplaceGroupPostMediaRequest,
    UpdateGroupPostRequest,
)

oauth2_scheme = HTTPBearer()

cms_group_posts_router = APIRouter(
    prefix="/cms/author/groups/{group_id}/posts",
    tags=["CMS Group Posts"],
    # Publishing or removing a post changes the feed for every reader.
    dependencies=[Depends(invalidate_on_write(*POST_CACHE_TYPES))],
)


@cms_group_posts_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostsResponse,
)
def cms_list_group_posts(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[
        Optional[GroupPostStatus],
        Query(alias="status", description="Filter by post status: PUBLISHED or HIDDEN"),
    ] = None,
):
    """List posts for a group (CMS)."""
    return cms_list_group_posts_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
    )


@cms_group_posts_router.get(
    "/{post_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostDTO,
)
def cms_get_group_post_detail(
    group_id: UUID,
    post_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Get a specific post with its media and links (CMS)."""
    return cms_get_group_post_detail_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        post_id=post_id,
    )


@cms_group_posts_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupPostDTO,
)
def cms_create_group_post(
    group_id: UUID,
    request: CreateGroupPostRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Create a post with caption, ordered media keys, and links."""
    return cms_create_group_post_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        request=request,
    )


@cms_group_posts_router.patch(
    "/{post_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostDTO,
)
def cms_update_group_post(
    group_id: UUID,
    post_id: UUID,
    request: UpdateGroupPostRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Update caption / status / published_at of a post."""
    return cms_update_group_post_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        post_id=post_id,
        request=request,
    )


@cms_group_posts_router.put(
    "/{post_id}/media",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostDTO,
)
def cms_replace_group_post_media(
    group_id: UUID,
    post_id: UUID,
    request: ReplaceGroupPostMediaRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Replace the full ordered media set of a post."""
    return cms_replace_group_post_media_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        post_id=post_id,
        request=request,
    )


@cms_group_posts_router.put(
    "/{post_id}/links",
    status_code=status.HTTP_200_OK,
    response_model=GroupPostDTO,
)
def cms_replace_group_post_links(
    group_id: UUID,
    post_id: UUID,
    request: ReplaceGroupPostLinksRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Replace the full ordered link set of a post."""
    return cms_replace_group_post_links_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        post_id=post_id,
        request=request,
    )


@cms_group_posts_router.delete(
    "/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def cms_delete_group_post(
    group_id: UUID,
    post_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Soft delete a post."""
    cms_delete_group_post_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        post_id=post_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
