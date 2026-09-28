import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from uuid import UUID, uuid4

from fastapi import HTTPException
from starlette import status
from starlette.concurrency import run_in_threadpool

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
from ..texts.texts_openpecha_service import get_texts_by_edition_or_text_ids
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

logger = logging.getLogger(__name__)


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


async def _resolve_preset_text_titles(text_ids: List[str]) -> Dict[str, str]:
    """One batched OpenPecha lookup for every distinct edition on the page."""
    unique_ids = list(dict.fromkeys(text_id for text_id in text_ids if text_id))
    if not unique_ids:
        return {}
    try:
        texts = await get_texts_by_edition_or_text_ids(unique_ids)
    except Exception:
        logger.exception("Failed to resolve preset text titles")
        return {}
    titles: Dict[str, str] = {}
    for text_id, text in texts.items():
        title = (text.title or "").strip()
        if title:
            titles[text_id] = title
    return titles


async def _with_text_title(
    preset: CMSPublicAccumulatorDTO,
) -> CMSPublicAccumulatorDTO:
    """Fills `text_title` for one preset, so a single preset carries the same
    field the list does rather than dropping it for whoever reads it next."""
    if not preset.text_id:
        return preset
    titles = await _resolve_preset_text_titles([preset.text_id])
    title = titles.get(preset.text_id)
    if not title:
        return preset
    return preset.model_copy(update={"text_title": title})


def _list_presets_sync(
    skip: int,
    limit: int,
    search: Optional[str],
    language: Optional[str],
) -> Tuple[List[CMSPublicAccumulatorDTO], int]:
    """The synchronous half of the listing.

    Kept apart so the async service can hand it to a worker thread: these are
    blocking SQLAlchemy calls, and running them inline would stall the event
    loop for every other request while a slow preset or mantra query ran.
    """
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
        presets = [
            convert_accumulator_to_public_dto(
                accumulator,
                mantras_by_id=mantras_by_id,
                language=language,
                include_key=True,
            )
            for accumulator in accumulators
        ]
    return presets, total


def _get_preset_sync(
    preset_id: UUID,
    language: Optional[str],
) -> CMSPublicAccumulatorDTO:
    """The synchronous half of the by-id read; see _list_presets_sync."""
    with SessionLocal() as db:
        preset = get_preset_by_id(db, preset_id)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": PRESET_NOT_FOUND},
            )
        return _to_public_dto(db, preset, language=language)


async def list_preset_accumulators_cms_service(
    token: str,
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    language: Optional[str] = None,
) -> CMSPublicAccumulatorsResponse:
    validate_cms_author_details(token=token)

    presets, total = await run_in_threadpool(
        _list_presets_sync,
        skip=skip,
        limit=limit,
        search=search,
        language=language,
    )

    titles = await _resolve_preset_text_titles(
        [preset.text_id for preset in presets if preset.text_id]
    )
    if titles:
        presets = [
            preset.model_copy(update={"text_title": titles[preset.text_id]})
            if preset.text_id in titles
            else preset
            for preset in presets
        ]

    return CMSPublicAccumulatorsResponse(
        accumulators=presets,
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_preset_accumulator_cms_service(
    token: str,
    preset_id: UUID,
    language: Optional[str] = None,
) -> CMSPublicAccumulatorDTO:
    validate_cms_author_details(token=token)

    preset = await run_in_threadpool(
        _get_preset_sync,
        preset_id=preset_id,
        language=language,
    )
    return await _with_text_title(preset)


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
        created = _to_public_dto(db, saved)

    return await _with_text_title(created)


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
        updated_dto = _to_public_dto(db, updated)

    return await _with_text_title(updated_dto)


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
