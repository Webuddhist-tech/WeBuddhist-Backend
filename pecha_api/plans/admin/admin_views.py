from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from starlette import status

from pecha_api.plans.admin.admin_response_models import (
    AdminAuthorActivateResponse,
    AdminAuthorDetailDTO,
    AdminAuthorListResponse,
    AdminAuthorPlatformRoleUpdate,
)
from pecha_api.plans.admin.admin_service import (
    activate_author,
    get_admin_author_detail,
    list_admin_authors,
    suspend_author,
    update_author_platform_role,
)
from pecha_api.plans.auth.cms_auth_deps import get_cms_author_token
from pecha_api.plans.auth.plan_auth_enums import AuthorStatus
from pecha_api.plans.platform_enums import PlatformRole

cms_admin_router = APIRouter(prefix="/cms/admin/authors", tags=["CMS Admin Authors"])


@cms_admin_router.get("", status_code=status.HTTP_200_OK, response_model=AdminAuthorListResponse)
def get_cms_admin_authors(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    is_verified: Annotated[Optional[bool], Query()] = None,
    is_active: Annotated[Optional[bool], Query()] = None,
    platform_role: Annotated[Optional[PlatformRole], Query()] = None,
    search: Annotated[Optional[str], Query()] = None,
    account_status: Annotated[
        Optional[AuthorStatus],
        Query(description="ACTIVE, SUSPENDED, or INACTIVE (never signed in to the Studio)"),
    ] = None,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
):
    return list_admin_authors(
        token=token,
        skip=skip,
        limit=limit,
        is_verified=is_verified,
        is_active=is_active,
        platform_role=platform_role,
        search=search,
        account_status_filter=account_status,
    )


@cms_admin_router.get("/{author_id}", status_code=status.HTTP_200_OK, response_model=AdminAuthorDetailDTO)
def get_cms_admin_author_detail(
    author_id: UUID,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
):
    return get_admin_author_detail(token=token, author_id=author_id)


@cms_admin_router.post("/{author_id}/activate", status_code=status.HTTP_200_OK, response_model=AdminAuthorActivateResponse)
def post_cms_admin_author_activate(
    author_id: UUID,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
):
    return activate_author(token=token, author_id=author_id)


@cms_admin_router.post("/{author_id}/suspend", status_code=status.HTTP_200_OK, response_model=AdminAuthorActivateResponse)
def post_cms_admin_author_suspend(
    author_id: UUID,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
):
    return suspend_author(token=token, author_id=author_id)


@cms_admin_router.patch("/{author_id}/platform-role", status_code=status.HTTP_200_OK, response_model=AdminAuthorDetailDTO)
def patch_cms_admin_author_platform_role(
    author_id: UUID,
    body: AdminAuthorPlatformRoleUpdate,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
):
    return update_author_platform_role(token=token, author_id=author_id, body=body)
