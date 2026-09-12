import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.config import get, get_int
from pecha_api.db.database import SessionLocal
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.plans.authors.plan_authors_repository import find_author_by_email, find_author_by_id
from pecha_api.auth.auth_repository import validate_token
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details, validate_cms_author_details
from pecha_api.plans.shared.permissions import (
    _STATUS_CHANGE_ROLES,
    get_member_role,
    is_reviewer,
    is_super_admin,
    require_cms_write_access,
)
from pecha_api.notification.notification_repository import (
    mark_notifications_read_by_reference,
    notification_exists_for_reference,
)
from pecha_api.notification.notification_service import create_notification_record
from pecha_api.plans.groups.group_invite_email import send_group_invitation_email
from pecha_api.plans.groups.join_request_dispatch_service import (
    enqueue_join_request_created,
    enqueue_join_request_decided,
)
from pecha_api.plans.groups.groups_enums import (
    AuthorGroupInviteStatus,
    AuthorGroupJoinRequestStatus,
    AuthorGroupMemberRole,
    AuthorGroupStatus,
    AuthorGroupType,
)
from pecha_api.plans.groups.groups_models import (
    AuthorGroup,
    AuthorGroupInvite,
    AuthorGroupJoinRequest,
    AuthorGroupMember,
    AuthorGroupMetadata,
    AuthorGroupSocialLink,
)
from pecha_api.plans.plans_enums import PlanStatus
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.cms.cms_plans_repository import get_plans_with_aggregates_by_ids
from pecha_api.plans.plans_response_models import AuthorDTO, PlanDTO, PlanWithAggregates
from pecha_api.plans.series.series_model import Series
from pecha_api.group_accumulator.group_accumulator_repository import (
    get_group_accumulator_joiners_counts,
    get_group_accumulators_for_group_ids,
    get_joined_group_accumulator_ids_by_user,
    remove_group_accumulator_joins_for_group,
)
from pecha_api.plans.groups.follow_scope import resolve_public_group_scope
from pecha_api.plans.groups.groups_repository import (
    add_group_member,
    create_group,
    create_group_invite,
    create_group_join_request,
    get_followers_count_map,
    get_following_group_ids_by_user,
    get_joined_group_ids_by_user,
    get_joiners_count_map,
    is_user_following_group,
    is_group_published,
    is_user_joined_group,
    lock_group_status,
    lock_group_visibility,
    get_group_by_id,
    get_group_by_slug,
    get_groups_by_ids,
    get_group_member,
    get_groups_paginated,
    get_member_roles_map,
    get_invite_by_id,
    get_join_request_by_id,
    get_join_request_status_map,
    get_owner_count,
    get_plans_by_group_id,
    get_plans_by_ids,
    get_series_by_group_id,
    get_series_for_group_ids,
    get_standalone_plans_for_group_ids,
    get_series_partner_id_map_for_group,
    get_user_series_enrollment_partner_map,
    has_pending_invite,
    has_pending_join_request,
    leave_group_membership,
    list_invites_by_group,
    list_group_joiners_paginated,
    list_group_member_ids_by_roles,
    list_join_requests_by_group,
    list_pending_invites_by_email,
    list_pending_join_requests_by_group,
    get_series_by_ids,
    get_tags_by_ids,
    save_invite,
    save_join_request,
    remove_group_follow,
    remove_group_member,
    replace_group_metadata,
    replace_group_relation_ids,
    replace_group_social_links,
    revoke_invite,
    set_group_member_role,
    update_group,
    upsert_group_follow,
    upsert_group_join,
)
from pecha_api.mantra.mantra_count_repository import get_group_mantra_accumulations
from pecha_api.mantra.mantra_repository import get_mantras_by_ids
from pecha_api.group_accumulator.group_accumulator_repository import (
    get_group_accumulator_by_id,
    get_group_accumulator_member_contributions,
)
from pecha_api.plans.series.series_repository import (
    get_active_plan_count_map_by_series_ids,
    get_enrolled_count_map_by_group_and_series_ids,
    get_series_plan_schedule_by_series_ids,
)
from pecha_api.plans.series.series_service import (
    _series_schedule_from_plans,
    _series_to_list_item_dto,
    get_series_partner_dtos_by_series_ids,
)
from pecha_api.plans.shared.metadata_utils import (
    format_metadata_response,
    filter_by_language_with_fallback,
)
from pecha_api.plans.groups.groups_response_models import (
    AuthorGroupDetailDTO,
    GroupSeriesListItemDTO,
    AuthorGroupListResponse,
    AuthorGroupMemberDTO,
    AuthorGroupMemberProfileDTO,
    AuthorGroupMembersListResponse,
    AuthorGroupSummaryDTO,
    CreateAuthorGroupRequest,
    CreateGroupInviteRequest,
    CreateGroupJoinRequest,
    GroupAccumulationsResponse,
    GroupInviteCreatedResponse,
    GroupInviteDTO,
    GroupInviteListResponse,
    GroupJoinRequestDTO,
    GroupJoinRequestListResponse,
    GroupJoinRequestUserDTO,
    GroupMantraAccumulationDTO,
    GroupMemberAccumulationDTO,
    GroupMemberAccumulationsResponse,
    GroupMetadataDTO,
    GroupPracticeCardDTO,
    GroupPracticeFeedItemDTO,
    GroupPracticesFeedResponse,
    GroupPracticesResponse,
    GroupPracticeType,
    GroupSocialLinkDTO,
    PublicAuthorGroupDetailDTO,
    PublicAuthorGroupListResponse,
    PublicAuthorGroupSummaryDTO,
    UserFollowedAuthorGroupDTO,
    UserFollowedAuthorGroupListResponse,
    UserJoinedAuthorGroupDTO,
    UserJoinedAuthorGroupListResponse,
    ReplaceGroupPlansRequest,
    ReplaceGroupSeriesRequest,
    ReplaceGroupSocialLinksRequest,
    ReplaceGroupTagsRequest,
    UpdateAuthorGroupRequest,
    UpdateAuthorGroupStatusRequest,
    UpdateGroupMemberRoleRequest,
    GroupPermissionDTO,
)
from pecha_api.group_accumulator.group_accumulator_service import (
    _convert_to_dto as _group_accumulator_to_dto,
    get_group_accumulators_service,
)
from pecha_api.group_recitation_collection.service import list_group_collections_service
from pecha_api.group_recitation_collection.repository import (
    get_collections_for_group_ids_with_total,
    get_collection_item_counts,
)
from pecha_api.group_recitation_collection.response_models import GroupRecitationCollectionDTO
from pecha_api.plans.groups.groups_models import author_group_tags
from pecha_api.plans.tags.tag_helpers import tags_to_summary_dtos
from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.users.users_repository import get_users_by_ids, get_user_by_id
from pecha_api.users.users_models import Users
from pecha_api.region_restrictions.china_timezone import is_china_timezone
from pecha_api.region_restrictions.region_restriction_enums import RestrictedItemType
from pecha_api.region_restrictions.region_restriction_service import (
    filter_items_for_timezone,
    get_restricted_item_ids,
)

GROUP_NOT_FOUND = "Group not found"
INVITE_NOT_FOUND = "Invite not found"
OWNER_ROLE_NOT_ASSIGNABLE = (
    "The OWNER role cannot be assigned via invite or role change; use transfer ownership"
)
GROUP_ALREADY_HAS_OWNER = "This group already has an owner"
JOIN_REQUEST_NOT_FOUND = "Join request not found"
GROUP_IS_PRIVATE_USE_REQUEST = "This group is private; submit a join request"
NOTIFICATION_CATEGORY_GROUP_INVITE = "group_invite"
NOTIFICATION_CATEGORY_GROUP_JOIN_REQUEST = "group_join_request"
_PRACTICES_FETCH_LIMIT = 1000


def _to_role_value(role: AuthorGroupMemberRole | str) -> str:
    if hasattr(role, "value"):
        return role.value
    return str(role)


def _to_group_type(value) -> AuthorGroupType:
    if hasattr(value, "value"):
        return AuthorGroupType(value.value)
    return AuthorGroupType(value)


def _to_group_status(value) -> AuthorGroupStatus:
    if hasattr(value, "value"):
        return AuthorGroupStatus(value.value)
    return AuthorGroupStatus(value)


_GROUP_TYPE_ENGAGEMENT = {
    AuthorGroupType.PAGE: "follow",
    AuthorGroupType.COMMUNITY: "join",
}


def _assert_group_allows_engagement(group: AuthorGroup, action: Literal["follow", "join"]) -> None:
    expected = _GROUP_TYPE_ENGAGEMENT[_to_group_type(group.group_type)]
    if expected != action:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This group does not support that action",
        )


def _generate_group_asset_url(asset_key: Optional[str]) -> Optional[str]:
    if not asset_key:
        return None
    return generate_presigned_access_url(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=asset_key,
    )


def _user_fullname(user: Users) -> str:
    parts = [user.firstname, user.lastname]
    return " ".join(part for part in parts if part).strip()


def _user_avatar_url(user: Users) -> Optional[str]:
    if not user.avatar_url:
        return None
    return generate_presigned_access_url(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=user.avatar_url,
    )


def _optional_metadata_str(value) -> Optional[str]:
    return value if isinstance(value, str) else None


def _metadata_to_dtos(metadata_entries, language: Optional[str] = None) -> List[GroupMetadataDTO]:
    metadata_entries = filter_by_language_with_fallback(
        entries=list(metadata_entries or []),
        language=language,
        language_of=lambda item: _language_value(item.language),
    )
    return [
        GroupMetadataDTO(
            id=item.id,
            title=item.title,
            sub_title=_optional_metadata_str(getattr(item, "sub_title", None)),
            description=item.description,
            description_long=_optional_metadata_str(getattr(item, "description_long", None)),
            language=_language_value(item.language),
        )
        for item in sorted(
            metadata_entries,
            key=lambda value: (
                0
                if language
                and _language_value(value.language).upper() == language.upper()
                else 1,
                value.language,
            ),
        )
    ]


def _metadata_response(metadata_entries, language: Optional[str] = None):
    return format_metadata_response(
        _metadata_to_dtos(metadata_entries, language=language),
        language=language,
    )


