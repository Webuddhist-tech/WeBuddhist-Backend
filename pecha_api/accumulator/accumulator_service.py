from typing import Dict, Optional, List
from uuid import UUID, uuid4
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status
from ..db.database import SessionLocal
from ..config import get
from ..uploads.S3_utils import generate_presigned_access_url
from ..users.users_service import validate_and_extract_user_details
from pecha_api.daily_log.daily_log_cache_service import invalidate_user_stats_cache
from ..plans.authors.plan_authors_service import get_image_url
from ..plans.shared.metadata_utils import filter_by_language_with_fallback
from .accumulator_repository import (
    get_all_accumulators,
    get_user_accumulators,
    get_preset_by_id,
    get_user_accumulator_by_parent,
    add_accumulator,
    commit_accumulator,
    get_accumulator_by_id,
    get_accumulator_with_history,
    update_accumulator,
    delete_accumulator,
    add_history_row,
    get_user_accumulator_history,
    mantra_exists,
    get_mantra_mala_image_id,
    get_mala_image_by_id,
    get_groups_by_accumulator_id
)
from ..mantra.mantra_model import Mantra
from ..mantra.mantra_metadata_model import MantraMetadata
from ..mantra.mantra_repository import get_mantra_by_id, get_mantras_by_ids
from .accumulator_response_models import (
    AccumulatorsResponse,
    AccumulatorDTO,
    AccumulatorMetadataDTO,
    PresetMantraDTO,
    CMSPresetMantraDTO,
    PublicAccumulatorDTO,
    PublicAccumulatorsResponse,
    CMSPublicAccumulatorDTO,
    CreateAccumulatorRequest,
    UpdateAccumulatorRequest,
    UpdateMalaImageRequest,
    AccumulatorHistoryResponse,
    AccumulatorHistoryDTO,
    AccumulatorSessionDTO,
    AccumulatorGroupDTO,
    AccumulatorGroupsResponse
)
from .accumulator_models import Accumulator
from .accumulator_metadata_model import AccumulatorMetadata
from .accumulator_history_model import AccumulatorHistory
from .accumulator_enums import AccumulatorType
from pecha_api.region_restrictions.region_restriction_enums import RestrictedItemType
from pecha_api.region_restrictions.region_restriction_service import (
    filter_items_for_timezone,
)
from .response_message import (
    NOT_FOUND,
    FORBIDDEN,
    CONFLICT,
    ACCUMULATOR_NOT_FOUND,
    ACCUMULATOR_ALREADY_EXISTS,
    MALA_IMAGE_NOT_FOUND,
    PRESET_NOT_FOUND,
    MANTRA_NOT_FOUND,
    ACCUMULATOR_UPDATE_NOT_ALLOWED,
    ACCUMULATOR_DELETE_NOT_ALLOWED,
    ONLY_USER_ACCUMULATORS_CAN_BE_UPDATED,
    ONLY_USER_ACCUMULATORS_CAN_BE_DELETED
)

logger = logging.getLogger(__name__)


def generate_mala_image_presigned_url(url: Optional[str]) -> Optional[str]:
    """Presign a stored mala image S3 key so the frontend can load it."""
    if not url:
        return None
    try:
        bucket_name = get("AWS_BUCKET_NAME")
        return generate_presigned_access_url(bucket_name, url)
    except Exception:
        logger.error(f"Failed to generate presigned URL for mala image: {url}", exc_info=True)
        return None


def convert_metadata_to_dto(metadata: AccumulatorMetadata) -> AccumulatorMetadataDTO:
    language = metadata.language.value if hasattr(metadata.language, 'value') else metadata.language
    return AccumulatorMetadataDTO(
        language=language,
        name=metadata.name,
        description=metadata.description,
    )


def convert_metadata_entries_to_dtos(accumulator: Accumulator) -> List[AccumulatorMetadataDTO]:
    return [convert_metadata_to_dto(entry) for entry in accumulator.metadata_entries]


def resolve_mala_image_fields(accumulator: Accumulator) -> tuple[Optional[UUID], Optional[str]]:
    """Return (mala_image_id, presigned mala_image_url) for the accumulator's
    chosen mala image, or (None, None) when none is set."""
    mala = accumulator.mala
    if mala is None:
        return None, None
    return mala.id, generate_mala_image_presigned_url(mala.url)


