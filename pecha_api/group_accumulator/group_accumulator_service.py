from typing import List, Optional, Tuple, Union
from uuid import UUID, uuid4
from fastapi import HTTPException
from starlette import status

from pecha_api.accumulator.group_accumulator_models import GroupAccumulator
from pecha_api.accumulator.group_accumulator_metadata_model import GroupAccumulatorMetadata
from pecha_api.accumulator.group_accumulator_link_model import GroupAccumulatorLink
from pecha_api.accumulator.link_utils import classify_link, is_valid_http_url
from pecha_api.accumulator.response_message import INVALID_URL
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.plans.shared.metadata_utils import (
    DEFAULT_FALLBACK_LANGUAGE,
    filter_by_language_with_fallback,
)
from pecha_api.db.database import SessionLocal
from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.timezone_utils import get_day_bounds_in_timezone, normalize_timezone_name
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.shared.permissions import (
    require_can_create_content,
    require_can_read_group_content,
    require_can_change_status,
)
from pecha_api.config import get
from pecha_api.plans.authors.plan_authors_service import get_image_url
from pecha_api.plans.groups.groups_enums import AuthorGroupType
from pecha_api.plans.groups.groups_repository import (
    get_group_by_id,
    is_group_published,
    is_user_joined_group,
    upsert_group_join,
)
from pecha_api.plans.groups.group_ban_guard import assert_user_not_banned_from_group
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.users.users_models import Users
from pecha_api.region_restrictions.region_restriction_enums import RestrictedItemType
from pecha_api.region_restrictions.region_restriction_service import (
    assert_visible_for_timezone,
    filter_items_for_timezone,
)
from .group_accumulator_repository import (
    create_group_accumulator,
    get_group_accumulators,
    get_group_accumulator_by_id,
    update_group_accumulator,
    delete_group_accumulator,
    add_group_history_row,
    get_group_accumulator_history,
    get_group_accumulator_total_count,
    get_group_accumulator_count_in_range,
    get_user_group_accumulator_count,
    verify_group_exists,
    upsert_group_accumulator_join,
    is_user_joined_group_accumulator,
    get_joined_group_accumulator_ids_by_user,
    get_group_accumulator_joiners_count,
    get_group_accumulator_joiners_counts,
    list_group_accumulator_joiners_paginated,
    get_active_user_group_accumulator,
    get_or_create_active_user_group_accumulator,
    soft_delete_user_group_accumulator,
    get_user_group_accumulator_sessions,
)
from .group_accumulator_response_models import (
    CreateGroupAccumulatorRequest,
    UpdateGroupAccumulatorRequest,
    GroupAccumulatorDTO,
    GroupAccumulatorsResponse,
    SubmitGroupCountRequest,
    GroupAccumulatorDetailDTO,
    GroupAccumulatorDetailUserDTO,
    GroupAccumulatorHistoryResponse,
    GroupAccumulatorHistoryItemDTO,
    GroupAccumulatorMemberDTO,
    GroupAccumulatorMembersResponse,
    GroupAccumulatorContributionDTO,
    GroupAccumulatorUserSessionDTO,
    GroupAccumulatorUserSessionsResponse,
    GroupAccumulatorMemberSortBy,
    GroupAccumulatorMetadataDTO,
    GroupAccumulatorLinkDTO,
    GroupAccumulatorLinkRequest,
)


def _to_group_type(value) -> AuthorGroupType:
    if hasattr(value, "value"):
        return AuthorGroupType(value.value)
    return AuthorGroupType(value)


def _assert_group_allows_join(group) -> None:
    if _to_group_type(group.group_type) != AuthorGroupType.COMMUNITY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "This group does not support joining"},
        )


def _user_fullname(user: Users) -> str:
    parts = [user.firstname, user.lastname]
    return " ".join(part for part in parts if part).strip()


def _user_avatar_url(user: Users) -> str | None:
    if not user.avatar_url:
        return None
    return generate_presigned_access_url(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=user.avatar_url,
    )


def _build_detail_user_dto(
    user: Users,
    *,
    total_count: int,
    today_count: int,
) -> GroupAccumulatorDetailUserDTO:
    return GroupAccumulatorDetailUserDTO(
        total_count=total_count,
        today_count=today_count,
        username=user.username,
        image=_user_avatar_url(user),
        fullname=_user_fullname(user),
    )