def _members_to_dtos(members) -> List[AuthorGroupMemberDTO]:
    return [
        AuthorGroupMemberDTO(
            author_id=member.author_id,
            role=AuthorGroupMemberRole(_to_role_value(member.role)),
            firstname=member.author.first_name,
            lastname=member.author.last_name,
            email=member.author.email,
        )
        for member in members
    ]


def _social_links_to_dtos(links) -> List[GroupSocialLinkDTO]:
    return [GroupSocialLinkDTO(id=link.id, platform=link.platform, url=link.url) for link in links]


def _tag_name(tag, language: str = 'EN') -> str:
    if not getattr(tag, 'metadata_entries', None):
        return ""
    for meta in tag.metadata_entries:
        lang_value = meta.language.value if hasattr(meta.language, 'value') else str(meta.language)
        if lang_value == language:
            return meta.name
    return tag.metadata_entries[0].name


def _group_tag_names(tags) -> List[str]:
    if not tags:
        return []
    active = [tag for tag in tags if tag.deleted_at is None]
    names = (name for name in (_tag_name(tag) for tag in active) if name)
    return sorted(names, key=str.lower)


def _assert_metadata_valid(metadata_entries: List) -> None:
    if not metadata_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group must have at least one metadata entry",
        )
    seen_languages = set()
    for item in metadata_entries:
        if not item.title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Metadata title is required",
            )
        language = item.language.value if hasattr(item.language, "value") else item.language
        if language in seen_languages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Metadata language must be unique per group",
            )
        seen_languages.add(language)


def _get_member_or_403(db, group_id: UUID, author_id: UUID):
    member = get_group_member(db=db, group_id=group_id, author_id=author_id)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this group",
        )
    return member


def _assert_role_allowed(member: AuthorGroupMember, allowed_roles: List[AuthorGroupMemberRole]):
    role_value = _to_role_value(member.role)
    if role_value not in [_to_role_value(role) for role in allowed_roles]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission for this action",
        )


_GROUP_SETTINGS_ROLES = [AuthorGroupMemberRole.OWNER, AuthorGroupMemberRole.ADMIN]
_MEMBER_MANAGEMENT_ROLES = [AuthorGroupMemberRole.OWNER, AuthorGroupMemberRole.ADMIN]
_ADMIN_INVITE_ROLE = AuthorGroupMemberRole.ADMIN.value


def _resolve_actor_group_role(
    db,
    *,
    group_id: UUID,
    author,
) -> str:
    if is_super_admin(author):
        return AuthorGroupMemberRole.OWNER.value
    member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
    return _to_role_value(member.role)


def _assert_invite_role_allowed(*, actor_role: str, invite_role: str) -> None:
    if invite_role == AuthorGroupMemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OWNER_ROLE_NOT_ASSIGNABLE,
        )
    if invite_role == _ADMIN_INVITE_ROLE and actor_role != AuthorGroupMemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner can invite with ADMIN role",
        )


def _assert_role_not_owner_assignment(requested_role: str) -> None:
    if requested_role == AuthorGroupMemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OWNER_ROLE_NOT_ASSIGNABLE,
        )


def _assert_can_revoke_invite(*, actor_role: str, invite: AuthorGroupInvite) -> None:
    if _to_role_value(invite.role) == AuthorGroupMemberRole.ADMIN.value and actor_role != AuthorGroupMemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner can revoke an ADMIN invitation",
        )


def _assert_role_change_allowed(
    *,
    actor_role: str,
    actor_author_id: UUID,
    target_author_id: UUID,
    target_role: str,
    requested_role: str,
) -> None:
    _assert_role_not_owner_assignment(requested_role)
    if actor_role == AuthorGroupMemberRole.OWNER.value:
        return
    if target_role == AuthorGroupMemberRole.ADMIN.value and target_author_id != actor_author_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner can change an ADMIN member's role",
        )
    if requested_role == AuthorGroupMemberRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner can assign the ADMIN role",
        )


