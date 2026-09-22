import uuid
from typing import Optional

from fastapi import HTTPException, UploadFile
from starlette import status

from ..accumulator.accumulator_repository import get_mala_image_by_id
from ..accumulator.accumulator_service import generate_mala_image_presigned_url
from ..accumulator.response_message import NOT_FOUND, MANTRA_NOT_FOUND
from ..db.database import SessionLocal
from ..plans.authors.plan_authors_service import safe_get_image_url, validate_and_extract_author_details, validate_cms_author_details
from ..plans.media.media_response_models import ImageUrlModel, PlanUploadResponse
from ..plans.media.media_services import prepare_image_upload, validate_file
from ..plans.response_message import IMAGE_UPLOAD_SUCCESS
from .mantra_model import Mantra
from .mantra_repository import get_all_mantras, get_mantra_by_id, save_mantra
from pecha_api.region_restrictions.region_restriction_enums import RestrictedItemType
from pecha_api.region_restrictions.region_restriction_service import filter_items_for_timezone
from .mantra_response_models import (
    CMSMantraDTO,
    CreateMantraRequest,
    MantraDTO,
    MantraMetadataDTO,
    MantraResponse,
    UpdateMantraRequest,
)


def resolve_deity_image(mantra: Optional[Mantra]) -> Optional[ImageUrlModel]:
    if mantra is None or not mantra.deity_image:
        return None
    return safe_get_image_url(mantra.deity_image, resource_id=mantra.id, resource_type="mantra")


def _build_mantra_dto(mantra, language: Optional[str]) -> MantraDTO:
    entries = mantra.metadata_entries
    if language:
        language_upper = language.upper()
        entries = [
            entry for entry in entries
            if entry.language.value == language_upper
        ]
    mala = mantra.mala
    return MantraDTO(
        id=mantra.id,
        audio_url=mantra.audio_url,
        mala_image_id=mala.id if mala is not None else None,
        mala_image_url=generate_mala_image_presigned_url(mala.url) if mala is not None else None,
        deity_image=resolve_deity_image(mantra),
        metadata=[MantraMetadataDTO.model_validate(entry) for entry in entries],
    )


def get_mantras_service(
    language: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> MantraResponse:

    with SessionLocal() as db:
        mantras = get_all_mantras(db, language=language)
        visible_mantras = filter_items_for_timezone(
            mantras,
            timezone_name=timezone_name,
            item_type=RestrictedItemType.MANTRA,
            id_of=lambda mantra: mantra.id,
        )

        return MantraResponse(
            mantras=[_build_mantra_dto(mantra, language) for mantra in visible_mantras]
        )


def _build_cms_mantra_dto(mantra) -> CMSMantraDTO:
    base = _build_mantra_dto(mantra, language=None)
    return CMSMantraDTO(**base.__dict__, deity_image_key=mantra.deity_image)


def create_mantra_service(token: str, request: CreateMantraRequest) -> CMSMantraDTO:
    validate_cms_author_details(token=token)

    mantra = Mantra(
        audio_url=request.audio_url,
        mala_image=request.mala_image_id,
        deity_image=request.deity_image_key,
    )

    with SessionLocal() as db:
        if request.mala_image_id is not None:
            mala = get_mala_image_by_id(db, request.mala_image_id)
            if mala is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Mala image with id '{request.mala_image_id}' does not exist",
                )

        saved = save_mantra(db, mantra, request.metadata)
        return _build_cms_mantra_dto(saved)


def update_mantra_service(token: str, mantra_id: uuid.UUID, request: UpdateMantraRequest) -> CMSMantraDTO:
    validate_cms_author_details(token=token)

    with SessionLocal() as db:
        mantra = get_mantra_by_id(db, mantra_id)
        if mantra is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": MANTRA_NOT_FOUND},
            )

        mantra.deity_image = request.deity_image_key
        db.commit()
        updated = get_mantra_by_id(db, mantra_id)
        return _build_cms_mantra_dto(updated)


def upload_mantra_image(token: str, mantra_id: uuid.UUID, file: UploadFile) -> PlanUploadResponse:
    validate_and_extract_author_details(token=token)
    validate_file(file)

    with SessionLocal() as db:
        mantra = get_mantra_by_id(db, mantra_id)
        if mantra is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": MANTRA_NOT_FOUND},
            )

    unique_id = str(uuid.uuid4())
    image_path_full = f"images/mantra_images/{mantra_id}/{unique_id}"

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
