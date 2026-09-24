from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.plans.dashboard.dashboard_response_models import (
    DashboardItemsResponse,
    DashboardTab,
)
from pecha_api.plans.dashboard.dashboard_service import get_dashboard_items_list, get_practice_items_list
from pecha_api.plans.plans_enums import PlanStatus

oauth2_scheme = HTTPBearer()

dashboard_router = APIRouter(
    prefix="/cms/dashboard",
    tags=["CMS Dashboard"],
)

practice_router = APIRouter(
    prefix="/practice",
    tags=["Practice"],
)


@dashboard_router.get(
    "/items",
    status_code=status.HTTP_200_OK,
    response_model=DashboardItemsResponse,
)
async def list_dashboard_items(
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
    tab: Annotated[DashboardTab, Query()] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[Optional[str], Query()] = None,
    status: Annotated[Optional[PlanStatus], Query()] = None,
    language: Annotated[Optional[str], Query()] = None,
    featured: Annotated[Optional[bool], Query()] = None,
    group_id: Annotated[Optional[UUID], Query(description="Filter by author group")] = None,
    include_partner_groups: Annotated[
        bool,
        Query(description="Also include series/plans the group is a SeriesPartner of"),
    ] = False,
):
    return get_dashboard_items_list(
        token=authentication_credential.credentials,
        tab=tab,
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        language=language,
        featured=featured,
        group_id=group_id,
        include_partner_groups=include_partner_groups,
    )


@practice_router.get(
    "/items",
    status_code=status.HTTP_200_OK,
    response_model=DashboardItemsResponse,
)
async def list_practice_items(
    tab: Annotated[DashboardTab, Query()] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[Optional[str], Query()] = None,
    language: Annotated[Optional[str], Query()] = None,
    featured: Annotated[Optional[bool], Query()] = None,
):
    return get_practice_items_list(
        tab=tab,
        page=page,
        page_size=page_size,
        search=search,
        language=language,
        featured=featured,
    )