def _validate_group_links(db, tag_ids: Optional[List[UUID]], series_ids: Optional[List[UUID]], plan_ids: Optional[List[UUID]]) -> None:
    if tag_ids is not None:
        found_tags = get_tags_by_ids(db=db, tag_ids=tag_ids)
        if len(found_tags) != len(set(tag_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more tags do not exist")
    if series_ids is not None:
        found_series = get_series_by_ids(db=db, series_ids=series_ids)
        if len(found_series) != len(set(series_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more series do not exist")
    if plan_ids is not None:
        found_plans = get_plans_by_ids(db=db, plan_ids=plan_ids)
        if len(found_plans) != len(set(plan_ids)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more plans do not exist")


def _is_series_enrolled_for_group_context(
    enrollment_partner_id: Optional[UUID],
    expected_partner_id: Optional[UUID],
    *,
    is_enrolled_in_series: bool,
) -> Optional[bool]:
    if not is_enrolled_in_series:
        return None
    if enrollment_partner_id is None:
        return None
    return enrollment_partner_id == expected_partner_id


def _series_to_dtos(
    db: Session,
    series_list: List[Series],
    group_id: UUID,
    language: Optional[str] = None,
    published_only: bool = False,
    user_id: Optional[UUID] = None,
) -> List[GroupSeriesListItemDTO]:
    if not series_list:
        return []
    series_ids = [series.id for series in series_list]
    plan_count_map = get_active_plan_count_map_by_series_ids(
        db=db, series_ids=series_ids, published_only=published_only
    )
    enrolled_count_map = get_enrolled_count_map_by_group_and_series_ids(
        db=db, group_id=group_id, series_ids=series_ids
    )
    partner_id_map = get_series_partner_id_map_for_group(
        db=db, group_id=group_id, series_ids=series_ids
    )
    enrollment_partner_map: Dict[UUID, Optional[UUID]] = {}
    if user_id is not None:
        enrollment_partner_map = get_user_series_enrollment_partner_map(
            db=db, user_id=user_id, series_ids=series_ids
        )
    plans_by_series_id = get_series_plan_schedule_by_series_ids(
        db=db,
        series_ids=series_ids,
    )
    partner_by_series_id = get_series_partner_dtos_by_series_ids(
        db=db,
        user_id=user_id,
        series_ids=series_ids,
        language=language,
    )
    series_dtos: List[GroupSeriesListItemDTO] = []
    for series in series_list:
        start_date, end_date, total_days = _series_schedule_from_plans(
            plans_by_series_id.get(series.id, []),
            published_only=published_only,
            language=language,
            fallback=True,
        )
        series_dtos.append(
            GroupSeriesListItemDTO(
                **_series_to_list_item_dto(
                    series,
                    plan_count=plan_count_map.get(series.id, 0),
                    enrolled_count=enrolled_count_map.get(series.id, 0),
                    language=language,
                    start_date=start_date,
                    end_date=end_date,
                    total_days=total_days,
                    fallback=True,
                    partner=partner_by_series_id.get(series.id),
                ).model_dump(),
                is_group_enrolled=_is_series_enrolled_for_group_context(
                    enrollment_partner_id=enrollment_partner_map.get(series.id),
                    expected_partner_id=partner_id_map.get(series.id),
                    is_enrolled_in_series=series.id in enrollment_partner_map,
                ),
            )
        )
    return series_dtos


def _language_value(language) -> str:
    if language is None:
        return "EN"
    if hasattr(language, "value"):
        return language.value
    return str(language)


def _plan_aggregate_to_dto(plan_info: PlanWithAggregates, group_id: UUID) -> PlanDTO:
    plan = plan_info.plan
    author_dto = None
    if plan.author:
        author_dto = AuthorDTO(
            id=plan.author_id,
            firstname=plan.author.first_name,
            lastname=plan.author.last_name,
            image_url=_generate_group_asset_url(plan.author.image_url),
            image_key=plan.author.image_url,
        )
    return PlanDTO(
        id=plan.id,
        title=plan.title,
        description=plan.description,
        language=_language_value(plan.language),
        difficulty_level=plan.difficulty_level,
        image_url=_generate_group_asset_url(plan.image_url),
        image_key=plan.image_url,
        total_days=int(plan_info.total_days or 0),
        tags=tags_to_summary_dtos(plan.tag_list),
        status=PlanStatus(plan.status.value),
        featured=bool(plan.featured),
        subscription_count=int(plan_info.subscription_count or 0),
        author=author_dto,
        start_date=plan.start_date,
        series_id=plan.series_id,
        display_order=plan.display_order,
        group_id=group_id,
    )


def _plans_to_dtos(db: Session, plan_list: List[Plan], group_id: UUID) -> List[PlanDTO]:
    if not plan_list:
        return []
    plan_ids = [plan.id for plan in plan_list]
    aggregate_by_id = {
        item.plan.id: item
        for item in get_plans_with_aggregates_by_ids(db=db, plan_ids=plan_ids)
    }
    return [
        _plan_aggregate_to_dto(aggregate_by_id[plan.id], group_id=group_id)
        for plan in plan_list
        if plan.id in aggregate_by_id
    ]


def _group_to_summary(
    group: AuthorGroup,
    follower_count: int = 0,
    joiner_count: int = 0,
    public: bool = False,
    language: Optional[str] = None,
    my_role: Optional[AuthorGroupMemberRole | str] = None,
    my_join_request_status: Optional[str] = None,
) -> AuthorGroupSummaryDTO:
    dto_class = PublicAuthorGroupSummaryDTO if public else AuthorGroupSummaryDTO
    tags = _group_tag_names(group.tags) if public else tags_to_summary_dtos(group.tags)
    role = (
        AuthorGroupMemberRole(_to_role_value(my_role))
        if my_role is not None and not public
        else None
    )
    return dto_class(
        id=group.id,
        slug=group.slug,
        group_type=_to_group_type(group.group_type),
        is_public=group.is_public,
        status=_to_group_status(group.status),
        avatar_key=group.avatar_key,
        banner_key=group.banner_key,
        avatar_url=_generate_group_asset_url(group.avatar_key),
        banner_url=_generate_group_asset_url(group.banner_key),
        metadata=_metadata_response(group.metadata_entries, language=language),
        tags=tags,
        follower_count=follower_count,
        joiner_count=joiner_count,
        member_count=len(group.members),
        my_role=role,
        **(
            {"my_join_request_status": my_join_request_status}
            if public and my_join_request_status
            else {}
        ),
    )


def _group_to_followed_summary(
    group: AuthorGroup,
    follower_count: int = 0,
    language: Optional[str] = None,
) -> UserFollowedAuthorGroupDTO:
    return UserFollowedAuthorGroupDTO(
        id=group.id,
        avatar_key=group.avatar_key,
        avatar_url=_generate_group_asset_url(group.avatar_key),
        metadata=_metadata_response(group.metadata_entries, language=language),
        follower_count=follower_count,
        tags=_group_tag_names(group.tags),
    )


def _group_to_joined_summary(
    group: AuthorGroup,
    joiner_count: int = 0,
    language: Optional[str] = None,
) -> UserJoinedAuthorGroupDTO:
    return UserJoinedAuthorGroupDTO(
        id=group.id,
        avatar_key=group.avatar_key,
        avatar_url=_generate_group_asset_url(group.avatar_key),
        metadata=_metadata_response(group.metadata_entries, language=language),
        joiner_count=joiner_count,
        tags=_group_tag_names(group.tags),
    )


def get_group_summaries_by_ids(
    db: Session,
    group_ids: Sequence[UUID],
    language: Optional[str] = None,
) -> Dict[UUID, AuthorGroupSummaryDTO]:
    if not group_ids:
        return {}
    unique_group_ids = list(dict.fromkeys(group_ids))
    groups = get_groups_by_ids(db=db, group_ids=unique_group_ids)
    follower_count_map = get_followers_count_map(db=db, group_ids=unique_group_ids)
    joiner_count_map = get_joiners_count_map(db=db, group_ids=unique_group_ids)
    return {
        group.id: _group_to_summary(
            group,
            follower_count=follower_count_map.get(group.id, 0),
            joiner_count=joiner_count_map.get(group.id, 0),
            language=language,
        )
        for group in groups
    }


def _group_to_detail(
    group: AuthorGroup,
    follower_count: int = 0,
    joiner_count: int = 0,
    db: Optional[Session] = None,
    public: bool = False,
    language: Optional[str] = None,
    user_id: Optional[UUID] = None,
    teaser: bool = False,
    my_join_request_status: Optional[str] = None,
) -> AuthorGroupDetailDTO:
    if teaser:
        db = None
    if db is not None:
        group_series = get_series_by_group_id(db=db, group_id=group.id)
        group_plans = get_plans_by_group_id(db=db, group_id=group.id)
        series_dtos = _series_to_dtos(
            db=db,
            series_list=group_series,
            group_id=group.id,
            language=language,
            published_only=public,
            user_id=user_id,
        )
        plans_dtos = _plans_to_dtos(db=db, plan_list=group_plans, group_id=group.id)
    else:
        series_dtos = []
        plans_dtos = []

    dto_class = PublicAuthorGroupDetailDTO if public else AuthorGroupDetailDTO
    tags = _group_tag_names(group.tags) if public else tags_to_summary_dtos(group.tags)
    return dto_class(
        id=group.id,
        slug=group.slug,
        group_type=_to_group_type(group.group_type),
        is_public=group.is_public,
        status=_to_group_status(group.status),
        avatar_key=group.avatar_key,
        banner_key=group.banner_key,
        avatar_url=_generate_group_asset_url(group.avatar_key),
        banner_url=_generate_group_asset_url(group.banner_key),
        metadata=_metadata_response(group.metadata_entries, language=language),
        members=[] if teaser else _members_to_dtos(group.members),
        tags=tags,
        social_links=[] if teaser else _social_links_to_dtos(group.social_links),
        series=series_dtos,
        plans=plans_dtos,
        follower_count=follower_count,
        joiner_count=joiner_count,
        **(
            {"my_join_request_status": my_join_request_status}
            if public and my_join_request_status
            else {}
        ),
    )


def create_author_group(token: str, request: CreateAuthorGroupRequest) -> AuthorGroupDetailDTO:
    _assert_metadata_valid(request.metadata)
    author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        if get_group_by_slug(db=db, slug=request.slug):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group slug already exists")

        metadata_entries = [
            AuthorGroupMetadata(
                language=item.language.value,
                title=item.title,
                sub_title=item.sub_title,
                description=item.description,
                description_long=item.description_long,
            )
            for item in request.metadata
        ]
        group = AuthorGroup(
            slug=request.slug,
            group_type=request.group_type.value,
            is_public=request.is_public,
            avatar_key=request.avatar_key,
            banner_key=request.banner_key,
            created_by=author.email,
            updated_by=author.email,
        )
        owner_member = AuthorGroupMember(
            author_id=author.id,
            role=AuthorGroupMemberRole.OWNER,
            created_by=author.email,
            updated_by=author.email,
        )
        created = create_group(db=db, group=group, metadata_entries=metadata_entries, owner_member=owner_member)
        loaded = get_group_by_id(db=db, group_id=created.id)
        return _group_to_detail(loaded, follower_count=0, db=db)


def update_author_group(token: str, group_id: UUID, request: UpdateAuthorGroupRequest) -> AuthorGroupDetailDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if not is_super_admin(author):
            member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
            _assert_role_allowed(member=member, allowed_roles=_GROUP_SETTINGS_ROLES)

        fields_set = request.model_fields_set

        if "slug" in fields_set:
            if request.slug != group.slug:
                existing = get_group_by_slug(db=db, slug=request.slug)
                if existing and existing.id != group.id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Group slug already exists")
            group.slug = request.slug
        became_public = False
        if "is_public" in fields_set:
            became_public = bool(request.is_public) and not group.is_public
            group.is_public = request.is_public
        if "avatar_key" in fields_set:
            group.avatar_key = request.avatar_key
        if "banner_key" in fields_set:
            group.banner_key = request.banner_key
        if "metadata" in fields_set:
            _assert_metadata_valid(request.metadata)
            metadata_entries = [
                AuthorGroupMetadata(
                    language=item.language.value,
                    title=item.title,
                    sub_title=item.sub_title,
                    description=item.description,
                    description_long=item.description_long,
                )
                for item in request.metadata
            ]
            replace_group_metadata(db=db, group_id=group_id, metadata_entries=metadata_entries)
            db.expire(group, ["metadata_entries"])

        group.updated_by = author.email
        group.updated_at = datetime.now(timezone.utc)
        # Admit pending applicants in the same transaction as the visibility
        # flip, so the group can never be public with applicants left waiting.
        # The group lock also blocks a concurrent submission from inserting a
        # new PENDING row after this sweep.
        if became_public:
            lock_group_visibility(db=db, group_id=group_id)
            _approve_pending_join_requests_on_publish(db, group_id=group_id)
        update_group(db=db, group=group)
        loaded = get_group_by_id(db=db, group_id=group_id)
        followers_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        joiners_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_detail(
            group=loaded,
            follower_count=followers_count,
            joiner_count=joiners_count,
            db=db,
        )


def update_group_status(
    token: str,
    group_id: UUID,
    request: UpdateAuthorGroupStatusRequest,
) -> AuthorGroupDetailDTO:
    """Publish or hide a group.

    Kept separate from update_author_group so a routine settings edit can never
    publish or hide a group by accident. is_public is untouched.
    """
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if not is_super_admin(author):
            member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
            _assert_role_allowed(member=member, allowed_roles=_GROUP_SETTINGS_ROLES)

        # Lock the row so an in-flight chat send that already passed its status
        # check cannot commit a message after this hide lands.
        lock_group_status(db=db, group_id=group_id)

        group.status = request.status
        group.updated_by = author.email
        group.updated_at = datetime.now(timezone.utc)
        update_group(db=db, group=group)

        loaded = get_group_by_id(db=db, group_id=group_id)
        followers_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        joiners_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_detail(
            group=loaded,
            follower_count=followers_count,
            joiner_count=joiners_count,
            db=db,
        )


def delete_author_group(token: str, group_id: UUID) -> None:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if not is_super_admin(author):
            member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
            _assert_role_allowed(
                member=member,
                allowed_roles=[AuthorGroupMemberRole.OWNER],
            )

        now = datetime.now(timezone.utc)
        group.deleted_at = now
        group.deleted_by = author.email
        group.updated_at = now
        group.updated_by = author.email
        update_group(db=db, group=group)


def get_author_group_detail(
    group_id: UUID,
    language: Optional[str] = None,
    token: Optional[str] = None,
) -> PublicAuthorGroupDetailDTO:
    user_id = None
    if token:
        try:
            user = validate_and_extract_user_details(token=token)
            user_id = user.id
        except Exception:
            pass
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        # A private group is discoverable so it can be requested, but a
        # non-joiner only sees the teaser: no members, contacts or content.
        teaser = not group.is_public and not (
            user_id is not None
            and is_user_joined_group(db=db, group_id=group_id, user_id=user_id)
        )
        follower_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        joiner_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        join_request_status = (
            get_join_request_status_map(db=db, user_id=user_id, group_ids=[group_id]).get(group_id)
            if user_id is not None
            else None
        )
        return _group_to_detail(
            group=group,
            follower_count=follower_count,
            joiner_count=joiner_count,
            db=db, public=True,
            language=language,
            user_id=user_id,
            teaser=teaser,
            my_join_request_status=join_request_status,
        )


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _restricted_ids_for_timezone(
    item_type: RestrictedItemType,
    timezone_name: Optional[str],
) -> Optional[List[UUID]]:
    """IDs to exclude at the query layer so restricted items never occupy a
    fetch-window slot ahead of eligible ones. None means no exclusion needed."""
    if not is_china_timezone(timezone_name):
        return None
    restricted_ids = get_restricted_item_ids(item_type)
    return list(restricted_ids) if restricted_ids else None


async def get_group_practices(
    group_id: UUID,
    skip: int = 0,
    limit: int = 20,
    language: Optional[str] = None,
    token: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> GroupPracticesResponse:
    user_id = None
    if token:
        try:
            user = validate_and_extract_user_details(token=token)
            user_id = user.id
        except Exception:
            pass

    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not group.is_public or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)

        group_series = get_series_by_group_id(db=db, group_id=group_id)
        series_dtos = _series_to_dtos(
            db=db,
            series_list=group_series,
            group_id=group_id,
            language=language,
            published_only=True,
            user_id=user_id,
        )
        series_cards = [
            (
                _as_aware_utc(series.created_at),
                str(series.id),
                GroupPracticeCardDTO(type=GroupPracticeType.SERIES, series=dto),
            )
            for series, dto in zip(group_series, series_dtos)
        ]

    accumulators_response = get_group_accumulators_service(
        group_id=group_id,
        skip=0,
        limit=_PRACTICES_FETCH_LIMIT,
        token=token,
        timezone_name=timezone_name,
    )
    accumulator_cards = [
        (
            _as_aware_utc(acc.created_at),
            str(acc.id),
            GroupPracticeCardDTO(type=GroupPracticeType.ACCUMULATOR, accumulator=acc),
        )
        for acc in accumulators_response.accumulators
    ]

    collections_response = await list_group_collections_service(
        group_id=group_id,
        skip=0,
        limit=_PRACTICES_FETCH_LIMIT,
        timezone_name=timezone_name,
    )
    collection_cards = [
        (
            _as_aware_utc(datetime.fromisoformat(collection.created_at)),
            str(collection.id),
            GroupPracticeCardDTO(type=GroupPracticeType.COLLECTION, collection=collection),
        )
        for collection in collections_response.collections
    ]

    all_cards = series_cards + accumulator_cards + collection_cards
    all_cards.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    total = len(all_cards)
    page_cards = [card for _, _, card in all_cards[skip:skip + limit]]

    return GroupPracticesResponse(
        practices=page_cards,
        skip=skip,
        limit=limit,
        total=total,
    )


def _group_card_title(group: AuthorGroup, language: Optional[str] = None) -> Optional[str]:
    entries = list(group.metadata_entries or [])
    if not entries:
        return group.slug
    preferred = filter_by_language_with_fallback(
        entries=entries,
        language=language,
        language_of=lambda item: _language_value(item.language),
    )
    if preferred:
        return preferred[0].title
    for entry in entries:
        if _language_value(entry.language).upper() == "EN":
            return entry.title
    return entries[0].title


def get_group_practices_feed(
    token: Optional[str] = None,
    group_id: Optional[UUID] = None,
    should_include_unfollowed: bool = False,
    skip: int = 0,
    limit: int = 20,
    language: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> GroupPracticesFeedResponse:
    """Merged feed of practices (series, group accumulators, plans that are
    not part of a series, and recitation collections) across the user's
    joined public groups; with should_include_unfollowed=True, across all
    public groups. Guests (no token) always see published public groups."""
    current_user = None
    if token:
        current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        scope_group_ids, joined_group_id_set = resolve_public_group_scope(
            db=db,
            user_id=current_user.id if current_user else None,
            should_include_unfollowed=should_include_unfollowed,
        )
        if group_id is not None:
            scope_group_ids = [item for item in scope_group_ids if item == group_id]
        scope_group_ids = filter_items_for_timezone(
            scope_group_ids,
            timezone_name=timezone_name,
            item_type=RestrictedItemType.GROUP,
            id_of=lambda item: item,
        )
        if not scope_group_ids:
            return GroupPracticesFeedResponse(
                practices=[],
                skip=skip,
                limit=limit,
                total=0,
                include_unfollowed=should_include_unfollowed,
            )

        # Restricted items are excluded at the query layer (not after fetching)
        # so a skip+limit-sized fetch window never omits eligible older items,
        # and the reported total reflects only eligible rows, at any depth.
        fetch_limit = skip + limit

        series_list, series_total = get_series_for_group_ids(
            db=db,
            group_ids=scope_group_ids,
            limit=fetch_limit,
            exclude_ids=_restricted_ids_for_timezone(RestrictedItemType.SERIES, timezone_name),
        )

        plans_list, plans_total = get_standalone_plans_for_group_ids(
            db=db,
            group_ids=scope_group_ids,
            limit=fetch_limit,
            exclude_ids=_restricted_ids_for_timezone(RestrictedItemType.PLAN, timezone_name),
        )

        accumulators, accumulators_total = get_group_accumulators_for_group_ids(
            db=db,
            group_ids=scope_group_ids,
            limit=fetch_limit,
            exclude_ids=_restricted_ids_for_timezone(RestrictedItemType.GROUP_ACCUMULATOR, timezone_name),
        )

        collections, collections_total = get_collections_for_group_ids_with_total(
            db=db,
            group_ids=scope_group_ids,
            limit=fetch_limit,
            exclude_ids=_restricted_ids_for_timezone(
                RestrictedItemType.GROUP_RECITATION_COLLECTION, timezone_name
            ),
        )
        collection_item_counts = get_collection_item_counts(
            db=db, collection_ids=[collection.id for collection in collections]
        )
        collection_dtos = [
            GroupRecitationCollectionDTO(
                id=collection.id,
                group_id=collection.group_id,
                name=collection.name,
                img_url=_generate_group_asset_url(collection.img_url),
                item_count=collection_item_counts.get(collection.id, 0),
                created_at=collection.created_at.isoformat()
                if hasattr(collection.created_at, "isoformat")
                else str(collection.created_at),
            )
            for collection in collections
        ]

        # Series DTOs are built per owning group because enrollment and partner
        # lookups are scoped to a group.
        series_by_group: Dict[UUID, List[Series]] = {}
        for series in series_list:
            series_by_group.setdefault(series.group_id, []).append(series)
        series_pairs = []
        for owning_group_id, group_series in series_by_group.items():
            dtos = _series_to_dtos(
                db=db,
                series_list=group_series,
                group_id=owning_group_id,
                language=language,
                published_only=True,
                user_id=current_user.id if current_user else None,
            )
            series_pairs.extend(zip(group_series, dtos))

        plan_aggregate_by_id = {
            item.plan.id: item
            for item in get_plans_with_aggregates_by_ids(
                db=db, plan_ids=[plan.id for plan in plans_list]
            )
        }

        accumulator_ids = [accumulator.id for accumulator in accumulators]
        joined_accumulator_ids = set()
        if current_user:
            joined_accumulator_ids = set(
                get_joined_group_accumulator_ids_by_user(
                    db=db,
                    user_id=current_user.id,
                    group_accumulator_ids=accumulator_ids,
                )
            )
        accumulator_member_counts = get_group_accumulator_joiners_counts(
            db=db, group_accumulator_ids=accumulator_ids
        )

        card_group_ids = list({
            *[series.group_id for series, _ in series_pairs],
            *[plan.group_id for plan in plans_list],
            *[accumulator.group_id for accumulator in accumulators],
            *[collection.group_id for collection in collections],
        })
        group_by_id = {
            group.id: group
            for group in get_groups_by_ids(db=db, group_ids=card_group_ids)
        }

        def _feed_item(
            item_id,
            item_group_id: UUID,
            created_at: datetime,
            practice_type: GroupPracticeType,
            **payload,
        ):
            group = group_by_id.get(item_group_id)
            practice_at = _as_aware_utc(created_at)
            return (
                practice_at,
                str(item_id),
                GroupPracticeFeedItemDTO(
                    type=practice_type,
                    practice_at=practice_at,
                    is_joined=item_group_id in joined_group_id_set,
                    group_id=item_group_id,
                    group_name=_group_card_title(group, language=language) if group else None,
                    group_slug=group.slug if group else None,
                    group_avatar_url=_generate_group_asset_url(group.avatar_key) if group else None,
                    **payload,
                ),
            )

        cards = [
            _feed_item(series.id, series.group_id, series.created_at, GroupPracticeType.SERIES, series=dto)
            for series, dto in series_pairs
        ]
        cards.extend(
            _feed_item(
                plan.id,
                plan.group_id,
                plan.created_at,
                GroupPracticeType.PLAN,
                plan=_plan_aggregate_to_dto(plan_aggregate_by_id[plan.id], group_id=plan.group_id),
            )
            for plan in plans_list
            if plan.id in plan_aggregate_by_id
        )
        cards.extend(
            _feed_item(
                accumulator.id,
                accumulator.group_id,
                accumulator.created_at,
                GroupPracticeType.ACCUMULATOR,
                accumulator=_group_accumulator_to_dto(
                    accumulator,
                    is_joined=accumulator.id in joined_accumulator_ids,
                    member_count=accumulator_member_counts.get(accumulator.id, 0),
                ),
            )
            for accumulator in accumulators
        )
        cards.extend(
            _feed_item(
                collection.id,
                collection.group_id,
                collection.created_at,
                GroupPracticeType.COLLECTION,
                collection=dto,
            )
            for collection, dto in zip(collections, collection_dtos)
        )

        cards.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        total = series_total + plans_total + accumulators_total + collections_total
        page_cards = [card for _, _, card in cards[skip:skip + limit]]

    return GroupPracticesFeedResponse(
        practices=page_cards,
        skip=skip,
        limit=limit,
        total=total,
        include_unfollowed=should_include_unfollowed,
    )


def list_group_members(
    group_id: UUID,
    skip: int,
    limit: int,
) -> AuthorGroupMembersListResponse:
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        # Intended behaviour, not an oversight: this endpoint is unauthenticated
        # and lists members for private groups as well as public ones. Product
        # decision — the frontend gates who is shown the members list, so the
        # backend deliberately does not filter by is_public or check membership.
        # Note the trade-off this accepts: member profiles (username, fullname,
        # avatar) for a private group are readable by anyone holding the group id.
        # Revisit here, not in the frontend, if that ever stops being acceptable.
        # Status is still enforced: an unpublished group lists no members.
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        users, total = list_group_joiners_paginated(
            db=db,
            group_id=group_id,
            skip=skip,
            limit=limit,
        )
        return AuthorGroupMembersListResponse(
            total_members=total,
            list=[
                AuthorGroupMemberProfileDTO(
                    username=user.username,
                    fullname=_user_fullname(user),
                    avatar_url=_user_avatar_url(user),
                )
                for user in users
            ],
            skip=skip,
            limit=limit,
        )


def get_cms_group_detail(
    token: str,
    group_id: UUID,
    language: Optional[str] = None,
) -> AuthorGroupDetailDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if not is_super_admin(author) and not is_reviewer(author):
            _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
        follower_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        joiner_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_detail(
            group=group,
            follower_count=follower_count,
            joiner_count=joiner_count,
            db=db,
            language=language,
        )


def list_public_groups(
    skip: int,
    limit: int,
    search: Optional[str] = None,
    language: Optional[str] = None,
    tag_id: Optional[UUID] = None,
    group_type: AuthorGroupType = AuthorGroupType.COMMUNITY,
    token: Optional[str] = None,
    timezone_name: Optional[str] = None,
) -> PublicAuthorGroupListResponse:
    with SessionLocal() as db:
        exclude_group_ids = None
        user_id = None
        if token:
            try:
                user = validate_and_extract_user_details(token=token)
                user_id = user.id
                joined_ids = get_joined_group_ids_by_user(db=db, user_id=user.id)
                if joined_ids:
                    exclude_group_ids = joined_ids
            except Exception:
                pass
        # status is filtered, is_public deliberately is not: a private group must
        # stay discoverable or nobody can request to join it. Summaries carry only
        # public metadata — members and content stay gated to joiners.
        groups, total = get_groups_paginated(
            db=db,
            skip=skip,
            limit=limit,
            search=search,
            tag_id=tag_id,
            exclude_group_ids=exclude_group_ids,
            group_type=group_type,
            status=AuthorGroupStatus.PUBLISHED,
        )
        groups = filter_items_for_timezone(
            groups,
            timezone_name=timezone_name,
            item_type=RestrictedItemType.GROUP,
            id_of=lambda group: group.id,
        )
        group_ids = [group.id for group in groups]
        follower_count_map = get_followers_count_map(db=db, group_ids=group_ids)
        joiner_count_map = get_joiners_count_map(db=db, group_ids=group_ids)
        join_request_status_map = (
            get_join_request_status_map(db=db, user_id=user_id, group_ids=group_ids)
            if user_id is not None
            else {}
        )
        return PublicAuthorGroupListResponse(
            groups=[
                _group_to_summary(
                    group=item,
                    follower_count=follower_count_map.get(item.id, 0),
                    joiner_count=joiner_count_map.get(item.id, 0),
                    public=True,
                    language=language,
                    my_join_request_status=join_request_status_map.get(item.id),
                )
                for item in groups
            ],
            skip=skip,
            limit=limit,
            total=total,
        )


def list_cms_groups(
    token: str,
    skip: int,
    limit: int,
    search: Optional[str] = None,
    language: Optional[str] = None,
    tag_id: Optional[UUID] = None,
    is_public: Optional[bool] = None,
    for_transfer: bool = False,
    group_type: Optional[AuthorGroupType] = None,
    group_status: Optional[AuthorGroupStatus] = None,
) -> AuthorGroupListResponse:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group_ids = None
        if for_transfer:
            require_cms_write_access(author)
        elif not is_super_admin(author) and not is_reviewer(author):
            membership_rows = db.query(AuthorGroupMember.group_id).filter(AuthorGroupMember.author_id == author.id).all()
            group_ids = [row.group_id for row in membership_rows]
        groups, total = get_groups_paginated(
            db=db,
            skip=skip,
            limit=limit,
            search=search,
            language=language,
            tag_id=tag_id,
            group_ids=group_ids,
            is_public=is_public,
            group_type=group_type,
            # Unset means Studio sees every status.
            status=group_status,
        )
        ids = [group.id for group in groups]
        follower_count_map = get_followers_count_map(db=db, group_ids=ids)
        joiner_count_map = get_joiners_count_map(db=db, group_ids=ids)
        my_role_map = get_member_roles_map(db=db, author_id=author.id, group_ids=ids)
        return AuthorGroupListResponse(
            groups=[
                _group_to_summary(
                    group=item,
                    follower_count=follower_count_map.get(item.id, 0),
                    joiner_count=joiner_count_map.get(item.id, 0),
                    language=language,
                    my_role=my_role_map.get(item.id),
                )
                for item in groups
            ],
            skip=skip,
            limit=limit,
            total=total,
        )


def replace_group_tags(token: str, group_id: UUID, request: ReplaceGroupTagsRequest) -> AuthorGroupDetailDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if not is_super_admin(author):
            member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
            _assert_role_allowed(member=member, allowed_roles=_GROUP_SETTINGS_ROLES)
        _validate_group_links(db=db, tag_ids=request.tag_ids, series_ids=None, plan_ids=None)
        replace_group_relation_ids(db=db, table=author_group_tags, group_id=group_id, column_name="tag_id", ids=request.tag_ids)
        db.commit()
        loaded = get_group_by_id(db=db, group_id=group_id)
        follower_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        joiner_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_detail(loaded, follower_count=follower_count, joiner_count=joiner_count, db=db)


def replace_group_social_links_by_id(
    token: str,
    group_id: UUID,
    request: ReplaceGroupSocialLinksRequest,
) -> AuthorGroupDetailDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if not is_super_admin(author):
            member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
            _assert_role_allowed(member=member, allowed_roles=_GROUP_SETTINGS_ROLES)
        social_links = [AuthorGroupSocialLink(platform=item.platform, url=item.url) for item in request.social_links]
        replace_group_social_links(db=db, group_id=group_id, social_links=social_links)
        db.commit()
        loaded = get_group_by_id(db=db, group_id=group_id)
        follower_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        joiner_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_detail(loaded, follower_count=follower_count, joiner_count=joiner_count, db=db)


def follow_group(token: str, group_id: UUID) -> None:
    user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not group.is_public or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        _assert_group_allows_engagement(group=group, action="follow")
        upsert_group_follow(db=db, group_id=group_id, user_id=user.id)


def unfollow_group(token: str, group_id: UUID) -> None:
    user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        remove_group_follow(db=db, group_id=group_id, user_id=user.id)


def get_followed_group(
    token: str,
    group_id: UUID,
    language: Optional[str] = None,
) -> UserFollowedAuthorGroupDTO:
    user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        if not is_user_following_group(db=db, group_id=group_id, user_id=user.id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        follower_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_followed_summary(
            group=group,
            follower_count=follower_count,
            language=language,
        )


def list_followed_groups(
    token: str,
    skip: int,
    limit: int,
    language: Optional[str] = None,
) -> UserFollowedAuthorGroupListResponse:
    user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        group_ids = get_following_group_ids_by_user(db=db, user_id=user.id)
        groups, total = get_groups_paginated(
            db=db,
            skip=skip,
            limit=limit,
            group_ids=group_ids,
            group_type=AuthorGroupType.PAGE,
            status=AuthorGroupStatus.PUBLISHED,
        )
        follower_count_map = get_followers_count_map(db=db, group_ids=[group.id for group in groups])
        return UserFollowedAuthorGroupListResponse(
            groups=[
                _group_to_followed_summary(
                    group=item,
                    follower_count=follower_count_map.get(item.id, 0),
                    language=language,
                )
                for item in groups
            ],
            skip=skip,
            limit=limit,
            total=total,
        )


def join_group(token: str, group_id: UUID) -> None:
    user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        _assert_group_allows_engagement(group=group, action="join")
        if not group.is_public:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GROUP_IS_PRIVATE_USE_REQUEST,
            )
        upsert_group_join(db=db, group_id=group_id, user_id=user.id)


def leave_group(token: str, group_id: UUID) -> None:
    user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        remove_group_accumulator_joins_for_group(
            db=db,
            user_id=user.id,
            group_id=group_id,
        )
        leave_group_membership(db=db, user_id=user.id, group_id=group_id)


def get_joined_group(
    token: str,
    group_id: UUID,
    language: Optional[str] = None,
) -> UserJoinedAuthorGroupDTO:
    user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        if not is_user_joined_group(db=db, group_id=group_id, user_id=user.id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        joiner_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_joined_summary(
            group=group,
            joiner_count=joiner_count,
            language=language,
        )


def list_joined_groups(
    token: str,
    skip: int,
    limit: int,
    language: Optional[str] = None,
) -> UserJoinedAuthorGroupListResponse:
    user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        group_ids = get_joined_group_ids_by_user(db=db, user_id=user.id)
        groups, total = get_groups_paginated(
            db=db,
            skip=skip,
            limit=limit,
            group_ids=group_ids,
            group_type=AuthorGroupType.COMMUNITY,
            status=AuthorGroupStatus.PUBLISHED,
        )
        joiner_count_map = get_joiners_count_map(db=db, group_ids=[group.id for group in groups])
        return UserJoinedAuthorGroupListResponse(
            groups=[
                _group_to_joined_summary(
                    group=item,
                    joiner_count=joiner_count_map.get(item.id, 0),
                    language=language,
                )
                for item in groups
            ],
            skip=skip,
            limit=limit,
            total=total,
        )


def _to_join_request_status(status_value) -> AuthorGroupJoinRequestStatus:
    if hasattr(status_value, "value"):
        return AuthorGroupJoinRequestStatus(status_value.value)
    return AuthorGroupJoinRequestStatus(status_value)


def _join_request_to_dto(join_request: AuthorGroupJoinRequest) -> GroupJoinRequestDTO:
    return GroupJoinRequestDTO(
        id=join_request.id,
        status=_to_join_request_status(join_request.status),
    )


def _join_request_to_user_dto(join_request: AuthorGroupJoinRequest) -> GroupJoinRequestUserDTO:
    user = join_request.user
    return GroupJoinRequestUserDTO(
        id=join_request.id,
        user_id=join_request.user_id,
        user_name=_user_fullname(user) if user else "",
        user_avatar_url=_user_avatar_url(user) if user else None,
        message=join_request.message,
        status=_to_join_request_status(join_request.status),
        created_at=join_request.created_at,
    )


def _get_join_request_for_group_or_404(
    db, *, group_id: UUID, request_id: UUID, for_update: bool = False
):
    join_request = get_join_request_by_id(
        db=db, request_id=request_id, load_group=True, for_update=for_update
    )
    if not join_request or join_request.group_id != group_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=JOIN_REQUEST_NOT_FOUND,
        )
    return join_request


def _assert_join_request_pending(join_request: AuthorGroupJoinRequest) -> None:
    if _to_join_request_status(join_request.status) != AuthorGroupJoinRequestStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This join request has already been reviewed",
        )


def _assert_can_manage_join_requests(db, *, group_id: UUID, author) -> None:
    if is_super_admin(author):
        return
    member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
    _assert_role_allowed(member=member, allowed_roles=_MEMBER_MANAGEMENT_ROLES)


def _notify_moderators_of_join_request(
    *,
    group_id: UUID,
    group_title: str,
    requester_name: str,
    join_request_id: UUID,
    moderator_ids: List[UUID],
) -> None:
    """Best-effort: a notification failure must not lose the join request.

    reference_id is the group, not the request: notifications carry no other
    id field, and Studio needs the group to route to its review screen."""
    for author_id in moderator_ids:
        try:
            create_notification_record(
                recipient_author_id=author_id,
                title=f"Request to join {group_title}",
                description=f"{requester_name} asked to join {group_title}.",
                category=NOTIFICATION_CATEGORY_GROUP_JOIN_REQUEST,
                reference_id=group_id,
            )
        except Exception:
            logging.exception(
                "Failed to notify author %s of join request %s", author_id, join_request_id
            )


def submit_group_join_request(
    token: str,
    group_id: UUID,
    request: CreateGroupJoinRequest,
) -> GroupJoinRequestDTO:
    user = validate_and_extract_user_details(token=token)
    message = request.message.strip() if request.message else None
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        _assert_group_allows_engagement(group=group, action="join")
        # Lock the group so a concurrent publish cannot flip it public after we
        # read it, which would strand this request as PENDING on a public group.
        is_public = lock_group_visibility(db=db, group_id=group_id)
        if is_public is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if is_public:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This group is public; join it directly",
            )
        if is_user_joined_group(db=db, group_id=group_id, user_id=user.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You are already a member of this group",
            )
        if has_pending_join_request(db=db, group_id=group_id, user_id=user.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A join request is already pending for this group",
            )

        created = create_group_join_request(
            db=db,
            join_request=AuthorGroupJoinRequest(
                group_id=group_id,
                user_id=user.id,
                message=message,
                status=AuthorGroupJoinRequestStatus.PENDING.value,
            ),
        )
        dto = _join_request_to_dto(created)
        group_title = _group_title_from_metadata(group.metadata_entries)
        requester_name = _user_fullname(user) or "Someone"
        moderator_ids = list_group_member_ids_by_roles(
            db=db,
            group_id=group_id,
            roles=[_to_role_value(role) for role in _MEMBER_MANAGEMENT_ROLES],
        )
        join_request_id = created.id

    _notify_moderators_of_join_request(
        group_id=group_id,
        group_title=group_title,
        requester_name=requester_name,
        join_request_id=join_request_id,
        moderator_ids=moderator_ids,
    )
    enqueue_join_request_created(join_request_id)
    return dto


def list_group_join_requests(
    token: str,
    group_id: UUID,
    skip: int,
    limit: int,
    status_filter: Optional[AuthorGroupJoinRequestStatus] = AuthorGroupJoinRequestStatus.PENDING,
) -> GroupJoinRequestListResponse:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        _assert_can_manage_join_requests(db, group_id=group_id, author=author)

        rows, total = list_join_requests_by_group(
            db=db,
            group_id=group_id,
            skip=skip,
            limit=limit,
            status=status_filter,
        )
        return GroupJoinRequestListResponse(
            requests=[_join_request_to_user_dto(row) for row in rows],
            skip=skip,
            limit=limit,
            total=total,
        )


def approve_group_join_request(
    token: str,
    group_id: UUID,
    request_id: UUID,
) -> GroupJoinRequestDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        _assert_can_manage_join_requests(db, group_id=group_id, author=author)

        join_request = _get_join_request_for_group_or_404(
            db, group_id=group_id, request_id=request_id, for_update=True
        )
        _assert_join_request_pending(join_request)

        # One transaction: the row lock taken above must hold until both the
        # membership and the APPROVED status are committed together.
        upsert_group_join(
            db=db, group_id=group_id, user_id=join_request.user_id, commit=False
        )
        _mark_join_request_reviewed(
            join_request,
            new_status=AuthorGroupJoinRequestStatus.APPROVED,
            reviewer_id=author.id,
        )
        save_join_request(db=db, join_request=join_request)
        dto = _join_request_to_dto(join_request)

    enqueue_join_request_decided(request_id)
    return dto


def reject_group_join_request(
    token: str,
    group_id: UUID,
    request_id: UUID,
) -> GroupJoinRequestDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        _assert_can_manage_join_requests(db, group_id=group_id, author=author)

        join_request = _get_join_request_for_group_or_404(
            db, group_id=group_id, request_id=request_id, for_update=True
        )
        _assert_join_request_pending(join_request)

        _mark_join_request_reviewed(
            join_request,
            new_status=AuthorGroupJoinRequestStatus.REJECTED,
            reviewer_id=author.id,
        )
        save_join_request(db=db, join_request=join_request)
        dto = _join_request_to_dto(join_request)

    enqueue_join_request_decided(request_id)
    return dto


def _mark_join_request_reviewed(
    join_request: AuthorGroupJoinRequest,
    *,
    new_status: AuthorGroupJoinRequestStatus,
    reviewer_id: Optional[UUID],
) -> None:
    now = datetime.now(timezone.utc)
    join_request.status = new_status.value
    join_request.reviewed_by = reviewer_id
    join_request.reviewed_at = now
    join_request.updated_at = now


def _approve_pending_join_requests_on_publish(db, *, group_id: UUID) -> None:
    """A public group is instant-join, so pending requests are admitted on the flip.

    Intentionally dispatches no decision notification: this is a system-level
    sweep triggered by a visibility change, not a per-request moderation
    decision, so applicants are admitted silently. reviewer_id is None for the
    same reason. Only approve/reject by a moderator notifies the applicant.
    """
    pending = list_pending_join_requests_by_group(
        db=db, group_id=group_id, for_update=True
    )
    for join_request in pending:
        # commit=False keeps the row locks held until every membership and
        # status change lands in the same transaction, as moderator approval does.
        upsert_group_join(
            db=db, group_id=group_id, user_id=join_request.user_id, commit=False
        )
        _mark_join_request_reviewed(
            join_request,
            new_status=AuthorGroupJoinRequestStatus.APPROVED,
            reviewer_id=None,
        )
        db.add(join_request)


def _to_invite_status(status_value) -> AuthorGroupInviteStatus:
    if hasattr(status_value, "value"):
        return AuthorGroupInviteStatus(status_value.value)
    return AuthorGroupInviteStatus(status_value)


def _group_name_from_invite(invite: AuthorGroupInvite) -> str:
    group = getattr(invite, "group", None)
    if group is not None and group.metadata_entries:
        return _group_title_from_metadata(group.metadata_entries)
    return "Group"


def _invite_to_dto(
    invite: AuthorGroupInvite,
    *,
    group_name: Optional[str] = None,
    db: Optional[Session] = None,
) -> GroupInviteDTO:
    resolved_group_name = group_name if group_name is not None else _group_name_from_invite(invite)
    inviter_email = invite.created_by
    inviter_name = inviter_email
    if db is not None:
        inviter = find_author_by_email(db=db, email=inviter_email)
        if inviter:
            display_name = _inviter_display_name(inviter)
            if display_name:
                inviter_name = display_name
    return GroupInviteDTO(
        id=invite.id,
        group_id=invite.group_id,
        group_name=resolved_group_name,
        target_email=invite.target_email,
        role=AuthorGroupMemberRole(_to_role_value(invite.role)),
        status=_to_invite_status(invite.status),
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        rejected_at=invite.rejected_at,
        revoked_at=invite.revoked_at,
        created_at=invite.created_at,
        created_by=invite.created_by,
        inviter_name=inviter_name,
        inviter_email=inviter_email,
    )


def _inviter_display_name(author) -> str:
    parts = [getattr(author, "first_name", None), getattr(author, "last_name", None)]
    name = " ".join(part for part in parts if isinstance(part, str) and part.strip()).strip()
    email = getattr(author, "email", None)
    if isinstance(email, str) and email.strip():
        return name or email
    return name


def _group_title_from_metadata(metadata_entries) -> str:
    if not metadata_entries:
        return "Group"
    for entry in metadata_entries:
        language = entry.language
        lang_value = language.value if hasattr(language, "value") else str(language)
        if lang_value.upper() == "EN":
            return entry.title
    return metadata_entries[0].title


def _invite_expires_at() -> datetime:
    """Invite TTL is minutes only (default 30), not days — see GROUP_INVITE_EXPIRY_MINUTES."""
    minutes = get_int("GROUP_INVITE_EXPIRY_MINUTES")
    minutes = max(1, min(minutes, 24 * 60))
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _assert_invite_pending_for_recipient(invite: AuthorGroupInvite, author_email: str) -> None:
    if invite.target_email.lower() != author_email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address",
        )
    invite_status = _to_invite_status(invite.status)
    if invite_status != AuthorGroupInviteStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invite is not pending (status: {invite_status.value})",
        )
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite has expired")


def _mark_invite_notification_read(db, *, recipient_author_id: UUID, invite_id: UUID) -> None:
    mark_notifications_read_by_reference(
        db=db,
        recipient_author_id=recipient_author_id,
        category=NOTIFICATION_CATEGORY_GROUP_INVITE,
        reference_id=invite_id,
    )


def notify_pending_group_invites(author) -> None:
    """Backfill in-app notifications for any group invites addressed to this
    author's email that were sent before they had a Studio account. Called
    once an author becomes verified so the invite is already waiting for them
    the first time they can see the Studio."""
    try:
        with SessionLocal() as db:
            pending = list_pending_invites_by_email(db=db, target_email=author.email)
            for invite in pending:
                if notification_exists_for_reference(
                    db=db,
                    recipient_author_id=author.id,
                    category=NOTIFICATION_CATEGORY_GROUP_INVITE,
                    reference_id=invite.id,
                ):
                    continue
                group_title = _group_name_from_invite(invite)
                inviter = find_author_by_email(db=db, email=invite.created_by)
                inviter_name = _inviter_display_name(inviter) if inviter else invite.created_by
                create_notification_record(
                    recipient_author_id=author.id,
                    title=f"Invitation to join {group_title}",
                    description=f"{inviter_name} invited you to join {group_title}.",
                    category=NOTIFICATION_CATEGORY_GROUP_INVITE,
                    reference_id=invite.id,
                )
    except Exception:
        logging.exception("Failed to backfill group invite notifications for %s", author.email)


def create_group_member_invite(
    token: str,
    group_id: UUID,
    request: CreateGroupInviteRequest,
) -> GroupInviteCreatedResponse:
    author = validate_and_extract_author_details(token=token)
    target_email = request.target_email.strip().lower()
    if not target_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_email is required")

    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        actor_role = _resolve_actor_group_role(db, group_id=group_id, author=author)
        if not is_super_admin(author):
            member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
            _assert_role_allowed(member=member, allowed_roles=_MEMBER_MANAGEMENT_ROLES)

        _assert_invite_role_allowed(
            actor_role=actor_role,
            invite_role=_to_role_value(request.role),
        )

        target_author = find_author_by_email(db=db, email=target_email)
        if target_author and get_group_member(db=db, group_id=group_id, author_id=target_author.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This author is already a member of this group",
            )
        if has_pending_invite(db=db, group_id=group_id, target_email=target_email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A pending invitation already exists for this email",
            )

        invite = AuthorGroupInvite(
            group_id=group_id,
            target_email=target_email,
            role=request.role,
            status=AuthorGroupInviteStatus.PENDING.value,
            expires_at=_invite_expires_at(),
            created_by=author.email,
        )
        created = create_group_invite(db=db, invite=invite)
        loaded_group = get_group_by_id(db=db, group_id=group_id)
        group_title = _group_title_from_metadata(loaded_group.metadata_entries)
        inviter_name = _inviter_display_name(author)
        target_author_id = target_author.id if target_author else None
        created_invite_id = created.id
        invite_dto = _invite_to_dto(created, group_name=group_title, db=db)

    notification = None
    if target_author_id is not None:
        notification = create_notification_record(
            recipient_author_id=target_author_id,
            title=f"Invitation to join {group_title}",
            description=f"{inviter_name} invited you to join {group_title}.",
            category=NOTIFICATION_CATEGORY_GROUP_INVITE,
            reference_id=created_invite_id,
        )

    send_group_invitation_email(
        target_email=target_email,
        inviter_name=inviter_name,
        inviter_email=author.email,
        group_title=group_title,
        invite_role=_to_role_value(request.role),
    )

    return GroupInviteCreatedResponse(
        invite=invite_dto,
        notification_id=notification.id if notification else None,
    )


def list_group_invites(
    token: str,
    group_id: UUID,
    status_filter: Optional[AuthorGroupInviteStatus] = None,
) -> GroupInviteListResponse:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if not is_super_admin(author):
            member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
            _assert_role_allowed(member=member, allowed_roles=[AuthorGroupMemberRole.OWNER, AuthorGroupMemberRole.ADMIN])

        rows = list_invites_by_group(db=db, group_id=group_id, status=status_filter)
        invite_dtos = [_invite_to_dto(row, db=db) for row in rows]
    return GroupInviteListResponse(
        invites=invite_dtos,
        total=len(invite_dtos),
    )


def list_my_pending_group_invites(token: str) -> GroupInviteListResponse:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        rows = list_pending_invites_by_email(db=db, target_email=author.email)
        invite_dtos = [_invite_to_dto(row, db=db) for row in rows]
    return GroupInviteListResponse(
        invites=invite_dtos,
        total=len(invite_dtos),
    )


def accept_group_invite_by_id(token: str, invite_id: UUID) -> AuthorGroupDetailDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        invite = get_invite_by_id(db=db, invite_id=invite_id, load_group=True)
        if not invite:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INVITE_NOT_FOUND)
        _assert_invite_pending_for_recipient(invite=invite, author_email=author.email)

        group = get_group_by_id(db=db, group_id=invite.group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)

        invite_role = _to_role_value(invite.role)
        if invite_role == AuthorGroupMemberRole.OWNER.value and get_owner_count(db=db, group_id=group.id) >= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=GROUP_ALREADY_HAS_OWNER,
            )
        _assert_role_not_owner_assignment(invite_role)

        existing_member = get_group_member(db=db, group_id=group.id, author_id=author.id)
        if existing_member is None:
            add_group_member(
                db=db,
                member=AuthorGroupMember(
                    group_id=group.id,
                    author_id=author.id,
                    role=invite.role,
                    created_by=author.email,
                ),
            )

        now = datetime.now(timezone.utc)
        invite.status = AuthorGroupInviteStatus.ACCEPTED.value
        invite.accepted_at = now
        save_invite(db=db, invite=invite)
        _mark_invite_notification_read(db=db, recipient_author_id=author.id, invite_id=invite.id)

        loaded = get_group_by_id(db=db, group_id=group.id)
        follower_count = get_followers_count_map(db=db, group_ids=[group.id]).get(group.id, 0)
        joiner_count = get_joiners_count_map(db=db, group_ids=[group.id]).get(group.id, 0)
        return _group_to_detail(loaded, follower_count=follower_count, joiner_count=joiner_count, db=db)