def _language_code(language: Union[LanguageCode, str]) -> str:
    return language.value if hasattr(language, "value") else str(language)


def _metadata_language(entry: GroupAccumulatorMetadata) -> str:
    return _language_code(entry.language)


def _resolve_metadata_value(
    group_accumulator: GroupAccumulator,
    language: Optional[str],
    attribute: str,
) -> Optional[str]:
    """The requested language, else EN, else whatever language is stored.

    Entries with nothing in ``attribute`` are skipped first, so a title-only
    translation never hides the English description (or the other way round)."""
    entries = [
        entry
        for entry in (getattr(group_accumulator, "metadata_entries", None) or [])
        if getattr(entry, attribute, None)
    ]
    if not entries:
        return None

    if language:
        matched = filter_by_language_with_fallback(
            entries=entries,
            language=language,
            language_of=_metadata_language,
        )
        if matched:
            return getattr(matched[0], attribute)

    fallback = DEFAULT_FALLBACK_LANGUAGE.upper()
    for entry in entries:
        if _metadata_language(entry).upper() == fallback:
            return getattr(entry, attribute)
    return getattr(entries[0], attribute)


def _resolve_description(
    group_accumulator: GroupAccumulator, language: Optional[str]
) -> Optional[str]:
    return _resolve_metadata_value(group_accumulator, language, "description")


def _resolve_title(
    group_accumulator: GroupAccumulator, language: Optional[str]
) -> Optional[str]:
    """Per-language title, falling back to the default stored on the parent row
    for accumulators created before titles were translated."""
    resolved = _resolve_metadata_value(group_accumulator, language, "title")
    return resolved if resolved else group_accumulator.title


def _default_metadata_title(
    metadata: Optional[List[GroupAccumulatorMetadataDTO]],
) -> Optional[str]:
    """The title to keep on ``group_accumulators.title``: EN when it is being
    written, else the first entry carrying a title. Search, list views and the
    modules reading that column all stay on this single value."""
    titled = [entry for entry in (metadata or []) if (entry.title or "").strip()]
    if not titled:
        return None
    for entry in titled:
        if _language_code(entry.language).upper() == DEFAULT_FALLBACK_LANGUAGE.upper():
            return entry.title
    return titled[0].title


def _convert_metadata_entries(
    group_accumulator: GroupAccumulator,
) -> List[GroupAccumulatorMetadataDTO]:
    return [
        GroupAccumulatorMetadataDTO(
            language=entry.language,
            title=entry.title,
            description=entry.description,
        )
        for entry in (getattr(group_accumulator, "metadata_entries", None) or [])
    ]


def _convert_links(group_accumulator) -> List[GroupAccumulatorLinkDTO]:
    links = list(getattr(group_accumulator, "links", None) or [])
    links.sort(key=lambda link: link.display_order)
    return [
        GroupAccumulatorLinkDTO(
            id=link.id,
            url=link.url,
            link_type=link.link_type,
            video_id=link.video_id,
            title=link.title,
            display_order=link.display_order,
        )
        for link in links
    ]


def _build_metadata_entries(
    metadata: List[GroupAccumulatorMetadataDTO],
) -> List[GroupAccumulatorMetadata]:
    return [
        GroupAccumulatorMetadata(
            id=uuid4(),
            title=entry.title,
            description=entry.description,
            language=entry.language,
        )
        for entry in metadata
    ]


def _build_link_entries(
    links: List[GroupAccumulatorLinkRequest],
    *,
    created_by: Optional[str] = None,
) -> List[GroupAccumulatorLink]:
    entries = []
    for display_order, entry in enumerate(links):
        url = entry.url.strip()
        if not is_valid_http_url(url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "BAD_REQUEST", "message": INVALID_URL},
            )
        link_type, video_id = classify_link(url)
        entries.append(
            GroupAccumulatorLink(
                id=uuid4(),
                url=url,
                link_type=link_type,
                video_id=video_id,
                title=entry.title,
                display_order=display_order,
                created_by=created_by,
                updated_by=created_by,
            )
        )
    return entries


