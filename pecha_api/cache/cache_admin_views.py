from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.cache.cache_admin_service import flush_cache_key, flush_response_cache
from pecha_api.cache.cache_enums import CacheType
from pecha_api.plans.auth.cms_auth_deps import get_cms_author_token
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.shared.permissions import require_super_admin

cms_cache_router = APIRouter(prefix="/cms/admin/cache", tags=["CMS Admin Cache"])


class CacheFlushResponse(BaseModel):
    keys_deleted: int
    scope: str


def _require_super_admin_caller(token: str) -> None:
    """Both calls hit the database, so callers run this in a worker thread."""
    caller = validate_and_extract_author_details(token=token)
    require_super_admin(caller)


@cms_cache_router.delete("", status_code=status.HTTP_200_OK, response_model=CacheFlushResponse)
async def flush_cache(
    cache_type: Annotated[
        Optional[CacheType],
        Query(description="Flush one namespace only, e.g. series_list. Omit to flush everything."),
    ] = None,
    hash_key: Annotated[
        Optional[str],
        Query(description="Evict a single cached entry by its hash key. Takes precedence over cache_type."),
    ] = None,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
) -> CacheFlushResponse:
    """Flush cached responses.

    Super admin only: a flush is cheap to recover from but it sends every
    subsequent request to the database at once, which is the last thing a busy
    instance needs. Realtime state (live recitation position, chat presence) is
    not cache and is never touched.
    """
    await run_in_threadpool(_require_super_admin_caller, token)

    if hash_key:
        deleted = await flush_cache_key(hash_key=hash_key)
        return CacheFlushResponse(keys_deleted=int(deleted), scope=f"key:{hash_key}")

    deleted = await flush_response_cache(cache_type=cache_type)
    return CacheFlushResponse(
        keys_deleted=deleted,
        scope=cache_type.value if cache_type else "all",
    )