def resolve_accumulator_bookmark_mala_image_url(
    db: Session,
    accumulator: Accumulator,
) -> Optional[str]:
    """Presigned mala image URL for bookmark display.

    Preset accumulators prefer the linked mantra's default mala image over
    the mala image stored on the accumulator row itself.
    """
    accumulator_type = (
        accumulator.type.value
        if hasattr(accumulator.type, "value")
        else accumulator.type
    )
    if (
        accumulator_type == AccumulatorType.PRESET.value
        and accumulator.mantra_id is not None
    ):
        mantra = get_mantra_by_id(db, accumulator.mantra_id)
        if mantra is not None and mantra.mala is not None:
            return generate_mala_image_presigned_url(mantra.mala.url)

    _, mala_image_url = resolve_mala_image_fields(accumulator)
    return mala_image_url


def _single_mantra_by_id(db: Session, mantra_id: Optional[UUID]) -> Dict[UUID, Mantra]:
    return get_mantras_by_ids(db, [mantra_id]) if mantra_id is not None else {}


def convert_accumulator_to_dto(
    accumulator: Accumulator,
    mantras_by_id: Optional[Dict[UUID, Mantra]] = None,
) -> AccumulatorDTO:
    from ..mantra.mantra_service import resolve_deity_image

    accumulator_type = (
        AccumulatorType(accumulator.type.value)
        if hasattr(accumulator.type, 'value')
        else accumulator.type
    )
    mala_image_id, mala_image_url = resolve_mala_image_fields(accumulator)
    mantra = mantras_by_id.get(accumulator.mantra_id) if mantras_by_id and accumulator.mantra_id else None
    return AccumulatorDTO(
        id=accumulator.id,
        user_id=accumulator.user_id,
        group_id=accumulator.group_id,
        parent_id=accumulator.parent_id,
        type=accumulator_type,
        target_count=accumulator.target_count,
        current_count=accumulator.current_count or 0,
        text_id=accumulator.text_id,
        mantra_id=accumulator.mantra_id,
        mala_image_id=mala_image_id,
        mala_image_url=mala_image_url,
        deity_image=resolve_deity_image(mantra),
        metadata=convert_metadata_entries_to_dtos(accumulator),
        created_at=accumulator.created_at,
        updated_at=accumulator.updated_at
    )


def convert_accumulators_to_dtos(
    accumulators: List[Accumulator],
    mantras_by_id: Optional[Dict[UUID, Mantra]] = None,
) -> List[AccumulatorDTO]:
    return [convert_accumulator_to_dto(accumulator, mantras_by_id) for accumulator in accumulators]


def _metadata_language(entry: MantraMetadata) -> str:
    return entry.language.value if hasattr(entry.language, "value") else str(entry.language)


def _pick_mantra_metadata(
    metadata_entries: List[MantraMetadata],
    language: Optional[str],
) -> Optional[MantraMetadata]:
    if not metadata_entries:
        return None
    if language:
        matched = filter_by_language_with_fallback(
            entries=list(metadata_entries),
            language=language,
            language_of=_metadata_language,
        )
        return matched[0] if matched else None
    for entry in metadata_entries:
        if _metadata_language(entry) == "EN":
            return entry
    return metadata_entries[0]


def build_preset_mantra_dto(
    mantra: Mantra,
    language: Optional[str],
    include_key: bool = False,
) -> Optional[PresetMantraDTO]:
    # Deferred import: mantra_service imports generate_mala_image_presigned_url
    # from this module, so importing it back at module load time would be
    # circular. By call time both modules are fully loaded.
    from ..mantra.mantra_service import resolve_deity_image

    metadata = _pick_mantra_metadata(mantra.metadata_entries, language)
    if metadata is None:
        return None
    mala = mantra.mala
    dto_class = CMSPresetMantraDTO if include_key else PresetMantraDTO
    extra_fields = {"deity_image_key": mantra.deity_image} if include_key else {}
    return dto_class(
        id=mantra.id,
        mantra=metadata.mantra,
        title=metadata.title,
        pronunciation=metadata.pronunciation,
        audio_url=mantra.audio_url,
        mala_image_id=mala.id if mala is not None else None,
        mala_image_url=generate_mala_image_presigned_url(mala.url) if mala is not None else None,
        deity_image=resolve_deity_image(mantra),
        **extra_fields,
    )