def reject_group_invite_by_id(token: str, invite_id: UUID) -> GroupInviteDTO:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        invite = get_invite_by_id(db=db, invite_id=invite_id)
        if not invite:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INVITE_NOT_FOUND)
        _assert_invite_pending_for_recipient(invite=invite, author_email=author.email)

        invite.status = AuthorGroupInviteStatus.REJECTED.value
        invite.rejected_at = datetime.now(timezone.utc)
        save_invite(db=db, invite=invite)
        _mark_invite_notification_read(db=db, recipient_author_id=author.id, invite_id=invite.id)
        return _invite_to_dto(invite, db=db)


def revoke_group_invite(token: str, group_id: UUID, invite_id: UUID) -> None:
    author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        actor_role = _resolve_actor_group_role(db, group_id=group_id, author=author)
        if not is_super_admin(author):
            member = _get_member_or_403(db=db, group_id=group_id, author_id=author.id)
            _assert_role_allowed(member=member, allowed_roles=_MEMBER_MANAGEMENT_ROLES)

        invite = get_invite_by_id(db=db, invite_id=invite_id)
        if not invite or invite.group_id != group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INVITE_NOT_FOUND)
        _assert_can_revoke_invite(actor_role=actor_role, invite=invite)
        if _to_invite_status(invite.status) != AuthorGroupInviteStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only pending invites can be revoked",
            )
        revoke_invite(db=db, invite=invite, revoked_by=author.email)
        target_author = find_author_by_email(db=db, email=invite.target_email)
        if target_author:
            _mark_invite_notification_read(
                db=db,
                recipient_author_id=target_author.id,
                invite_id=invite.id,
            )