def _apply_update_request(
    db,
    group_accumulator,
    request: UpdateGroupAccumulatorRequest,
    *,
    created_by: Optional[str] = None,
) -> None:
    """Apply the editable fields of an update request. Unset fields are left
    untouched."""
    for field in (
        "accumulator_id",
        "title",
        "image_key",
        "target_count",
        "start_date",
        "end_date",
    ):
        value = getattr(request, field)
        if value is not None:
            setattr(group_accumulator, field, value)

    # An explicit `title` wins; otherwise the default title follows the
    # translations being written.
    if request.title is None:
        default_title = _default_metadata_title(request.metadata)
        if default_title is not None:
            group_accumulator.title = default_title

    _apply_metadata_and_links(
        db,
        group_accumulator,
        metadata=request.metadata,
        links=request.links,
        created_by=created_by,
    )


def _validate_link_requests(links: Optional[List[GroupAccumulatorLinkRequest]]) -> None:
    """Raise before any row is written when a URL is unusable."""
    if links is not None:
        _build_link_entries(links)


def _create_with_children(
    db,
    group_id: UUID,
    request: CreateGroupAccumulatorRequest,
    *,
    created_by: Optional[str] = None,
):
    """Create the accumulator and its metadata/links. Links are validated up
    front so a bad URL cannot leave a committed parent behind."""
    if not verify_group_exists(db, group_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group not found"},
        )

    _validate_link_requests(request.links)

    group_accumulator = create_group_accumulator(
        db=db,
        group_id=group_id,
        accumulator_id=request.accumulator_id,
        title=request.title or _default_metadata_title(request.metadata),
        image_key=request.image_key,
        target_count=request.target_count,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    _apply_metadata_and_links(
        db,
        group_accumulator,
        metadata=request.metadata,
        links=request.links,
        created_by=created_by,
    )
    update_group_accumulator(db=db, group_accumulator=group_accumulator)
    return group_accumulator


def _apply_metadata_and_links(
    db,
    group_accumulator,
    *,
    metadata: Optional[List[GroupAccumulatorMetadataDTO]],
    links: Optional[List[GroupAccumulatorLinkRequest]],
    created_by: Optional[str] = None,
) -> None:
    """Full-replace both child sets. None leaves the existing rows untouched;
    an empty list clears them."""
    # Build (and so validate) the replacements before touching existing rows.
    new_metadata = _build_metadata_entries(metadata) if metadata is not None else None
    new_links = (
        _build_link_entries(links, created_by=created_by) if links is not None else None
    )

    if new_metadata is not None:
        group_accumulator.metadata_entries.clear()
    if new_links is not None:
        group_accumulator.links.clear()

    # The metadata unique constraint on (group_accumulator_id, language) is
    # checked per statement, so the deletes must land before the inserts.
    if new_metadata is not None or new_links is not None:
        db.flush()

    if new_metadata is not None:
        group_accumulator.metadata_entries.extend(new_metadata)
    if new_links is not None:
        group_accumulator.links.extend(new_links)


def _convert_to_dto(
    group_accumulator,
    *,
    is_joined: Optional[bool] = None,
    member_count: int = 0,
    language: Optional[str] = None,
    include_cms_fields: bool = False,
) -> GroupAccumulatorDTO:
    preset_accumulator = getattr(group_accumulator, "accumulator", None)
    return GroupAccumulatorDTO(
        id=group_accumulator.id,
        preset_accumulator_id=group_accumulator.accumulator_id,
        text_id=preset_accumulator.text_id if preset_accumulator else None,
        mantra_id=preset_accumulator.mantra_id if preset_accumulator else None,
        group_id=group_accumulator.group_id,
        title=_resolve_title(group_accumulator, language),
        image=get_image_url(group_accumulator.image_key),
        image_key=group_accumulator.image_key,
        target_count=group_accumulator.target_count,
        start_date=group_accumulator.start_date,
        end_date=group_accumulator.end_date,
        description=_resolve_description(group_accumulator, language),
        metadata=_convert_metadata_entries(group_accumulator) if include_cms_fields else None,
        links=_convert_links(group_accumulator),
        is_joined=is_joined,
        member_count=member_count,
        created_at=group_accumulator.created_at,
        updated_at=group_accumulator.updated_at,
    )


def _today_bounds(timezone_name: Optional[str]) -> Tuple:
    normalized = normalize_timezone_name(timezone_name)
    return get_day_bounds_in_timezone(normalized)


def _convert_to_detail_dto(
    group_accumulator,
    *,
    total_count: int,
    total_today_count: int,
    member_count: int,
    user: Optional[GroupAccumulatorDetailUserDTO] = None,
    is_joined: Optional[bool] = None,
    language: Optional[str] = None,
    include_cms_fields: bool = False,
) -> GroupAccumulatorDetailDTO:
    preset_accumulator = getattr(group_accumulator, "accumulator", None)
    links = _convert_links(group_accumulator)
    return GroupAccumulatorDetailDTO(
        id=group_accumulator.id,
        preset_accumulator_id=group_accumulator.accumulator_id,
        text_id=preset_accumulator.text_id if preset_accumulator else None,
        mantra_id=preset_accumulator.mantra_id if preset_accumulator else None,
        group_id=group_accumulator.group_id,
        title=_resolve_title(group_accumulator, language),
        image=get_image_url(group_accumulator.image_key),
        image_key=group_accumulator.image_key,
        target_count=group_accumulator.target_count,
        start_date=group_accumulator.start_date,
        end_date=group_accumulator.end_date,
        description=_resolve_description(group_accumulator, language),
        metadata=_convert_metadata_entries(group_accumulator) if include_cms_fields else None,
        links=links,
        total_count=total_count,
        total_today_count=total_today_count,
        user=user,
        is_joined=is_joined,
        member_count=member_count,
        created_at=group_accumulator.created_at,
        updated_at=group_accumulator.updated_at,
    )


def create_group_accumulator_service(
    group_id: UUID,
    request: CreateGroupAccumulatorRequest,
) -> GroupAccumulatorDTO:
    with SessionLocal() as db:
        group_accumulator = _create_with_children(db, group_id, request)
        return _convert_to_dto(group_accumulator, include_cms_fields=True)


def get_group_accumulators_service(
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    token: Optional[str] = None,
    timezone_name: Optional[str] = None,
    language: Optional[str] = None,
) -> GroupAccumulatorsResponse:
    with SessionLocal() as db:
        accumulators, total = get_group_accumulators(
            db, group_id, skip, limit, exclude_event_linked=True
        )
        accumulators = filter_items_for_timezone(
            accumulators,
            timezone_name=timezone_name,
            item_type=RestrictedItemType.GROUP_ACCUMULATOR,
            id_of=lambda accumulator: accumulator.id,
        )

        joined_ids: set[UUID] = set()
        if token:
            current_user = validate_and_extract_user_details(token=token)
            joined_ids = set(
                get_joined_group_accumulator_ids_by_user(
                    db=db,
                    user_id=current_user.id,
                    group_accumulator_ids=[acc.id for acc in accumulators],
                )
            )

        member_counts = get_group_accumulator_joiners_counts(
            db=db,
            group_accumulator_ids=[acc.id for acc in accumulators],
        )

        return GroupAccumulatorsResponse(
            accumulators=[
                _convert_to_dto(
                    acc,
                    is_joined=acc.id in joined_ids if token else None,
                    member_count=member_counts.get(acc.id, 0),
                    language=language,
                )
                for acc in accumulators
            ],
            total=total,
            skip=skip,
            limit=limit,
        )


def get_group_accumulator_service(
    group_accumulator_id: UUID,
    timezone_name: Optional[str] = None,
    token: Optional[str] = None,
    language: Optional[str] = None,
) -> GroupAccumulatorDetailDTO:
    assert_visible_for_timezone(
        timezone_name=timezone_name,
        item_type=RestrictedItemType.GROUP_ACCUMULATOR,
        item_id=group_accumulator_id,
        not_found_detail="Group accumulator not found",
    )
    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )
        
        total_count = get_group_accumulator_total_count(db, group_accumulator_id)
        member_count = get_group_accumulator_joiners_count(db, group_accumulator_id)
        day_start, day_end = _today_bounds(timezone_name)
        total_today_count = get_group_accumulator_count_in_range(
            db=db,
            group_accumulator_id=group_accumulator_id,
            range_start=day_start,
            range_end=day_end,
        )

        user = None
        is_joined = None
        if token:
            current_user = validate_and_extract_user_details(token=token)
            is_joined = is_user_joined_group_accumulator(
                db=db,
                group_accumulator_id=group_accumulator_id,
                user_id=current_user.id,
            )
            user = _build_detail_user_dto(
                current_user,
                total_count=get_user_group_accumulator_count(
                    db=db,
                    group_accumulator_id=group_accumulator_id,
                    user_id=current_user.id,
                ),
                today_count=get_group_accumulator_count_in_range(
                    db=db,
                    group_accumulator_id=group_accumulator_id,
                    range_start=day_start,
                    range_end=day_end,
                    user_id=current_user.id,
                    active_session_only=True,
                ),
            )

        return _convert_to_detail_dto(
            group_accumulator,
            total_count=total_count,
            total_today_count=total_today_count,
            member_count=member_count,
            user=user,
            is_joined=is_joined,
            language=language,
        )


