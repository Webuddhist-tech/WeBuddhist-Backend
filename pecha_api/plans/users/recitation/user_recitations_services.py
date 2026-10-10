from uuid import UUID
from typing import Dict, List

from pecha_api.db.database import SessionLocal
from pecha_api.texts.texts_openpecha_service import (
    ensure_text_or_edition_exists,
    get_texts_by_edition_or_text_ids,
)
from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.plans.users.recitation.user_recitations_models import UserRecitations
from pecha_api.plans.users.recitation.user_recitations_repository import (
    save_user_recitation,
    get_user_recitations_by_user_id,
    get_max_display_order_for_user,
    update_recitation_order_in_bulk,
    delete_user_recitation,
)
from pecha_api.plans.users.recitation.user_recitations_response_models import (
    CreateUserRecitationRequest,
    UserRecitationsResponse,
    UserRecitationDTO,
    UpdateRecitationOrderRequest,
)
from pecha_api.recitations.recitations_repository import get_text_images_by_text_ids
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.config import get


def get_image_url_map_by_text_ids(db, text_ids: list) -> Dict[str, str]:
    image_keys = get_text_images_by_text_ids(db=db, text_ids=text_ids)

    image_url_map = {
        text_id: generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"),
            s3_key=s3_key,
        )
        for text_id, s3_key in image_keys.items()
    }

    return image_url_map


async def _build_recitation_dtos(db, user_id: UUID) -> List[UserRecitationDTO]:
    user_recitations = get_user_recitations_by_user_id(db=db, user_id=user_id)
    if not user_recitations:
        return []

    text_ids = [str(recitation.text_id) for recitation in user_recitations]
    texts_dict = await get_texts_by_edition_or_text_ids(text_ids)
    image_url_map = get_image_url_map_by_text_ids(db=db, text_ids=text_ids)

    return [
        UserRecitationDTO(
            title=texts_dict[str(recitation.text_id)].title,
            text_id=recitation.text_id,
            image_url=image_url_map.get(str(recitation.text_id)),
            language=texts_dict[str(recitation.text_id)].language,
            display_order=recitation.display_order,
        )
        for recitation in user_recitations
        if str(recitation.text_id) in texts_dict
    ]


async def create_user_recitation_service(
    token: str, create_user_recitation_request: CreateUserRecitationRequest
) -> None:
    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        await ensure_text_or_edition_exists(
            str(create_user_recitation_request.text_id)
        )

        max_order = get_max_display_order_for_user(db=db, user_id=current_user.id)
        next_order = (max_order or 0) + 1

        new_user_recitations = UserRecitations(
            user_id=current_user.id,
            text_id=str(create_user_recitation_request.text_id),
            display_order=next_order,
        )
        save_user_recitation(db=db, user_recitations=new_user_recitations)


async def get_user_recitations_service(token: str) -> UserRecitationsResponse:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        items = await _build_recitation_dtos(db=db, user_id=current_user.id)
        return UserRecitationsResponse(recitations=items)


async def update_recitation_order_service(
    token: str, update_order_request: UpdateRecitationOrderRequest
) -> None:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        recitation_updates = [
            {"text_id": str(item.text_id), "display_order": item.display_order}
            for item in update_order_request.recitations
        ]
        update_recitation_order_in_bulk(
            db=db, user_id=current_user.id, recitation_updates=recitation_updates
        )


async def delete_user_recitation_service(token: str, text_id: str) -> None:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        delete_user_recitation(db=db, user_id=current_user.id, text_id=text_id)