def convert_accumulator_to_public_dto(
    accumulator: Accumulator,
    mantras_by_id: Optional[Dict[UUID, Mantra]] = None,
    language: Optional[str] = None,
    include_key: bool = False,
) -> PublicAccumulatorDTO:
    accumulator_type = (
        AccumulatorType(accumulator.type.value)
        if hasattr(accumulator.type, 'value')
        else accumulator.type
    )
    mala_image_id, mala_image_url = resolve_mala_image_fields(accumulator)
    mantra_dto = None
    if accumulator.mantra_id and mantras_by_id:
        mantra = mantras_by_id.get(accumulator.mantra_id)
        if mantra is not None:
            mantra_dto = build_preset_mantra_dto(mantra, language, include_key=include_key)
    dto_class = CMSPublicAccumulatorDTO if include_key else PublicAccumulatorDTO
    return dto_class(
        id=accumulator.id,
        group_id=accumulator.group_id,
        type=accumulator_type,
        target_count=accumulator.target_count,
        current_count=accumulator.current_count or 0,
        text_id=accumulator.text_id,
        mantra=mantra_dto,
        mala_image_id=mala_image_id,
        mala_image_url=mala_image_url,
        metadata=convert_metadata_entries_to_dtos(accumulator),
        created_at=accumulator.created_at,
        updated_at=accumulator.updated_at
    )


def validate_mantra_exists(db, mantra_id: UUID) -> None:
    if not mantra_exists(db, mantra_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": NOT_FOUND, "message": MANTRA_NOT_FOUND}
        )


def is_user_created_accumulator(accumulator: Accumulator) -> bool:
    accumulator_type = accumulator.type.value if hasattr(accumulator.type, 'value') else accumulator.type
    return accumulator_type == AccumulatorType.USER.value


def _create_accumulator_from_preset(
    db,
    user_id: UUID,
    preset_id: UUID,
) -> Accumulator:
    """Create a user accumulator by copying fields from a public preset."""
    preset = get_preset_by_id(db, preset_id)
    if preset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": NOT_FOUND, "message": PRESET_NOT_FOUND}
        )

    existing = get_user_accumulator_by_parent(db, user_id, preset.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": CONFLICT, "message": ACCUMULATOR_ALREADY_EXISTS}
        )

    mantra_mala_image_id = (
        get_mantra_mala_image_id(db, preset.mantra_id)
        if preset.mantra_id is not None
        else None
    )

    new_accumulator = Accumulator(
        id=uuid4(),
        user_id=user_id,
        group_id=preset.group_id,
        parent_id=preset.id,
        type=AccumulatorType.USER,
        target_count=preset.target_count,
        current_count=0,
        text_id=preset.text_id,
        mantra_id=preset.mantra_id,
        mala_image=mantra_mala_image_id or preset.mala_image,
    )

    new_accumulator.metadata_entries = [
        AccumulatorMetadata(
            id=uuid4(),
            name=entry.name,
            description=entry.description,
            language=entry.language,
        )
        for entry in preset.metadata_entries
    ]

    add_accumulator(db, new_accumulator)
    return commit_accumulator(db, new_accumulator)


def _build_accumulator_history_dto(
    accumulator: Accumulator,
    total_counted: int,
    sessions: List[AccumulatorHistory],
    mantras_by_id: Optional[Dict[UUID, Mantra]] = None,
) -> AccumulatorHistoryDTO:
    from ..mantra.mantra_service import resolve_deity_image

    mala_image_id, mala_image_url = resolve_mala_image_fields(accumulator)
    mantra = mantras_by_id.get(accumulator.mantra_id) if mantras_by_id and accumulator.mantra_id else None
    return AccumulatorHistoryDTO(
        accumulator_id=accumulator.id,
        parent_id=accumulator.parent_id,
        target_count=accumulator.target_count,
        current_count=accumulator.current_count or 0,
        total_counted=total_counted,
        mala_image_id=mala_image_id,
        mala_image_url=mala_image_url,
        deity_image=resolve_deity_image(mantra),
        metadata=convert_metadata_entries_to_dtos(accumulator),
        sessions=[
            AccumulatorSessionDTO(
                count=session.count,
                created_at=session.created_at
            )
            for session in sessions
        ]
    )


