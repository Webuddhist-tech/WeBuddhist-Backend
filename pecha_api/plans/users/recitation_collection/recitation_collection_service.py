import logging
import uuid as uuid_lib
from uuid import UUID
from datetime import datetime
from fastapi import HTTPException, UploadFile
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.config import get
from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.texts.texts_openpecha_service import get_texts_by_edition_or_text_ids
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.utils import Utils
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.media.media_response_models import PlanUploadResponse
from pecha_api.plans.media.media_services import prepare_image_upload, validate_file
from pecha_api.plans.response_message import (
    DUPLICATE_DISPLAY_ORDER,
    IMAGE_UPLOAD_SUCCESS,
    NOT_FOUND,
    BAD_REQUEST,
)

from pecha_api.plans.users.recitation_collection.recitation_collection_models import (
    RecitationCollection,
    RecitationCollectionItem
)
from pecha_api.plans.users.recitation_collection.recitation_collection_repository import (
    get_user_collections,
    get_collection_item_counts,
    get_collection_by_id,
    get_collection_items,
    get_collection_item_by_id,
    save_collection,
    update_collection,
    get_max_display_order_for_collection,
    collection_item_display_order_taken,
    save_collection_items,
    update_collection_item,
    delete_collection,
    soft_delete_collection_item
)
from pecha_api.plans.users.recitation_collection.recitation_collection_response_models import (
    RecitationCollectionDTO,
    RecitationCollectionDetailDTO,
    RecitationCollectionItemDTO,
    RecitationCollectionsResponse,
    CreateCollectionRequest,
    CreateCollectionResponse,
    UpdateCollectionRequest,
    UpdateCollectionItemRequest,
    AddItemsRequest,
    AddItemsResponse
)

logger = logging.getLogger(__name__)


def _generate_presigned_url(s3_key: str) -> str | None:
    """Safely generate presigned URL for S3 key."""
    if not s3_key:
        return None
    try:
        return generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=s3_key
        )
    except Exception as e:
        logger.error(f"Failed to generate presigned URL for {s3_key}: {e}")
        return None


async def get_user_collections_service(
    token: str,
    skip: int = 0,
    limit: int = 20
) -> RecitationCollectionsResponse:

    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        collections, total = get_user_collections(
            db=db,
            user_id=current_user.id,
            skip=skip,
            limit=limit
        )
        
        if not collections:
            return RecitationCollectionsResponse(
                collections=[],
                skip=skip,
                limit=limit,
                total=0
            )
        
        collection_ids = [c.id for c in collections]
        item_counts = get_collection_item_counts(db=db, collection_ids=collection_ids)
        
        collections_dto = [
            RecitationCollectionDTO(
                id=collection.id,
                name=collection.name,
                img_url=_generate_presigned_url(collection.img_url),
                item_count=item_counts.get(collection.id, 0),
                created_at=collection.created_at,
                updated_at=collection.updated_at
            )
            for collection in collections
        ]
        
        return RecitationCollectionsResponse(
            collections=collections_dto,
            skip=skip,
            limit=limit,
            total=total
        )


async def get_collection_detail_service(
    token: str,
    collection_id: UUID
) -> RecitationCollectionDetailDTO:

    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            user_id=current_user.id
        )
        
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error=NOT_FOUND, message=f"Collection with ID {collection_id} not found").model_dump()
            )

        items = get_collection_items(db=db, collection_id=collection_id)
        
        if not items:
            return RecitationCollectionDetailDTO(
                id=collection.id,
                name=collection.name,
                img_url=_generate_presigned_url(collection.img_url),
                created_at=collection.created_at,
                updated_at=collection.updated_at,
                items=[]
            )
        
        text_ids = [str(item.text_id) for item in items]
        texts_dict = await get_texts_by_edition_or_text_ids(text_ids)

        items_dto = []
        for item in items:
            text_id_str = str(item.text_id)
            if text_id_str in texts_dict:
                text = texts_dict[text_id_str]
                items_dto.append(
                    RecitationCollectionItemDTO(
                        id=item.id,
                        text_id=item.text_id,
                        title=text.title,
                        language=text.language,
                        type=None,
                        display_order=item.display_order
                    )
                )

        return RecitationCollectionDetailDTO(
            id=collection.id,
            name=collection.name,
            img_url=_generate_presigned_url(collection.img_url),
            created_at=collection.created_at,
            updated_at=collection.updated_at,
            items=items_dto
        )


async def create_collection_service(
    token: str,
    request: CreateCollectionRequest
) -> CreateCollectionResponse:

    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        now = datetime.utcnow().isoformat()
        
        new_collection = RecitationCollection(
            user_id=current_user.id,
            name=request.name,
            img_url=Utils.extract_s3_key(presigned_url=request.img_url),
            created_at=now,
            updated_at=now
        )
        
        saved_collection = save_collection(db=db, collection=new_collection)
        
        return CreateCollectionResponse(
            id=saved_collection.id,
            name=saved_collection.name,
            img_url=_generate_presigned_url(saved_collection.img_url),
            created_at=saved_collection.created_at,
            updated_at=saved_collection.updated_at
        )


