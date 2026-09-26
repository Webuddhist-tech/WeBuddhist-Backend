from typing import Optional, List

from sqlalchemy.orm import Session
from uuid import UUID, uuid4

from fastapi import HTTPException
from starlette import status

from ..db.database import SessionLocal
from ..plans.authors.plan_authors_service import validate_cms_author_details
from ..mantra.mantra_repository import get_mantras_by_ids
from .accumulator_enums import AccumulatorType
from .accumulator_metadata_model import AccumulatorMetadata
from .accumulator_models import Accumulator
from .accumulator_repository import (
    get_all_accumulators,
    get_preset_by_id,
    get_mala_image_by_id,
    save_accumulator,
    update_accumulator,
    delete_accumulator,
)
from .accumulator_response_models import (
    AccumulatorMetadataDTO,
    CreatePresetAccumulatorRequest,
    UpdatePresetAccumulatorRequest,
    CMSPublicAccumulatorDTO,
    CMSPublicAccumulatorsResponse,
)
from .accumulator_service import (
    convert_accumulator_to_public_dto,
    validate_mantra_exists,
)
from .response_message import (
    NOT_FOUND,
    FORBIDDEN,
    PRESET_NOT_FOUND,
    MALA_IMAGE_NOT_FOUND,
    ONLY_PRESET_ACCUMULATORS_CAN_BE_UPDATED,
    ONLY_PRESET_ACCUMULATORS_CAN_BE_DELETED,
)


def _build_metadata_entries(
    metadata: List[AccumulatorMetadataDTO],
) -> List[AccumulatorMetadata]:
    return [
        AccumulatorMetadata(
            id=uuid4(),
            name=entry.name.strip(),
            description=entry.description,
            language=entry.language,
        )
        for entry in metadata
    ]


def _to_public_dto(
    db: Session, accumulator: Accumulator, language: Optional[str] = None
) -> CMSPublicAccumulatorDTO:
    mantras_by_id = {}
    if accumulator.mantra_id is not None:
        mantras_by_id = get_mantras_by_ids(db, [accumulator.mantra_id])
    return convert_accumulator_to_public_dto(
        accumulator,
        mantras_by_id=mantras_by_id,
        language=language,
        include_key=True,
    )


def _validate_optional_mala_image(db: Session, mala_image_id: Optional[UUID]) -> None:
    if mala_image_id is None:
        return
    mala = get_mala_image_by_id(db, mala_image_id)
    if mala is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": NOT_FOUND, "message": MALA_IMAGE_NOT_FOUND},
        )


def list_preset_accumulators_cms_service(
    token: str,
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    language: Optional[str] = None,
) -> CMSPublicAccumulatorsResponse:
    validate_cms_author_details(token=token)

    with SessionLocal() as db:
        # CMS always includes text-linked (recitation) presets.
        accumulators, total = get_all_accumulators(
            db,
            skip,
            limit,
            search=search,
            show_recitations=True,
        )
        mantra_ids = [a.mantra_id for a in accumulators if a.mantra_id is not None]
        mantras_by_id = get_mantras_by_ids(db, mantra_ids)
        return CMSPublicAccumulatorsResponse(
            accumulators=[
                convert_accumulator_to_public_dto(a, mantras_by_id=mantras_by_id, language=language, include_key=True)
                for a in accumulators
            ],
            total=total,
            skip=skip,
            limit=limit,
        )


def get_preset_accumulator_cms_service(
    token: str,
    preset_id: UUID,
    language: Optional[str] = None,
) -> CMSPublicAccumulatorDTO:
    validate_cms_author_details(token=token)

    with SessionLocal() as db:
        preset = get_preset_by_id(db, preset_id)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": PRESET_NOT_FOUND},
            )
        return _to_public_dto(db, preset, language=language)


async def create_preset_accumulator_cms_service(
    token: str,
    request: CreatePresetAccumulatorRequest,
) -> CMSPublicAccumulatorDTO:
    validate_cms_author_details(token=token)

    with SessionLocal() as db:
        if request.mantra_id is not None:
            validate_mantra_exists(db, request.mantra_id)
        _validate_optional_mala_image(db, request.mala_image_id)

        preset = Accumulator(
            id=uuid4(),
            user_id=None,
            group_id=None,
            parent_id=None,
            type=AccumulatorType.PRESET,
            target_count=request.target_count,
            current_count=0,
            text_id=request.text_id,
            mantra_id=request.mantra_id,
            mala_image=request.mala_image_id,
        )
        preset.metadata_entries = _build_metadata_entries(request.metadata)
        saved = save_accumulator(db, preset)
        return _to_public_dto(db, saved)


async def update_preset_accumulator_cms_service(
    token: str,
    preset_id: UUID,
    request: UpdatePresetAccumulatorRequest,
) -> CMSPublicAccumulatorDTO:
    validate_cms_author_details(token=token)

    with SessionLocal() as db:
        preset = get_preset_by_id(db, preset_id)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": PRESET_NOT_FOUND},
            )

        preset_type = preset.type.value if hasattr(preset.type, "value") else preset.type
        if preset_type != AccumulatorType.PRESET.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ONLY_PRESET_ACCUMULATORS_CAN_BE_UPDATED},
            )

        if request.target_count is not None:
            preset.target_count = request.target_count
        if request.text_id is not None:
            preset.text_id = request.text_id
        if request.mantra_id is not None:
            validate_mantra_exists(db, request.mantra_id)
            preset.mantra_id = request.mantra_id
        if request.mala_image_id is not None:
            _validate_optional_mala_image(db, request.mala_image_id)
            preset.mala_image = request.mala_image_id
        if request.metadata is not None:
            preset.metadata_entries.clear()
            preset.metadata_entries.extend(_build_metadata_entries(request.metadata))

        updated = update_accumulator(db, preset)
        return _to_public_dto(db, updated)


def delete_preset_accumulator_cms_service(token: str, preset_id: UUID) -> None:
    validate_cms_author_details(token=token)

    with SessionLocal() as db:
        preset = get_preset_by_id(db, preset_id)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": PRESET_NOT_FOUND},
            )

        preset_type = preset.type.value if hasattr(preset.type, "value") else preset.type
        if preset_type != AccumulatorType.PRESET.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ONLY_PRESET_ACCUMULATORS_CAN_BE_DELETED},
            )

        delete_accumulator(db, preset)
