from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.group_assets.enums import GroupAssetType
from pecha_api.group_assets.response_models import (
    GroupAssetDTO,
    GroupAssetsResponse,
    UpdateGroupAssetRequest,
)
from pecha_api.group_assets.service import (
    delete_group_asset_service,
    list_group_assets_service,
    update_group_asset_service,
    upload_group_asset_service,
)

oauth2_scheme = HTTPBearer()

cms_group_assets_router = APIRouter(
    prefix="/cms/author/groups/{group_id}/assets",
    tags=["CMS Group Assets"],
)


@cms_group_assets_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupAssetDTO,
)
def cms_upload_group_asset(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    file: Annotated[UploadFile, File()],
    asset_type: Annotated[GroupAssetType, Form()],
    title: Annotated[Optional[str], Form()] = None,
    duration_ms: Annotated[Optional[int], Form()] = None,
):
    """Upload a file into this group's asset library.

    One file per call, and uploading links it to nothing.
    """
    return upload_group_asset_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        file=file,
        asset_type=asset_type,
        title=title,
        duration_ms=duration_ms,
    )


@cms_group_assets_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=GroupAssetsResponse,
)
def cms_list_group_assets(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    asset_type: Optional[GroupAssetType] = None,
    search: Optional[str] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """List and search this group's assets. Newest first."""
    return list_group_assets_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        asset_type=asset_type,
        search=search,
        skip=skip,
        limit=limit,
    )


@cms_group_assets_router.patch(
    "/{asset_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupAssetDTO,
)
def cms_update_group_asset(
    group_id: UUID,
    asset_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: UpdateGroupAssetRequest,
):
    """Rename an asset."""
    return update_group_asset_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        asset_id=asset_id,
        request=request,
    )


@cms_group_assets_router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cms_delete_group_asset(
    group_id: UUID,
    asset_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    force: bool = False,
):
    """Remove an asset from the library.

    Returns 409 with its usages when it is still linked; pass force=true to
    drop those links and delete anyway.
    """
    await delete_group_asset_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        asset_id=asset_id,
        force=force,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