def update_group_accumulator_service(
    group_id: UUID,
    group_accumulator_id: UUID,
    request: UpdateGroupAccumulatorRequest,
) -> GroupAccumulatorDTO:
    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )
        
        if group_accumulator.group_id != group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "Group accumulator does not belong to this group"}
            )
        
        _apply_update_request(db, group_accumulator, request)

        updated = update_group_accumulator(db, group_accumulator)
        return _convert_to_dto(updated, include_cms_fields=True)


def delete_group_accumulator_service(
    group_id: UUID,
    group_accumulator_id: UUID,
) -> None:
    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )
        
        if group_accumulator.group_id != group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "Group accumulator does not belong to this group"}
            )
        
        delete_group_accumulator(db, group_accumulator)


def join_group_accumulator_service(
    token: str,
    group_accumulator_id: UUID,
) -> None:
    """Join a group accumulator and automatically join the parent group."""
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"},
            )

        group = get_group_by_id(db=db, group_id=group_accumulator.group_id)
        if not group or not is_group_published(group):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group not found"},
            )

        _assert_group_allows_join(group)
        # Joining an accumulator also joins the parent group, so a user banned
        # from that group must not be able to slip back in through here.
        assert_user_not_banned_from_group(db=db, group_id=group.id, user_id=current_user.id)
        # Joining an accumulator also joins the parent group, so a private
        # parent has to go through the join-request flow first.
        if not group.is_public and not is_user_joined_group(
            db=db, group_id=group.id, user_id=current_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "GROUP_IS_PRIVATE",
                    "message": "This group is private; submit a join request",
                },
            )
        upsert_group_join(db=db, group_id=group_accumulator.group_id, user_id=current_user.id)
        upsert_group_accumulator_join(
            db=db,
            group_accumulator_id=group_accumulator_id,
            user_id=current_user.id,
        )
        get_or_create_active_user_group_accumulator(
            db=db,
            group_accumulator_id=group_accumulator_id,
            user_id=current_user.id,
        )


