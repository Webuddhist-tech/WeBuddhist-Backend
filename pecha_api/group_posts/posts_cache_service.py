"""Cached reads for the public group post feeds.

Posts carry live state - like counts, comment counts, `liked_by_me` - so they
take `CACHE_SOCIAL_TIMEOUT` rather than the hours plan content gets. Liking a
post evicts the liker's entries (the routers that write likes and comments
carry `invalidate_caller_on_write`), and the count everyone else sees catches
up when the entry expires.

Resolving the token to a user id is a query, so it happens inside the loader,
on a miss only. The cache key uses the token's verified identity instead,
which costs no query at all.
"""

from typing import Optional
from uuid import UUID

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_identity import cache_identity_from_token
from pecha_api.cache.cached_response import cached_response
from pecha_api.group_posts.response_models import GroupPostDTO, GroupPostsResponse
from pecha_api.group_posts.service import (
    get_group_post_detail_service,
    list_group_posts_service,
    list_public_group_posts_service,
)
from pecha_api.users.users_service import validate_and_extract_user_details

POST_CACHE_TYPES = (CacheType.GROUP_POSTS_LIST, CacheType.GROUP_POST_DETAIL)


def _timeout() -> int:
    return config.get_int("CACHE_SOCIAL_TIMEOUT")


def _resolve_user_id(token: Optional[str]) -> Optional[UUID]:
    """The views' own rule: an unusable token means anonymous, not an error."""
    if not token:
        return None
    try:
        return validate_and_extract_user_details(token=token).id
    except Exception:
        return None


async def list_group_posts_cached(
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    token: Optional[str] = None,
) -> GroupPostsResponse:
    def _load() -> GroupPostsResponse:
        return list_group_posts_service(
            group_id=group_id, skip=skip, limit=limit, user_id=_resolve_user_id(token)
        )

    return await cached_response(
        cache_type=CacheType.GROUP_POSTS_LIST,
        parts=["group", group_id, skip, limit],
        model=GroupPostsResponse,
        loader=_load,
        timeout=_timeout(),
        user_identity=cache_identity_from_token(token),
    )


async def list_public_group_posts_cached(
    skip: int = 0,
    limit: int = 20,
    should_include_unfollowed: bool = False,
    token: Optional[str] = None,
) -> GroupPostsResponse:
    def _load() -> GroupPostsResponse:
        return list_public_group_posts_service(
            skip=skip,
            limit=limit,
            user_id=_resolve_user_id(token),
            should_include_unfollowed=should_include_unfollowed,
        )

    return await cached_response(
        cache_type=CacheType.GROUP_POSTS_LIST,
        parts=["public", skip, limit, should_include_unfollowed],
        model=GroupPostsResponse,
        loader=_load,
        timeout=_timeout(),
        user_identity=cache_identity_from_token(token),
    )


async def get_group_post_detail_cached(
    post_id: UUID,
    token: Optional[str] = None,
) -> GroupPostDTO:
    def _load() -> GroupPostDTO:
        return get_group_post_detail_service(post_id=post_id, user_id=_resolve_user_id(token))

    return await cached_response(
        cache_type=CacheType.GROUP_POST_DETAIL,
        parts=[post_id],
        model=GroupPostDTO,
        loader=_load,
        timeout=_timeout(),
        user_identity=cache_identity_from_token(token),
    )