def update_group_member_role(
    token: str,
    group_id: UUID,
    author_id: UUID,
    request: UpdateGroupMemberRoleRequest,
) -> AuthorGroupDetailDTO:
    current_author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)
        if not is_super_admin(current_author):
            current_member = _get_member_or_403(db=db, group_id=group_id, author_id=current_author.id)
            _assert_role_allowed(current_member, [AuthorGroupMemberRole.OWNER, AuthorGroupMemberRole.ADMIN])

        target_member = get_group_member(db=db, group_id=group_id, author_id=author_id)
        if not target_member:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group member not found")

        target_role = _to_role_value(target_member.role)
        requested_role = _to_role_value(request.role)
        actor_role = _resolve_actor_group_role(db, group_id=group_id, author=current_author)
        if target_role == AuthorGroupMemberRole.OWNER.value and actor_role != AuthorGroupMemberRole.OWNER.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot change the role of a group owner",
            )
        _assert_role_change_allowed(
            actor_role=actor_role,
            actor_author_id=current_author.id,
            target_author_id=author_id,
            target_role=target_role,
            requested_role=requested_role,
        )

        if target_role == AuthorGroupMemberRole.OWNER.value and requested_role != AuthorGroupMemberRole.OWNER.value:
            owner_count = get_owner_count(db=db, group_id=group_id)
            if owner_count <= 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one OWNER must always remain")

        set_group_member_role(db=db, member=target_member, role=request.role.value, updated_by=current_author.email)
        loaded = get_group_by_id(db=db, group_id=group_id)
        follower_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        joiner_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_detail(loaded, follower_count=follower_count, joiner_count=joiner_count, db=db)


