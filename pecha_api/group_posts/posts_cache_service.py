"""Cached reads for the public group post feeds.

Posts carry live state - like counts, comment counts, `liked_by_me` - so they
take `CACHE_SOCIAL_TIMEOUT` rather than the hours plan content gets. Liking a
post evicts the liker's entries (the routers that write likes and comments
carry `invalidate_caller_on_write`), and the count everyone else sees catches
up when the entry expires.

Access is re-checked on every read, hit or miss. A private group's posts are
only visible to its members, and membership is revocable: without the recheck
someone removed from a group would keep being served its posts from their own
cache entry until it expired. The check is two indexed queries against the
feed build it guards, so it is worth paying on a hit.
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
from pecha_api.group_posts.service_utils import validate_group_content_access
from pecha_api.plans.groups.follow_scope import resolve_public_group_scope
from pecha_api.utils import Utils
from pecha_api.db.database import SessionLocal
from pecha_api.users.users_service import validate_and_extract_user_details
from starlette.concurrency import run_in_threadpool

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


def _assert_group_access(group_id: UUID, token: Optional[str]) -> None:
    """Raises 404 the way the loaders do when the caller may not see a group."""
    with SessionLocal() as db:
        validate_group_content_access(
            db=db, group_id=group_id, user_id=_resolve_user_id(token)
        )


async def list_group_posts_cached(
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    token: Optional[str] = None,
) -> GroupPostsResponse:
    await run_in_threadpool(_assert_group_access, group_id, token)

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
        user_identity=await cache_identity_from_token(token),
    )


def _group_scope_fingerprint(token: Optional[str], should_include_unfollowed: bool) -> str:
    """A digest of the groups this caller may currently see.

    The cross-group feed spans every group the caller has joined, private ones
    included, so there is no single group to re-check. Putting the scope in
    the key instead makes the entry self-invalidating: leave a group or get
    removed from one and the scope changes, so the key changes, and the entry
    built while you were a member is simply never read again.
    """
    user_id = _resolve_user_id(token)
    if user_id is None:
        return "anon"
    with SessionLocal() as db:
        group_ids, _ = resolve_public_group_scope(
            db=db,
            user_id=user_id,
            should_include_unfollowed=should_include_unfollowed,
        )
    return Utils.generate_hash_key(payload=sorted(str(group_id) for group_id in group_ids))


async def list_public_group_posts_cached(
    skip: int = 0,
    limit: int = 20,
    should_include_unfollowed: bool = False,
    token: Optional[str] = None,
) -> GroupPostsResponse:
    scope = await run_in_threadpool(
        _group_scope_fingerprint, token, should_include_unfollowed
    )

    def _load() -> GroupPostsResponse:
        return list_public_group_posts_service(
            skip=skip,
            limit=limit,
            user_id=_resolve_user_id(token),
            should_include_unfollowed=should_include_unfollowed,
        )

    return await cached_response(
        cache_type=CacheType.GROUP_POSTS_LIST,
        parts=["public", skip, limit, should_include_unfollowed, scope],
        model=GroupPostsResponse,
        loader=_load,
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )


async def get_group_post_detail_cached(
    post_id: UUID,
    token: Optional[str] = None,
) -> GroupPostDTO:
    def _load() -> GroupPostDTO:
        return get_group_post_detail_service(post_id=post_id, user_id=_resolve_user_id(token))

    post = await cached_response(
        cache_type=CacheType.GROUP_POST_DETAIL,
        parts=[post_id],
        model=GroupPostDTO,
        loader=_load,
        timeout=_timeout(),
        user_identity=await cache_identity_from_token(token),
    )
    # Which group the post belongs to is only known once we have the post, so
    # the recheck happens after. On a miss the loader has already checked and
    # this repeats it; on a hit it is the only thing standing between a
    # removed member and the group's posts.
    await run_in_threadpool(_assert_group_access, post.group_id, token)
    return post