def get_group_accumulator_members_service(
    group_accumulator_id: UUID,
    skip: int = 0,
    limit: int = 20,
    timezone_name: Optional[str] = None,
    sort_by: GroupAccumulatorMemberSortBy = GroupAccumulatorMemberSortBy.TOTAL,
) -> GroupAccumulatorMembersResponse:
    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"},
            )

        tz = normalize_timezone_name(timezone_name)
        range_start, range_end = get_day_bounds_in_timezone(tz)

        rows, total = list_group_accumulator_joiners_paginated(
            db=db,
            group_accumulator_id=group_accumulator_id,
            skip=skip,
            limit=limit,
            range_start=range_start,
            range_end=range_end,
            sort_by=sort_by.value,
        )

        return GroupAccumulatorMembersResponse(
            members=[
                GroupAccumulatorMemberDTO(
                    user_id=user.id,
                    username=user.username,
                    fullname=_user_fullname(user),
                    avatar_url=_user_avatar_url(user),
                    joined_at=joined_at,
                    total_count=total_count,
                    today_count=today_count,
                )
                for user, joined_at, total_count, today_count in rows
            ],
            member_count=total,
            total=total,
            skip=skip,
            limit=limit,
        )


def delete_group_accumulator_user_service(
    token: str,
    group_accumulator_id: UUID,
) -> None:
    """Reset the user's active participation in a group accumulator.

    Soft-deletes the user's current session so their progress resets to zero,
    then starts a new active session so they remain joined and can count again.
    The group accumulator, join row, and all historical contribution rows are preserved.
    """
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )
        
        if not is_user_joined_group(db=db, group_id=group_accumulator.group_id, user_id=current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "You must be a member of this group"}
            )

        active_session = get_active_user_group_accumulator(
            db=db,
            group_accumulator_id=group_accumulator_id,
            user_id=current_user.id,
        )
        if not active_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "NOT_FOUND",
                    "message": "No active group accumulation to reset",
                },
            )

        soft_delete_user_group_accumulator(db, active_session)
        get_or_create_active_user_group_accumulator(
            db=db,
            group_accumulator_id=group_accumulator_id,
            user_id=current_user.id,
        )