def _assert_not_last_owner_removal(db, *, group_id: UUID, member: AuthorGroupMember) -> None:
    if _to_role_value(member.role) != "OWNER":
        return
    owner_count = get_owner_count(db=db, group_id=group_id)
    if owner_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one OWNER must remain. Transfer ownership or delete the group.",
        )


def _assert_admin_can_remove_target(
    current_member: AuthorGroupMember,
    target_member: AuthorGroupMember,
) -> None:
    current_role = _to_role_value(current_member.role)
    target_role = _to_role_value(target_member.role)
    if current_role == AuthorGroupMemberRole.ADMIN.value and target_role in (
        AuthorGroupMemberRole.OWNER.value,
        AuthorGroupMemberRole.ADMIN.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the group owner can remove a member with role OWNER or ADMIN",
        )
def transfer_group_ownership(
    token: str,
    group_id: UUID,
    new_owner_author_id: UUID,
) -> AuthorGroupDetailDTO:
    current_author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)

        current_member = get_group_member(db=db, group_id=group_id, author_id=current_author.id)
        if not current_member or _to_role_value(current_member.role) != AuthorGroupMemberRole.OWNER.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the group owner can transfer ownership",
            )

        if new_owner_author_id == current_author.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You are already the group owner",
            )

        new_owner_member = get_group_member(db=db, group_id=group_id, author_id=new_owner_author_id)
        if not new_owner_member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group member not found",
            )
        if _to_role_value(new_owner_member.role) == AuthorGroupMemberRole.OWNER.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected member is already the group owner",
            )

        set_group_member_role(
            db=db,
            member=current_member,
            role=AuthorGroupMemberRole.ADMIN.value,
            updated_by=current_author.email,
        )
        set_group_member_role(
            db=db,
            member=new_owner_member,
            role=AuthorGroupMemberRole.OWNER.value,
            updated_by=current_author.email,
        )

        loaded = get_group_by_id(db=db, group_id=group_id)
        follower_count = get_followers_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        joiner_count = get_joiners_count_map(db=db, group_ids=[group_id]).get(group_id, 0)
        return _group_to_detail(loaded, follower_count=follower_count, joiner_count=joiner_count, db=db)