def get_all_accumulators_service(
    skip: int = 0,
    limit: int = 20,
    language: Optional[str] = None,
    search: Optional[str] = None,
    timezone_name: Optional[str] = None,
    show_recitations: bool = False,
) -> PublicAccumulatorsResponse:
    with SessionLocal() as db:
        accumulators, total = get_all_accumulators(
            db,
            skip,
            limit,
            search=search,
            show_recitations=show_recitations,
        )
        visible_accumulators = filter_items_for_timezone(
            accumulators,
            timezone_name=timezone_name,
            item_type=RestrictedItemType.ACCUMULATOR,
            id_of=lambda accumulator: accumulator.id,
        )
        mantra_ids = [a.mantra_id for a in visible_accumulators if a.mantra_id is not None]
        mantras_by_id = get_mantras_by_ids(db, mantra_ids)
        return PublicAccumulatorsResponse(
            accumulators=[
                convert_accumulator_to_public_dto(a, mantras_by_id, language)
                for a in visible_accumulators
            ],
            total=total,
            skip=skip,
            limit=limit
        )


def get_user_accumulators_service(
    user_id: UUID,
    skip: int = 0,
    limit: int = 20
) -> AccumulatorsResponse:
    with SessionLocal() as db:
        accumulators, total = get_user_accumulators(db, user_id, skip, limit)
        mantra_ids = [a.mantra_id for a in accumulators if a.mantra_id is not None]
        mantras_by_id = get_mantras_by_ids(db, mantra_ids)
        return AccumulatorsResponse(
            accumulators=convert_accumulators_to_dtos(accumulators, mantras_by_id),
            total=total,
            skip=skip,
            limit=limit
        )


def create_accumulator_service(token: str, request: CreateAccumulatorRequest) -> AccumulatorDTO:
    """Create the user's accumulator from a tapped preset.

    The preset's fields are copied into a new user accumulator whose parent_id
    links back to the preset. A user has at most one active accumulator per
    preset, so a duplicate create is rejected."""
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        saved_accumulator = _create_accumulator_from_preset(
            db, current_user.id, request.parent_id
        )
        mantras_by_id = _single_mantra_by_id(db, saved_accumulator.mantra_id)
        return convert_accumulator_to_dto(saved_accumulator, mantras_by_id)


async def update_accumulator_service(token: str, accumulator_id: UUID, request: UpdateAccumulatorRequest) -> AccumulatorDTO:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        accumulator = get_accumulator_by_id(db, accumulator_id)

        if not accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": ACCUMULATOR_NOT_FOUND}
            )

        if accumulator.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ACCUMULATOR_UPDATE_NOT_ALLOWED}
            )

        if not is_user_created_accumulator(accumulator):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ONLY_USER_ACCUMULATORS_CAN_BE_UPDATED}
            )

        if request.target_count is not None:
            accumulator.target_count = request.target_count
        if request.text_id is not None:
            accumulator.text_id = request.text_id
        if request.mantra_id is not None:
            validate_mantra_exists(db, request.mantra_id)
            accumulator.mantra_id = request.mantra_id
        if request.current_count is not None:
            delta = request.current_count - (accumulator.current_count or 0)
            accumulator.current_count = request.current_count
            if delta > 0:
                add_history_row(
                    db=db,
                    accumulator_id=accumulator.id,
                    user_id=current_user.id,
                    count=delta
                )
                await invalidate_user_stats_cache(user_id=current_user.id)

        updated_accumulator = update_accumulator(db, accumulator)
        mantras_by_id = _single_mantra_by_id(db, updated_accumulator.mantra_id)
        return convert_accumulator_to_dto(updated_accumulator, mantras_by_id)


