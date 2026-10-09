from fastapi import APIRouter, Query, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from datetime import date
from starlette import status

from .verse_of_day_response_models import VerseOfDayPublicResponse, VerseOfDayListResponse, CreateVerseOfDayRequest, UpdateVerseOfDayRequest, VerseOfDayDTO
from .verse_of_day_enums import SortOrder
from .verse_of_day_service import get_verse_of_day, get_verses_of_day_list_service, get_verse_of_day_by_id_service, get_verse_of_day_today_service, create_verse_of_day_service, update_verse_of_day_service, delete_verse_of_day_service
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.users.users_service import validate_and_extract_user_details

oauth2_scheme = HTTPBearer()
oauth2_scheme_optional = HTTPBearer(auto_error=False)

verse_of_day_router = APIRouter(
    prefix="/verse-of-day",
    tags=["Verse of Day"]
)

cms_verse_of_day_router = APIRouter(
    prefix="/cms/verse-of-day",
    tags=["CMS Verse of Day"]
)


@verse_of_day_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayPublicResponse
)
def get_verse_of_day_endpoint(
    group_id: Annotated[Optional[UUID], Query(description="Filter by the linked page (group) ID")] = None,
    date: Annotated[Optional[date], Query(description="Filter by date (YYYY-MM-DD)")] = None,
    lang: Annotated[Optional[str], Query(description="Filter by language (en, bo, zh, hi, ne, mn). Returns all languages if not specified.")] = None,
):
 
    return get_verse_of_day(group_id=group_id, filter_date=date, lang=lang)


@verse_of_day_router.get(
    "/today",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayPublicResponse
)
def get_verse_of_day_today_endpoint(
    lang: Annotated[Optional[str], Query(description="Filter by language (en, bo, zh, hi, ne, mn). Returns all languages if not specified.")] = None,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone for determining today's date."),
    ] = None,
    authentication_credential: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(oauth2_scheme_optional)
    ] = None,
):
    if authentication_credential and x_timezone:
        try:
            from pecha_api.users.user_metadata_service import sync_user_timezone
            user = validate_and_extract_user_details(authentication_credential.credentials)
            sync_user_timezone(user.id, x_timezone)
        except Exception:
            pass
    
    return get_verse_of_day_today_service(lang=lang, timezone=x_timezone)


@verse_of_day_router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayPublicResponse
)
def get_verse_of_day_by_id_endpoint(
    id: UUID,
    lang: Annotated[Optional[str], Query(description="Filter by language (en, bo, zh, hi, ne, mn). Returns all languages if not specified.")] = None,
):

    return get_verse_of_day_by_id_service(verse_id=id, lang=lang)


@cms_verse_of_day_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayListResponse
)
def cms_get_verse_of_day_endpoint(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    group_id: Annotated[Optional[UUID], Query(description="Filter by the linked page (group) ID")] = None,
    date: Annotated[Optional[date], Query(description="Filter by date (YYYY-MM-DD)")] = None,
    lang: Annotated[Optional[str], Query(description="Filter by language (en, bo, zh, hi, ne, mn). Returns all languages if not specified.")] = None,
    search: Annotated[Optional[str], Query(description="Free-text search over verse content (any language)")] = None,
    sort_order: Annotated[SortOrder, Query(description="Sort by date: asc (oldest first) or desc (newest first)")] = SortOrder.DESC,
    skip: Annotated[int, Query(description="Number of records to skip", ge=0)] = 0,
    limit: Annotated[int, Query(description="Maximum number of records to return", ge=1, le=100)] = 100,
):
    validate_cms_author_details(credentials.credentials)
    return get_verses_of_day_list_service(group_id=group_id, filter_date=date, lang=lang, search=search, sort_order=sort_order, skip=skip, limit=limit)


@cms_verse_of_day_router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayPublicResponse
)
def cms_get_verse_of_day_by_id_endpoint(
    id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    lang: Annotated[Optional[str], Query(description="Filter by language (en, bo, zh, hi, ne, mn). Returns all languages if not specified.")] = None,
):
    validate_cms_author_details(credentials.credentials)
    return get_verse_of_day_by_id_service(verse_id=id, lang=lang)


@cms_verse_of_day_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=VerseOfDayDTO
)
def create_verse_of_day_endpoint(
    request: CreateVerseOfDayRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):

    author = validate_cms_author_details(credentials.credentials)
    return create_verse_of_day_service(request=request, created_by=author.email)


@cms_verse_of_day_router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_model=VerseOfDayDTO
)
def update_verse_of_day_endpoint(
    id: UUID,
    request: UpdateVerseOfDayRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):

    author = validate_cms_author_details(credentials.credentials)
    return update_verse_of_day_service(verse_id=id, request=request, updated_by=author.email)


@cms_verse_of_day_router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_verse_of_day_endpoint(
    id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):

    validate_cms_author_details(credentials.credentials)
    delete_verse_of_day_service(verse_id=id)