def delete_group_member(token: str, group_id: UUID, author_id: UUID) -> None:
    current_author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)

        is_self_remove = author_id == current_author.id
        member = get_group_member(db=db, group_id=group_id, author_id=author_id)
        if not member:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group member not found")

        if is_self_remove:
            if not is_super_admin(current_author):
                _get_member_or_403(db=db, group_id=group_id, author_id=current_author.id)
            _assert_not_last_owner_removal(db, group_id=group_id, member=member)
        else:
            if not is_super_admin(current_author):
                current_member = _get_member_or_403(db=db, group_id=group_id, author_id=current_author.id)
                _assert_role_allowed(
                    current_member,
                    [AuthorGroupMemberRole.OWNER, AuthorGroupMemberRole.ADMIN],
                )
                _assert_admin_can_remove_target(current_member, member)
            _assert_not_last_owner_removal(db, group_id=group_id, member=member)

        remove_group_member(db=db, member=member)


def get_group_accumulations(
    group_id: UUID,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
):
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)

        rows, total, grand_total_count = get_group_mantra_accumulations(db=db, group_id=group_id, skip=skip, limit=limit)
        
        if not rows:
            return GroupAccumulationsResponse(
                group_id=group_id,
                mantras=[],
                total_count=0,
                total=0,
                skip=skip,
                limit=limit,
            )
        
        mantra_ids = [row.mantra_id for row in rows]
        mantras_map = get_mantras_by_ids(db=db, mantra_ids=mantra_ids)
        
        language_code = language.upper() if language else "EN"
        
        mantra_dtos = []
        for row in rows:
            mantra = mantras_map.get(row.mantra_id)
            mantra_title = None
            mantra_slug = None
            
            if mantra:
                metadata_entry = next(
                    (m for m in mantra.metadata_entries if m.language.value == language_code),
                    None
                )
                if not metadata_entry and mantra.metadata_entries:
                    metadata_entry = next(
                        (m for m in mantra.metadata_entries if m.language.value == "EN"),
                        mantra.metadata_entries[0]
                    )
                
                if metadata_entry:
                    mantra_title = metadata_entry.title
                    mantra_slug = f"mantra-{row.mantra_id}"
            
            mantra_dtos.append(
                GroupMantraAccumulationDTO(
                    mantra_id=row.mantra_id,
                    mantra_slug=mantra_slug,
                    mantra_title=mantra_title,
                    count=row.total_count,
                )
            )
        
        return GroupAccumulationsResponse(
            group_id=group_id,
            mantras=mantra_dtos,
            total_count=grand_total_count,
            total=total,
            skip=skip,
            limit=limit,
        )