async def update_collection_service(
    token: str,
    collection_id: UUID,
    request: UpdateCollectionRequest
) -> CreateCollectionResponse:

    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            user_id=current_user.id
        )
        validate_collection_exists(collection, collection_id)

        if request.name is not None:
            collection.name = request.name
        if request.img_url is not None:
            collection.img_url = Utils.extract_s3_key(presigned_url=request.img_url)
        collection.updated_at = datetime.utcnow().isoformat()

        updated_collection = update_collection(db=db, collection=collection)

        return CreateCollectionResponse(
            id=updated_collection.id,
            name=updated_collection.name,
            img_url=_generate_presigned_url(updated_collection.img_url),
            created_at=updated_collection.created_at,
            updated_at=updated_collection.updated_at
        )


def upload_collection_image_service(
    token: str,
    file: UploadFile
) -> PlanUploadResponse:
    """Upload an image for a user's recitation collection and return its URL.

    The returned ``key`` is what callers pass back as ``img_url`` when
    creating or updating a collection.
    """
    current_user = validate_and_extract_user_details(token=token)

    validate_file(file)

    unique_id = str(uuid_lib.uuid4())
    path = "images/recitation_collection_images"
    image_path_full = f"{path}/{current_user.id}/{unique_id}"

    image_url_model, original_key = prepare_image_upload(
        file=file,
        image_path_full=image_path_full,
    )

    return PlanUploadResponse(
        image=image_url_model,
        key=original_key,
        path=image_path_full,
        message=IMAGE_UPLOAD_SUCCESS,
    )


def validate_collection_exists(collection, collection_id: UUID):
    if not collection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ResponseError(error=NOT_FOUND, message=f"Collection with ID {collection_id} not found").model_dump()
        )


def create_collection_items(
    collection_id: UUID,
    text_ids: list[str],
    start_order: float
) -> list[RecitationCollectionItem]:
    return [
        RecitationCollectionItem(
            recitation_collection_id=collection_id,
            text_id=str(text_id),
            display_order=start_order + idx
        )
        for idx, text_id in enumerate(text_ids)
    ]


async def build_items_dto(
    saved_items: list[RecitationCollectionItem]
) -> list[RecitationCollectionItemDTO]:
    text_ids_str = [str(item.text_id) for item in saved_items]
    texts_dict = await get_texts_by_edition_or_text_ids(text_ids_str)

    items_dto = []
    for item in saved_items:
        text_id_str = str(item.text_id)
        if text_id_str in texts_dict:
            text = texts_dict[text_id_str]
            items_dto.append(
                RecitationCollectionItemDTO(
                    id=item.id,
                    text_id=item.text_id,
                    title=text.title,
                    language=text.language,
                    type=None,
                    display_order=item.display_order
                )
            )
    return items_dto


async def add_items_to_collection_service(
    token: str,
    collection_id: UUID,
    request: AddItemsRequest
) -> AddItemsResponse:

    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            user_id=current_user.id
        )
        validate_collection_exists(collection, collection_id)

        max_order = get_max_display_order_for_collection(db=db, collection_id=collection_id)
        start_order = (max_order or 0) + 1
        
        new_items = create_collection_items(collection_id, request.text_ids, start_order)
        saved_items = save_collection_items(db=db, items=new_items)
        items_dto = await build_items_dto(saved_items)
        
        return AddItemsResponse(
            collection_id=collection_id,
            added_count=len(saved_items),
            items=items_dto
        )


async def delete_collection_service(
    token: str,
    collection_id: UUID
) -> None:

    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        collection = delete_collection(
            db=db,
            collection_id=collection_id,
            user_id=current_user.id
        )
        
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error=NOT_FOUND, message=f"Collection with ID {collection_id} not found").model_dump()
            )


async def delete_collection_item_service(
    token: str,
    collection_id: UUID,
    item_id: UUID
) -> None:

    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            user_id=current_user.id
        )
        validate_collection_exists(collection, collection_id)

        item = get_collection_item_by_id(
            db=db,
            item_id=item_id,
            collection_id=collection_id
        )

        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error=NOT_FOUND, message=f"Item with ID {item_id} not found").model_dump()
            )

        soft_delete_collection_item(db=db, item=item)


async def update_collection_item_display_order_service(
    token: str,
    collection_id: UUID,
    item_id: UUID,
    request: UpdateCollectionItemRequest,
) -> RecitationCollectionItemDTO:

    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        collection = get_collection_by_id(
            db=db,
            collection_id=collection_id,
            user_id=current_user.id
        )
        validate_collection_exists(collection, collection_id)

        item = get_collection_item_by_id(
            db=db,
            item_id=item_id,
            collection_id=collection_id
        )
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=NOT_FOUND,
                    message=f"Item with ID {item_id} not found"
                ).model_dump()
            )

        if item.display_order != request.display_order:
            if collection_item_display_order_taken(
                db=db,
                collection_id=collection_id,
                display_order=request.display_order,
                exclude_item_id=item.id,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ResponseError(
                        error=BAD_REQUEST,
                        message=DUPLICATE_DISPLAY_ORDER
                    ).model_dump()
                )
            item.display_order = request.display_order
            item = update_collection_item(db=db, item=item)

        items_dto = await build_items_dto([item])
        if items_dto:
            return items_dto[0]
        return RecitationCollectionItemDTO(
            id=item.id,
            text_id=item.text_id,
            title="",
            language=None,
            type=None,
            display_order=item.display_order,
        )