def submit_group_count_service(
    token: str,
    group_accumulator_id: UUID,
    request: SubmitGroupCountRequest,
) -> tuple[GroupAccumulatorHistoryItemDTO, bool]:
    """
    Submit a count contribution to a group accumulator.
    
    Returns:
        tuple: (history_item_dto, is_created) where is_created indicates if a new history entry was created
    """
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )
        
        # Verify user has an active participation session
        active_session = get_active_user_group_accumulator(
            db=db,
            group_accumulator_id=group_accumulator_id,
            user_id=current_user.id,
        )
        if not active_session:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "You must join this group accumulator first"},
            )
        
        # Get user's current total for the active session
        user_current_count = get_user_group_accumulator_count(
            db=db,
            group_accumulator_id=group_accumulator_id,
            user_id=current_user.id,
            active_session_only=True,
        )
        
        # Calculate delta
        delta = request.current_count - user_current_count
        
        # Only record history if delta is positive
        if delta > 0:
            history = add_group_history_row(
                db=db,
                group_accumulator_id=group_accumulator_id,
                user_id=current_user.id,
                count=delta,
                user_group_accumulator_id=active_session.id,
            )
            
            return (
                GroupAccumulatorHistoryItemDTO(
                    id=history.id,
                    user_id=history.user_id,
                    count=history.count,
                    created_at=history.created_at,
                ),
                True,  # is_created
            )
        
        # Return a response with zero count if no change or decrease
        # id is None to indicate no history entry was created
        return (
            GroupAccumulatorHistoryItemDTO(
                id=None,
                user_id=current_user.id,
                count=0,
                created_at=group_accumulator.created_at,
            ),
            False,  # is_created
        )


def get_group_accumulator_history_service(
    group_accumulator_id: UUID,
    skip: int = 0,
    limit: int = 20,
    today_only: bool = False,
    timezone_name: Optional[str] = None,
) -> GroupAccumulatorHistoryResponse:
    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )

        day_start, day_end = _today_bounds(timezone_name)
        range_start = day_start if today_only else None
        range_end = day_end if today_only else None

        history, total = get_group_accumulator_history(
            db,
            group_accumulator_id,
            skip,
            limit,
            range_start=range_start,
            range_end=range_end,
        )
        total_count = get_group_accumulator_total_count(db, group_accumulator_id)
        total_today_count = get_group_accumulator_count_in_range(
            db=db,
            group_accumulator_id=group_accumulator_id,
            range_start=day_start,
            range_end=day_end,
        )
        member_count = get_group_accumulator_joiners_count(db, group_accumulator_id)

        return GroupAccumulatorHistoryResponse(
            group_accumulator=_convert_to_detail_dto(
                group_accumulator,
                total_count=total_count,
                total_today_count=total_today_count,
                member_count=member_count,
            ),
            history=[
                GroupAccumulatorHistoryItemDTO(
                    id=h.id,
                    user_id=h.user_id,
                    count=h.count,
                    created_at=h.created_at,
                )
                for h in history
            ],
            total=total,
            skip=skip,
            limit=limit,
        )