def get_group_member_accumulations(
    group_id: UUID,
    accumulation_id: UUID,
    skip: int = 0,
    limit: int = 20,
) -> GroupMemberAccumulationsResponse:
    with SessionLocal() as db:
        group = get_group_by_id(db=db, group_id=group_id)
        if not group or not is_group_published(group):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)

        group_accumulator = get_group_accumulator_by_id(db=db, group_accumulator_id=accumulation_id)
        if not group_accumulator:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group accumulator not found")
        
        if group_accumulator.group_id != group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group accumulator does not belong to this group")
        
        rows, total = get_group_accumulator_member_contributions(
            db=db,
            group_accumulator_id=accumulation_id,
            skip=skip,
            limit=limit,
        )
        
        if not rows:
            return GroupMemberAccumulationsResponse(
                total_members=0,
                list=[],
                skip=skip,
                limit=limit,
            )
        
        user_ids = [row.user_id for row in rows]
        users_map = get_users_by_ids(db=db, user_ids=user_ids)
        
        member_dtos = []
        for row in rows:
            user = users_map.get(row.user_id)
            if user:
                fullname = f"{user.firstname} {user.lastname}".strip()
                if not fullname:
                    fullname = user.email
                
                member_dtos.append(
                    GroupMemberAccumulationDTO(
                        username=user.username,
                        fullname=fullname,
                        avatar_url=user.avatar_url,
                        count=row.total_count,
                    )
                )
        
        return GroupMemberAccumulationsResponse(
            total_members=total,
            list=member_dtos,
            skip=skip,
            limit=limit,
        )


def get_group_permission(token: str, group_id: UUID) -> GroupPermissionDTO:
    """Check CMS management permission for a group.

    Resolution strategy (fixes cross-domain subject confusion):
    1. User and Author accounts are independent tables whose ids can
       coincide, and their tokens carry no distinguishing claim. Whether a
       live User competes for a given id is decided by an exact-id lookup
       (get_user_by_id on the subject UUID) - never through validate_and_
       extract_user_details's own broader resolution rules, which also
       fall back to matching a phone/email claim for non-UUID subjects
       (Auth0-issued tokens). Collision detection here is id-only by
       construction, so it can never be satisfied "through" a claim - a
       stale or coincidentally-matching contact claim carries no weight in
       deciding whether a competing User exists at all.
    2. An id match against Author records is trusted outright whenever
       that exact-id lookup finds no live User - a contact claim that no
       longer matches the Author's current record is not treated as
       evidence of a different account in that case, since there is no
       other live account for the token to actually belong to; it just
       means the Author's profile changed after their token was minted
       (e.g. linking/changing a phone number does not force a new token to
       be issued, so a routine profile update must never turn into a false
       "unauthorized" for the same, rightful Author).
    3. Only when a live User *also* resolves to that exact same id (a
       genuine, currently-exploitable collision) do we require positive
       evidence before trusting the Author match: the token's own contact
       claims - "email" and "phone_number", each populated from the real
       account at mint time - must positively match the Author's own email
       or phone. Without that, the match is rejected and resolution falls
       back to the User, so a live colliding User's token can never be
       evaluated with an unrelated Author's group or super-admin
       permissions.
    4. Only when the subject does not resolve to a confirmed Author do we
       fall back to the User domain - reusing the exact-id User match when
       there is one, or validate_and_extract_user_details's broader rules
       otherwise (e.g. a non-UUID Auth0 subject).
    5. has_permission mirrors the OWNER/ADMIN "manage group" role set used
       elsewhere in this module (see _GROUP_SETTINGS_ROLES), with the same
       super-admin bypass those checks use - reviewer platform role is not
       a blocker here since none of the actual group-settings/member-
       management guards this endpoint represents check it (only content
       operations do). has_permission is a coarse "can manage this group"
       summary, not per-operation: several sub-actions (assigning/revoking
       ADMIN, removing an OWNER/ADMIN member, transferring ownership) are
       gated to the literal OWNER role only, with no ADMIN or super-admin
       bypass. Callers needing that precise distinction should check
       role == OWNER themselves - exactly how the Studio frontend derives
       its own owner-only affordances (e.g. canTransferOwnership) from the
       member's role rather than from a single coarse permission flag.
    """
    try:
        payload = validate_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    subject = payload.get("sub")
    try:
        subject_uuid = UUID(str(subject)) if subject is not None else None
    except (TypeError, ValueError):
        subject_uuid = None

    def _claim(name: str):
        value = payload.get(name)
        return value if isinstance(value, str) and value else None

    token_email = _claim("email")
    token_phone = _claim("phone_number")

    def _claim_confirms(token_value, record_value):
        """True/False when the claim is a definitive match/mismatch against
        the record, or None when there is no evidence either way."""
        if token_value is None or not record_value:
            return None
        return token_value == record_value

    with SessionLocal() as db:
        candidate_author = None
        if subject_uuid is not None:
            candidate_author = find_author_by_id(db=db, author_id=subject_uuid)

        # Exact-id collision check, independent of validate_and_extract_
        # user_details's own resolution rules (which fall back to phone/
        # email for non-UUID subjects such as Auth0-issued tokens). We only
        # want to know one thing here: is there a live Users row at this
        # precise id - never a claim-based match - so this check can never
        # be satisfied "through" a stale or coincidental contact claim.
        live_user_at_id = None
        if subject_uuid is not None:
            try:
                live_user_at_id = get_user_by_id(db=db, user_id=subject_uuid)
            except HTTPException:
                live_user_at_id = None

        author = None
        if candidate_author is not None:
            if live_user_at_id is None:
                # No live competing User for this id - trust the id match
                # unconditionally. A contact claim that no longer matches
                # the Author's current record is not evidence of a
                # different account here, since there is no other live
                # account for the token to actually belong to - it just
                # means the Author's profile changed after their token was
                # minted (linking/changing a phone number, for instance,
                # does not force a new token to be issued).
                author = candidate_author
            else:
                # A live User also resolves to this id: only trust the
                # Author when a contact claim positively identifies it.
                email_match = _claim_confirms(token_email, getattr(candidate_author, "email", None))
                phone_match = _claim_confirms(token_phone, getattr(candidate_author, "phone_number", None))
                if email_match or phone_match:
                    author = candidate_author

        user = None
        if author is None:
            if live_user_at_id is not None:
                user = live_user_at_id
            else:
                try:
                    user = validate_and_extract_user_details(token=token)
                except HTTPException:
                    user = None

        if author is None and user is None:
            # Resolve identity before touching the group so a token whose
            # account no longer exists (or never did) always gets 401,
            # instead of leaking whether group_id exists via 404-vs-401.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        group = get_group_by_id(db=db, group_id=group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=GROUP_NOT_FOUND)

        if author is None:
            return GroupPermissionDTO(
                group_id=group_id,
                has_permission=False,
                role=None,
                is_super_admin=False,
                author_id=None,
            )

        if not author.is_active:
            return GroupPermissionDTO(
                group_id=group_id,
                has_permission=False,
                role=None,
                is_super_admin=False,
                author_id=author.id,
            )

        role = get_member_role(db=db, group_id=group_id, author_id=author.id)
        author_is_super_admin = is_super_admin(author)
        has_permission = author_is_super_admin or role in _GROUP_SETTINGS_ROLES
        return GroupPermissionDTO(
            group_id=group_id,
            has_permission=has_permission,
            role=role,
            is_super_admin=author_is_super_admin,
            author_id=author.id,
        )