def delete_accumulator_service(token: str, accumulator_id: UUID) -> None:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        accumulator = get_accumulator_by_id(db, accumulator_id)

        if not accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": ACCUMULATOR_NOT_FOUND}
            )

        if accumulator.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ACCUMULATOR_DELETE_NOT_ALLOWED}
            )

        if not is_user_created_accumulator(accumulator):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ONLY_USER_ACCUMULATORS_CAN_BE_DELETED}
            )

        delete_accumulator(db, accumulator)


def get_accumulator_detail_service(
    token: str,
    parent_id: UUID
) -> AccumulatorHistoryDTO:
    """Fetch the current user's accumulator created from the given preset
    (parent_id), with its history. Creates one from the preset when the user
    has none yet."""
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        result = get_accumulator_with_history(db, current_user.id, parent_id)

        if result is None:
            accumulator = _create_accumulator_from_preset(
                db, current_user.id, parent_id
            )
            total_counted, sessions = 0, []
        else:
            accumulator, total_counted, sessions = result

        mantras_by_id = (
            get_mantras_by_ids(db, [accumulator.mantra_id])
            if accumulator.mantra_id is not None
            else {}
        )
        return _build_accumulator_history_dto(accumulator, total_counted, sessions, mantras_by_id)


def get_accumulator_history_service(
    token: str,
    skip: int = 0,
    limit: int = 20
) -> AccumulatorHistoryResponse:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        history_data, total = get_user_accumulator_history(db, current_user.id, skip, limit)

        mantra_ids = [
            accumulator.mantra_id
            for accumulator, _, _ in history_data
            if accumulator.mantra_id is not None
        ]
        mantras_by_id = get_mantras_by_ids(db, mantra_ids)

        accumulators = [
            _build_accumulator_history_dto(accumulator, total_counted, sessions, mantras_by_id)
            for accumulator, total_counted, sessions in history_data
        ]

        return AccumulatorHistoryResponse(
            accumulators=accumulators,
            total=total,
            skip=skip,
            limit=limit
        )


def update_mala_image_service(
    token: str,
    accumulator_id: UUID,
    request: UpdateMalaImageRequest
) -> AccumulatorDTO:
    """Set the mala image on an accumulator (one image per accumulator). The
    accumulator must belong to the requesting user and the mala image must
    exist in the catalog."""
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        accumulator = get_accumulator_by_id(db, accumulator_id)
        if not accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": ACCUMULATOR_NOT_FOUND}
            )

        if accumulator.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ACCUMULATOR_UPDATE_NOT_ALLOWED}
            )

        mala = get_mala_image_by_id(db, request.mala_image_id)
        if mala is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": MALA_IMAGE_NOT_FOUND}
            )

        accumulator.mala_image = mala.id
        updated_accumulator = update_accumulator(db, accumulator)
        mantras_by_id = _single_mantra_by_id(db, updated_accumulator.mantra_id)
        return convert_accumulator_to_dto(updated_accumulator, mantras_by_id)


def get_accumulator_groups_service(
    token: str,
    accumulator_id: UUID,
    skip: int = 0,
    limit: int = 20,
    joined_only: bool = False,
) -> AccumulatorGroupsResponse:
    """Get groups using a specific accumulator with the authenticated user's total count for each."""
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        # Verify accumulator exists
        accumulator = get_accumulator_by_id(db, accumulator_id)
        if not accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": ACCUMULATOR_NOT_FOUND}
            )
        
        groups_with_counts, total = get_groups_by_accumulator_id(
            db=db,
            accumulator_id=accumulator_id,
            user_id=current_user.id,
            skip=skip,
            limit=limit,
            joined_only=joined_only,
        )
        
        return AccumulatorGroupsResponse(
            groups=[
                AccumulatorGroupDTO(
                    group_accumulator_id=item.group_accumulator.id,
                    group_id=item.group_accumulator.group_id,
                    title=item.group_accumulator.title,
                    image=get_image_url(item.group_accumulator.image_key),
                    target_count=item.group_accumulator.target_count,
                    user_total_count=item.user_total_count,
                    is_joined=item.is_joined,
                    start_date=item.group_accumulator.start_date,
                    end_date=item.group_accumulator.end_date,
                    created_at=item.group_accumulator.created_at
                )
                for item in groups_with_counts
            ],
            total=total,
            skip=skip,
            limit=limit
        )
