from fastapi import APIRouter, Query, Depends, File, UploadFile
from starlette import status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated
from uuid import UUID

from pecha_api.plans.media.media_response_models import PlanUploadResponse
from pecha_api.plans.users.recitation_collection.recitation_collection_response_models import (
    RecitationCollectionsResponse,
    RecitationCollectionDetailDTO,
    RecitationCollectionItemDTO,
    CreateCollectionRequest,
    CreateCollectionResponse,
    UpdateCollectionRequest,
    UpdateCollectionItemRequest,
    AddItemsRequest,
    AddItemsResponse
)
from pecha_api.plans.users.recitation_collection.recitation_collection_service import (
    get_user_collections_service,
    get_collection_detail_service,
    create_collection_service,
    update_collection_service,
    upload_collection_image_service,
    add_items_to_collection_service,
    delete_collection_service,
    delete_collection_item_service,
    update_collection_item_display_order_service
)

oauth2_scheme = HTTPBearer()

recitation_collection_router = APIRouter(
    prefix="/users/me/recitation-collections",
    tags=["Recitation Collections"]
)


@recitation_collection_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=RecitationCollectionsResponse
)
async def get_user_collections(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50)
):

    return await get_user_collections_service(
        token=authentication_credential.credentials,
        skip=skip,
        limit=limit
    )


@recitation_collection_router.get(
    "/{collection_id}",
    status_code=status.HTTP_200_OK,
    response_model=RecitationCollectionDetailDTO
)
async def get_collection_detail(
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):

    return await get_collection_detail_service(
        token=authentication_credential.credentials,
        collection_id=collection_id
    )


@recitation_collection_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateCollectionResponse
)
async def create_collection(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: CreateCollectionRequest
):

    return await create_collection_service(
        token=authentication_credential.credentials,
        request=request
    )


@recitation_collection_router.put(
    "/{collection_id}",
    status_code=status.HTTP_200_OK,
    response_model=CreateCollectionResponse
)
async def update_collection(
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: UpdateCollectionRequest
):

    return await update_collection_service(
        token=authentication_credential.credentials,
        collection_id=collection_id,
        request=request
    )


@recitation_collection_router.post(
    "/upload-image",
    status_code=status.HTTP_201_CREATED,
    response_model=PlanUploadResponse
)
async def upload_collection_image(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    file: UploadFile = File(...)
):
    """Upload an image for a recitation collection and get its URL back.

    Call this first, then pass the returned ``key`` as ``img_url`` when
    creating or updating a collection.
    """
    return upload_collection_image_service(
        token=authentication_credential.credentials,
        file=file
    )


@recitation_collection_router.post(
    "/{collection_id}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=AddItemsResponse
)
async def add_items_to_collection(
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: AddItemsRequest
):

    return await add_items_to_collection_service(
        token=authentication_credential.credentials,
        collection_id=collection_id,
        request=request
    )


@recitation_collection_router.delete(
    "/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_collection(
    collection_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):

    await delete_collection_service(
        token=authentication_credential.credentials,
        collection_id=collection_id
    )


@recitation_collection_router.patch(
    "/{collection_id}/items/{item_id}",
    status_code=status.HTTP_200_OK,
    response_model=RecitationCollectionItemDTO
)
async def update_collection_item_display_order(
    collection_id: UUID,
    item_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    request: UpdateCollectionItemRequest
):
    """Update a collection item's display_order.

    The value can be fractional (e.g. 1.4) so an item can sit between
    neighbors. It must be unique among active items in the collection.
    Newly added items continue from the current max + 1.
    """
    return await update_collection_item_display_order_service(
        token=authentication_credential.credentials,
        collection_id=collection_id,
        item_id=item_id,
        request=request
    )


@recitation_collection_router.delete(
    "/{collection_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_collection_item(
    collection_id: UUID,
    item_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):

    await delete_collection_item_service(
        token=authentication_credential.credentials,
        collection_id=collection_id,
        item_id=item_id
    )
