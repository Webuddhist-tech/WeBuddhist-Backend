from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.group_recitation_collection.cms_service import (
    cms_add_items_service,
    cms_create_collection_service,
    cms_delete_collection_service,
    cms_delete_item_service,
    cms_get_group_collection_detail_service,
    cms_list_group_collections_service,
    cms_reorder_items_service,
    cms_update_collection_service,
)
from pecha_api.group_assets.item_assets_service import set_item_audio_service
from pecha_api.group_assets.response_models import SetItemAudioRequest
from pecha_api.group_recitation_collection.response_models import (
    AddGroupRecitationCollectionItemsRequest,
    AddGroupRecitationCollectionItemsResponse,
    CreateGroupRecitationCollectionRequest,
    GroupRecitationCollectionDetailDTO,
    GroupRecitationCollectionsResponse,
    ReorderGroupRecitationCollectionItemsRequest,
    UpdateGroupRecitationCollectionRequest,
)

oauth2_scheme = HTTPBearer()

cms_group_recitation_collection_router = APIRouter(
    prefix="/cms/author/groups/{group_id}/recitation-collections",
    tags=["CMS Group Recitation Collections"],
)


@cms_group_recitation_collection_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=GroupRecitationCollectionsResponse,
)
def cms_list_group_recitation_collections(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """List all recitation collections for a group (CMS)."""
    return cms_list_group_collections_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        skip=skip,
        limit=limit,
    )


@cms_group_recitation_collection_router.get(
    "/{collection_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupRecitationCollectionDetailDTO,
)
async def cms_get_group_recitation_collection_detail(
    group_id: UUID,
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Get a specific recitation collection with its items (CMS)."""
    return await cms_get_group_collection_detail_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        collection_id=collection_id,
    )


@cms_group_recitation_collection_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupRecitationCollectionDetailDTO,
)
def cms_create_group_recitation_collection(
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: CreateGroupRecitationCollectionRequest,
):
    """Create a new recitation collection for a group."""
    return cms_create_collection_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        request=request,
    )


@cms_group_recitation_collection_router.patch(
    "/{collection_id}",
    status_code=status.HTTP_200_OK,
    response_model=GroupRecitationCollectionDetailDTO,
)
def cms_update_group_recitation_collection(
    group_id: UUID,
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: UpdateGroupRecitationCollectionRequest,
):
    """Update a recitation collection."""
    return cms_update_collection_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        collection_id=collection_id,
        request=request,
    )


@cms_group_recitation_collection_router.delete(
    "/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def cms_delete_group_recitation_collection(
    group_id: UUID,
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Delete a recitation collection (soft delete)."""
    cms_delete_collection_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        collection_id=collection_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@cms_group_recitation_collection_router.post(
    "/{collection_id}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=AddGroupRecitationCollectionItemsResponse,
)
async def cms_add_items_to_collection(
    group_id: UUID,
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: AddGroupRecitationCollectionItemsRequest,
):
    """Add items to a recitation collection."""
    return await cms_add_items_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        collection_id=collection_id,
        text_ids=request.text_ids,
    )


@cms_group_recitation_collection_router.delete(
    "/{collection_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def cms_delete_collection_item(
    group_id: UUID,
    collection_id: UUID,
    item_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Delete an item from a recitation collection (soft delete)."""
    cms_delete_item_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        collection_id=collection_id,
        item_id=item_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@cms_group_recitation_collection_router.put(
    "/{collection_id}/items/{item_id}/audio",
    status_code=status.HTTP_200_OK,
    response_model=GroupRecitationCollectionDetailDTO,
)
async def cms_set_collection_item_audio(
    group_id: UUID,
    collection_id: UUID,
    item_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: SetItemAudioRequest,
) -> GroupRecitationCollectionDetailDTO:
    """Set an item's ordered audio.

    The array is the state: this links, unlinks and reorders in one call.
    """
    return await set_item_audio_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        collection_id=collection_id,
        item_id=item_id,
        asset_ids=request.asset_ids,
    )


@cms_group_recitation_collection_router.put(
    "/{collection_id}/items/reorder",
    status_code=status.HTTP_200_OK,
    response_model=GroupRecitationCollectionDetailDTO,
)
async def cms_reorder_collection_items(
    group_id: UUID,
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: ReorderGroupRecitationCollectionItemsRequest,
):
    """Reorder items in a recitation collection."""
    return await cms_reorder_items_service(
        token=authentication_credential.credentials,
        group_id=group_id,
        collection_id=collection_id,
        item_ids=request.item_ids,
    )