def get_group_accumulator_user_sessions_service(
    token: str,
    group_accumulator_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> GroupAccumulatorUserSessionsResponse:
    """List the authenticated user's participation sessions for a group accumulator."""
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"},
            )

        if not is_user_joined_group(
            db=db,
            group_id=group_accumulator.group_id,
            user_id=current_user.id,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "You must be a member of this group"},
            )

        session_rows, total = get_user_group_accumulator_sessions(
            db=db,
            group_accumulator_id=group_accumulator_id,
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )

        return GroupAccumulatorUserSessionsResponse(
            group_accumulator=_convert_to_dto(group_accumulator),
            sessions=[
                GroupAccumulatorUserSessionDTO(
                    id=session.id,
                    is_active=session.deleted_at is None,
                    total_counted=total_counted,
                    created_at=session.created_at,
                    deleted_at=session.deleted_at,
                    contributions=[
                        GroupAccumulatorContributionDTO(
                            id=row.id,
                            count=row.count,
                            created_at=row.created_at,
                        )
                        for row in history_rows
                    ],
                )
                for session, total_counted, history_rows in session_rows
            ],
            total=total,
            skip=skip,
            limit=limit,
        )


# =============================================================================
# CMS Service Functions (with authorization)
# =============================================================================

def create_group_accumulator_cms_service(
    token: str,
    group_id: UUID,
    request: CreateGroupAccumulatorRequest,
) -> GroupAccumulatorDTO:
    """Create a group accumulator (CMS - requires author with create permission)."""
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_create_content(db=db, group_id=group_id, author=author)

        group_accumulator = _create_with_children(
            db,
            group_id,
            request,
            created_by=getattr(author, "email", None),
        )
        return _convert_to_dto(group_accumulator, include_cms_fields=True)


def get_group_accumulators_cms_service(
    token: str,
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
) -> GroupAccumulatorsResponse:
    """List group accumulators (CMS - requires author with read permission)."""
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_read_group_content(db=db, group_id=group_id, author=author)
        accumulators, total = get_group_accumulators(db, group_id, skip, limit, search=search)
        member_counts = get_group_accumulator_joiners_counts(
            db=db,
            group_accumulator_ids=[acc.id for acc in accumulators],
        )
        return GroupAccumulatorsResponse(
            accumulators=[
                _convert_to_dto(
                    acc,
                    member_count=member_counts.get(acc.id, 0),
                    include_cms_fields=True,
                )
                for acc in accumulators
            ],
            total=total,
            skip=skip,
            limit=limit,
        )


def get_group_accumulator_cms_service(
    token: str,
    group_id: UUID,
    group_accumulator_id: UUID,
) -> GroupAccumulatorDetailDTO:
    """Get a single group accumulator (CMS - requires author with read permission)."""
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_read_group_content(db=db, group_id=group_id, author=author)
        
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )
        
        if group_accumulator.group_id != group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "Group accumulator does not belong to this group"}
            )
        
        total_count = get_group_accumulator_total_count(db, group_accumulator_id)
        member_count = get_group_accumulator_joiners_count(db, group_accumulator_id)
        day_start, day_end = _today_bounds(timezone_name=None)
        total_today_count = get_group_accumulator_count_in_range(
            db=db,
            group_accumulator_id=group_accumulator_id,
            range_start=day_start,
            range_end=day_end,
        )

        return _convert_to_detail_dto(
            group_accumulator,
            total_count=total_count,
            total_today_count=total_today_count,
            member_count=member_count,
            include_cms_fields=True,
        )


def update_group_accumulator_cms_service(
    token: str,
    group_id: UUID,
    group_accumulator_id: UUID,
    request: UpdateGroupAccumulatorRequest,
) -> GroupAccumulatorDTO:
    """Update a group accumulator (CMS - requires author with status change permission)."""
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_change_status(db=db, group_id=group_id, author=author)
        
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )
        
        if group_accumulator.group_id != group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "Group accumulator does not belong to this group"}
            )
        
        _apply_update_request(
            db,
            group_accumulator,
            request,
            created_by=getattr(author, "email", None),
        )

        updated = update_group_accumulator(db, group_accumulator)
        return _convert_to_dto(updated, include_cms_fields=True)


def delete_group_accumulator_cms_service(
    token: str,
    group_id: UUID,
    group_accumulator_id: UUID,
) -> None:
    """Delete a group accumulator (CMS - requires author with status change permission)."""
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_can_change_status(db=db, group_id=group_id, author=author)
        
        group_accumulator = get_group_accumulator_by_id(db, group_accumulator_id)
        if not group_accumulator:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
            )
        
        if group_accumulator.group_id != group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "FORBIDDEN", "message": "Group accumulator does not belong to this group"}
            )
        
        delete_group_accumulator(db, group_accumulator)
