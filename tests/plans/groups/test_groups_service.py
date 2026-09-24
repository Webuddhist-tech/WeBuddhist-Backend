from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.group_accumulator.group_accumulator_response_models import (
    GroupAccumulatorDTO,
    GroupAccumulatorsResponse,
)
from pecha_api.group_recitation_collection.response_models import (
    GroupRecitationCollectionDTO,
    GroupRecitationCollectionsResponse,
)
from pecha_api.plans.groups.groups_enums import (
    AuthorGroupInviteStatus,
    AuthorGroupJoinRequestStatus,
    AuthorGroupMemberRole,
    AuthorGroupStatus,
    AuthorGroupType,
)
from pecha_api.plans.groups.groups_response_models import (
    CreateAuthorGroupRequest,
    UpdateAuthorGroupStatusRequest,
    CreateGroupInviteRequest,
    CreateGroupJoinRequest,
    GroupMetadataInput,
    GroupPracticeType,
    GroupSeriesListItemDTO,
    GroupSocialLinkInput,
    ReplaceGroupSocialLinksRequest,
    ReplaceGroupTagsRequest,
    UpdateAuthorGroupRequest,
    UpdateGroupMemberRoleRequest,
)
from pecha_api.plans.series.series_response_models import SeriesPartnerDTO
from pecha_api.region_restrictions.region_restriction_enums import RestrictedItemType
from pecha_api.plans.groups.groups_service import (
    GROUP_IS_PRIVATE_USE_REQUEST,
    JOIN_REQUEST_NOT_FOUND,
    _approve_pending_join_requests_on_publish,
    approve_group_join_request,
    list_group_join_requests,
    reject_group_join_request,
    submit_group_join_request,
    GROUP_NOT_FOUND,
    _as_aware_utc,
    _assert_metadata_valid,
    _restricted_ids_for_timezone,
    _generate_group_asset_url,
    _get_member_or_403,
    _group_card_title,
    _group_to_detail,
    _is_series_enrolled_for_group_context,
    _series_to_dtos,
    _to_role_value,
    accept_group_invite_by_id,
    create_author_group,
    create_group_member_invite,
    delete_group_member,
    get_group_accumulations,
    get_group_member_accumulations,
    get_group_practices,
    get_group_practices_feed,
    list_group_invites,
    list_my_pending_group_invites,
    notify_pending_group_invites,
    reject_group_invite_by_id,
    follow_group,
    get_followed_group,
    get_joined_group,
    get_author_group_detail,
    get_cms_group_detail,
    list_cms_groups,
    list_group_members,
    list_followed_groups,
    list_joined_groups,
    update_group_status,
    list_public_groups,
    replace_group_social_links_by_id,
    replace_group_tags,
    revoke_group_invite,
    join_group,
    leave_group,
    unfollow_group,
    update_author_group,
    delete_author_group,
    transfer_group_ownership,
    update_group_member_role,
    OWNER_ROLE_NOT_ASSIGNABLE,
)
from pecha_api.plans.platform_enums import PlatformRole
from pecha_api.plans.plans_enums import LanguageCode, PlanStatus
from pecha_api.plans.plans_response_models import PlanDTO


def _session_local_context(mock_session_local):
    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db
    mock_session_local.return_value.__exit__.return_value = False
    return mock_db


def _make_author(
    author_id=None,
    email="author@example.org",
    *,
    platform_role: PlatformRole = PlatformRole.CREATOR,
    is_admin: bool = False,
    is_active: bool = True,
):
    author = MagicMock()
    author.id = author_id or uuid4()
    author.email = email
    author.platform_role = PlatformRole.SUPER_ADMIN if is_admin else platform_role
    author.first_name = None
    author.last_name = None
    author.is_active = is_active
    return author


def _make_group(
    is_public=True,
    slug="test-group",
    group_type=AuthorGroupType.PAGE,
    group_status=AuthorGroupStatus.PUBLISHED,
):
    # Published by default; pass group_status to cover the draft/hidden paths.
    group = MagicMock()
    group.id = uuid4()
    group.slug = slug
    group.group_type = group_type
    group.is_public = is_public
    group.status = group_status
    group.avatar_key = None
    group.banner_key = None
    group.metadata_entries = []
    group.members = []
    group.social_links = []
    group.tags = []
    group.plans = []
    group.series = []
    return group


def _metadata_input(title="Title", language=LanguageCode.EN):
    return GroupMetadataInput(title=title, description="Desc", language=language)


def test_generate_group_asset_url_returns_none_for_empty_key():
    assert _generate_group_asset_url(None) is None
    assert _generate_group_asset_url("") is None


def test_group_to_detail_includes_presigned_avatar_and_banner_urls():
    group = _make_group()
    group.avatar_key = "images/avatar.jpg"
    group.banner_key = "images/banner.jpg"
    with patch(
        "pecha_api.plans.groups.groups_service.generate_presigned_access_url",
        side_effect=lambda bucket_name, s3_key: f"https://signed.example/{s3_key}",
    ):
        detail = _group_to_detail(group)
    assert detail.avatar_key == "images/avatar.jpg"
    assert detail.banner_key == "images/banner.jpg"
    assert detail.avatar_url == "https://signed.example/images/avatar.jpg"
    assert detail.banner_url == "https://signed.example/images/banner.jpg"


def test_assert_metadata_valid_rejects_empty():
    with pytest.raises(HTTPException) as exc:
        _assert_metadata_valid([])
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_assert_metadata_valid_rejects_duplicate_language():
    with pytest.raises(HTTPException) as exc:
        _assert_metadata_valid(
            [
                _metadata_input(language=LanguageCode.EN),
                _metadata_input(title="Other", language=LanguageCode.EN),
            ]
        )
    assert "unique" in exc.value.detail.lower()


def test_assert_metadata_valid_rejects_missing_title():
    entry = _metadata_input()
    entry.title = ""
    with pytest.raises(HTTPException) as exc:
        _assert_metadata_valid([entry])
    assert "title" in exc.value.detail.lower()


def test_to_role_value_accepts_string():
    assert _to_role_value("OWNER") == "OWNER"


def test_get_member_or_403_raises_when_not_member():
    with patch("pecha_api.plans.groups.groups_service.get_group_member", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _get_member_or_403(db=MagicMock(), group_id=uuid4(), author_id=uuid4())
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_get_cms_group_detail_success():
    author = _make_author(is_admin=True)
    group = _make_group()
    meta = MagicMock()
    meta.id = uuid4()
    meta.title = "T"
    meta.description = "D"
    meta.language = "EN"
    group.metadata_entries = [meta]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group.id: 2},
    ):
        _session_local_context(mock_session)
        result = get_cms_group_detail(token="t", group_id=group.id)
    assert result.follower_count == 2


def test_update_author_group_success_as_admin():
    author = _make_author(is_admin=True)
    group = _make_group()
    meta = MagicMock()
    meta.id = uuid4()
    meta.title = "T"
    meta.description = "D"
    meta.language = "EN"
    group.metadata_entries = [meta]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.update_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group.id: 0},
    ):
        _session_local_context(mock_session)
        result = update_author_group(
            token="t",
            group_id=group.id,
            request=UpdateAuthorGroupRequest(is_public=False),
        )
    assert result.is_public is False


def test_accept_group_invite_not_pending():
    author = _make_author(email="a@b.com")
    invite = MagicMock()
    invite.target_email = "a@b.com"
    invite.status = AuthorGroupInviteStatus.REVOKED.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            accept_group_invite_by_id(token="t", invite_id=uuid4())
    assert "not pending" in exc.value.detail.lower()


def test_accept_group_invite_not_found():
    author = _make_author()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            accept_group_invite_by_id(token="t", invite_id=uuid4())
    assert exc.value.detail == "Invite not found"


def test_create_author_group_success():
    author = _make_author()
    request = CreateAuthorGroupRequest(
        slug="new-group",
        is_public=True,
        metadata=[_metadata_input()],
    )
    created = _make_group(slug="new-group")
    created.id = uuid4()
    meta = MagicMock()
    meta.id = uuid4()
    meta.title = "Title"
    meta.description = "Desc"
    meta.language = "EN"
    created.metadata_entries = [meta]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_slug",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group",
        return_value=created,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=created,
    ):
        _session_local_context(mock_session)
        result = create_author_group(token="t", request=request)

    assert result.slug == "new-group"


def test_create_author_group_slug_exists():
    author = _make_author()
    request = CreateAuthorGroupRequest(slug="taken", metadata=[_metadata_input()])

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_slug",
        return_value=_make_group(slug="taken"),
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            create_author_group(token="t", request=request)
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_get_author_group_detail_not_found():
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_author_group_detail(group_id=uuid4())
    assert exc.value.detail == GROUP_NOT_FOUND



def test_list_group_members_not_found():
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            list_group_members(group_id=uuid4(), skip=0, limit=20)
    assert exc.value.detail == GROUP_NOT_FOUND


def _make_joiner(username, email, firstname="Alice", lastname="Smith"):
    user = MagicMock()
    user.id = uuid4()
    user.email = email
    user.username = username
    user.firstname = firstname
    user.lastname = lastname
    user.avatar_url = f"images/profile_images/{username}.webp"
    return user


def test_list_group_members_returns_paginated_profiles():
    group = _make_group()
    user = _make_joiner("alice", "alice@example.org")
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_joiners_paginated",
        return_value=([user], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member_roles_by_emails",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service._user_avatar_url",
        return_value="https://example.com/avatar.webp",
    ):
        _session_local_context(mock_session)
        result = list_group_members(group_id=group.id, skip=0, limit=20)

    assert result.total_members == 1
    assert result.skip == 0
    assert result.limit == 20
    assert len(result.list) == 1
    assert result.list[0].user_id == user.id
    assert result.list[0].role == "MEMBER"
    assert result.list[0].username == "alice"
    assert result.list[0].fullname == "Alice Smith"
    assert result.list[0].avatar_url == "https://example.com/avatar.webp"


def test_list_group_members_returns_staff_role_for_matching_email():
    group = _make_group()
    admin_user = _make_joiner("alice", "alice@example.org")
    plain_user = _make_joiner("bob", "bob@example.org", firstname="Bob")
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_joiners_paginated",
        return_value=([admin_user, plain_user], 2),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member_roles_by_emails",
        return_value={"alice@example.org": "ADMIN"},
    ) as mock_roles, patch(
        "pecha_api.plans.groups.groups_service._user_avatar_url",
        return_value=None,
    ):
        _session_local_context(mock_session)
        result = list_group_members(group_id=group.id, skip=0, limit=20)

    assert mock_roles.call_args.kwargs["emails"] == ["alice@example.org", "bob@example.org"]
    assert [(m.user_id, m.role) for m in result.list] == [
        (admin_user.id, "ADMIN"),
        (plain_user.id, "MEMBER"),
    ]


def test_list_public_groups_defaults_to_community_type():
    group = _make_group(group_type=AuthorGroupType.COMMUNITY)
    group.metadata_entries = []
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        list_public_groups(skip=0, limit=10)

    assert mock_paginated.call_args.kwargs["group_type"] == AuthorGroupType.COMMUNITY


def test_list_public_groups_returns_paginated():
    group = _make_group()
    meta = MagicMock()
    meta.id = uuid4()
    meta.title = "T"
    meta.description = None
    meta.language = "EN"
    group.metadata_entries = [meta]
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group.id: 3},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={group.id: 2},
    ):
        _session_local_context(mock_session)
        result = list_public_groups(skip=0, limit=10, group_type=AuthorGroupType.COMMUNITY)

    assert result.total == 1
    assert result.groups[0].follower_count == 3
    assert result.groups[0].joiner_count == 2
    assert result.groups[0].group_type == AuthorGroupType.PAGE
    assert mock_paginated.call_args.kwargs["group_type"] == AuthorGroupType.COMMUNITY


def test_list_public_groups_without_token_does_not_exclude_joined_groups():
    group = _make_group(group_type=AuthorGroupType.COMMUNITY)
    group.metadata_entries = []
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        list_public_groups(skip=0, limit=10)

    assert mock_paginated.call_args.kwargs["exclude_group_ids"] is None


def test_list_public_groups_with_token_excludes_joined_groups():
    group = _make_group(group_type=AuthorGroupType.COMMUNITY)
    group.metadata_entries = []
    user_id = uuid4()
    joined_group_id = uuid4()
    user = MagicMock()
    user.id = user_id
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_ids_by_user",
        return_value=[joined_group_id],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        list_public_groups(skip=0, limit=10, token="valid-token")

    assert mock_paginated.call_args.kwargs["exclude_group_ids"] == [joined_group_id]


def test_list_public_groups_with_token_and_no_joined_groups_does_not_exclude():
    group = _make_group(group_type=AuthorGroupType.COMMUNITY)
    group.metadata_entries = []
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_ids_by_user",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        list_public_groups(skip=0, limit=10, token="valid-token")

    assert mock_paginated.call_args.kwargs["exclude_group_ids"] is None


def test_list_public_groups_with_invalid_token_does_not_exclude_joined_groups():
    group = _make_group(group_type=AuthorGroupType.COMMUNITY)
    group.metadata_entries = []
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        list_public_groups(skip=0, limit=10, token="invalid-token")

    assert mock_paginated.call_args.kwargs["exclude_group_ids"] is None


def test_list_public_groups_does_not_filter_by_language_and_falls_back_metadata():
    group = _make_group(group_type=AuthorGroupType.COMMUNITY)
    meta_en = MagicMock()
    meta_en.id = uuid4()
    meta_en.title = "English Community"
    meta_en.description = "EN desc"
    meta_en.sub_title = None
    meta_en.description_long = None
    meta_en.language = "EN"
    group.metadata_entries = [meta_en]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group.id: 0},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={group.id: 0},
    ):
        _session_local_context(mock_session)
        result = list_public_groups(
            skip=0,
            limit=10,
            language="bo",
            group_type=AuthorGroupType.COMMUNITY,
        )

    assert "language" not in mock_paginated.call_args.kwargs
    assert result.total == 1
    assert result.groups[0].metadata.title == "English Community"
    assert result.groups[0].metadata.language == "EN"


def test_list_public_groups_returns_page_type_with_language_fallback():
    group = _make_group(group_type=AuthorGroupType.PAGE)
    meta_en = MagicMock()
    meta_en.id = uuid4()
    meta_en.title = "English Author Group"
    meta_en.description = "EN desc"
    meta_en.sub_title = None
    meta_en.description_long = None
    meta_en.language = "EN"
    group.metadata_entries = [meta_en]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group.id: 2},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={group.id: 0},
    ):
        _session_local_context(mock_session)
        result = list_public_groups(
            skip=0,
            limit=10,
            language="bo",
            group_type=AuthorGroupType.PAGE,
        )

    assert "language" not in mock_paginated.call_args.kwargs
    assert mock_paginated.call_args.kwargs["group_type"] == AuthorGroupType.PAGE
    assert result.groups[0].metadata.title == "English Author Group"
    assert result.groups[0].metadata.language == "EN"


def test_list_public_groups_mixed_metadata_uses_selected_language_then_en_fallback():
    group_with_bo = _make_group(group_type=AuthorGroupType.COMMUNITY)
    meta_en = MagicMock()
    meta_en.id = uuid4()
    meta_en.title = "English Community"
    meta_en.description = None
    meta_en.sub_title = None
    meta_en.description_long = None
    meta_en.language = "EN"
    meta_bo = MagicMock()
    meta_bo.id = uuid4()
    meta_bo.title = "Tibetan Community"
    meta_bo.description = None
    meta_bo.sub_title = None
    meta_bo.description_long = None
    meta_bo.language = "BO"
    group_with_bo.metadata_entries = [meta_en, meta_bo]

    group_en_only = _make_group(group_type=AuthorGroupType.COMMUNITY)
    meta_en_only = MagicMock()
    meta_en_only.id = uuid4()
    meta_en_only.title = "English Only Community"
    meta_en_only.description = None
    meta_en_only.sub_title = None
    meta_en_only.description_long = None
    meta_en_only.language = "EN"
    group_en_only.metadata_entries = [meta_en_only]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group_with_bo, group_en_only], 2),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group_with_bo.id: 0, group_en_only.id: 0},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={group_with_bo.id: 0, group_en_only.id: 0},
    ):
        _session_local_context(mock_session)
        result = list_public_groups(
            skip=0,
            limit=10,
            language="bo",
            group_type=AuthorGroupType.COMMUNITY,
        )

    assert result.total == 2
    assert result.groups[0].metadata.title == "Tibetan Community"
    assert result.groups[0].metadata.language == "BO"
    assert result.groups[1].metadata.title == "English Only Community"
    assert result.groups[1].metadata.language == "EN"


def _make_series_with_metadata():
    meta_en = MagicMock()
    meta_en.id = uuid4()
    meta_en.title = "English Series"
    meta_en.description = None
    meta_en.language = LanguageCode.EN
    meta_bo = MagicMock()
    meta_bo.id = uuid4()
    meta_bo.title = "Tibetan Series"
    meta_bo.description = None
    meta_bo.language = LanguageCode.BO

    series = MagicMock()
    series.id = uuid4()
    series.metadata_entries = [meta_en, meta_bo]
    series.image = None
    series.author_id = uuid4()
    series.featured = False
    series.status = MagicMock(value="PUBLISHED")
    return series


def test_series_to_dtos_returns_empty_for_empty_series_list():
    mock_db = MagicMock()
    assert _series_to_dtos(db=mock_db, series_list=[], group_id=uuid4()) == []
    mock_db.assert_not_called()


def test_group_series_list_item_dto_excludes_series_partner_id():
    assert "series_partner_id" not in GroupSeriesListItemDTO.model_fields
    assert "is_group_enrolled" in GroupSeriesListItemDTO.model_fields
    assert "partner" in GroupSeriesListItemDTO.model_fields


def test_is_series_enrolled_for_group_context():
    partner_id = uuid4()
    assert _is_series_enrolled_for_group_context(
        partner_id, partner_id, is_enrolled_in_series=True
    )
    assert not _is_series_enrolled_for_group_context(
        partner_id, uuid4(), is_enrolled_in_series=True
    )
    assert _is_series_enrolled_for_group_context(
        None, None, is_enrolled_in_series=True
    ) is None
    assert not _is_series_enrolled_for_group_context(
        partner_id, None, is_enrolled_in_series=True
    )
    assert _is_series_enrolled_for_group_context(
        None, None, is_enrolled_in_series=False
    ) is None


def test_series_to_dtos_sets_partner_enrollment_for_authenticated_user():
    group_id = uuid4()
    series = _make_series_with_metadata()
    partner_id = uuid4()
    user_id = uuid4()
    mock_db = MagicMock()
    with patch(
        "pecha_api.plans.groups.groups_service.get_active_plan_count_map_by_series_ids",
        return_value={series.id: 2},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_enrolled_count_map_by_group_and_series_ids",
        return_value={series.id: 5},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_partner_id_map_for_group",
        return_value={series.id: partner_id},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_series_enrollment_partner_map",
        return_value={series.id: partner_id},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_plan_schedule_by_series_ids",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_partner_dtos_by_series_ids",
        return_value={
            series.id: SeriesPartnerDTO(
                group_name="Partner Group",
                group_image="https://example.com/avatar.png",
            )
        },
    ):
        dtos = _series_to_dtos(
            db=mock_db,
            series_list=[series],
            group_id=group_id,
            user_id=user_id,
        )

    assert dtos[0].is_group_enrolled is True
    assert dtos[0].enrolled_count == 5
    assert dtos[0].partner is not None
    assert dtos[0].partner.group_name == "Partner Group"


def test_series_to_dtos_partner_reflects_enrollment_partner_not_viewing_group():
    viewing_group_id = uuid4()
    enrolled_from_group_id = uuid4()
    series = _make_series_with_metadata()
    series_partner_row_id = uuid4()
    user_id = uuid4()
    mock_db = MagicMock()
    with patch(
        "pecha_api.plans.groups.groups_service.get_active_plan_count_map_by_series_ids",
        return_value={series.id: 1},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_enrolled_count_map_by_group_and_series_ids",
        return_value={series.id: 0},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_partner_id_map_for_group",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_series_enrollment_partner_map",
        return_value={series.id: series_partner_row_id},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_plan_schedule_by_series_ids",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_partner_dtos_by_series_ids",
        return_value={
            series.id: SeriesPartnerDTO(
                group_name="Enrolled From Group",
                group_image="https://example.com/enrolled-from.png",
            )
        },
    ):
        dtos = _series_to_dtos(
            db=mock_db,
            series_list=[series],
            group_id=viewing_group_id,
            user_id=user_id,
        )

    assert dtos[0].is_group_enrolled is False
    assert dtos[0].partner is not None
    assert dtos[0].partner.group_name == "Enrolled From Group"
    assert dtos[0].partner.group_image == "https://example.com/enrolled-from.png"


def test_series_to_dtos_is_not_enrolled_without_user():
    group_id = uuid4()
    series = _make_series_with_metadata()
    partner_id = uuid4()
    mock_db = MagicMock()
    with patch(
        "pecha_api.plans.groups.groups_service.get_active_plan_count_map_by_series_ids",
        return_value={series.id: 2},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_enrolled_count_map_by_group_and_series_ids",
        return_value={series.id: 5},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_partner_id_map_for_group",
        return_value={series.id: partner_id},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_series_enrollment_partner_map",
    ) as mock_enrollment_map, patch(
        "pecha_api.plans.groups.groups_service.get_series_plan_schedule_by_series_ids",
        return_value={},
    ):
        dtos = _series_to_dtos(
            db=mock_db,
            series_list=[series],
            group_id=group_id,
        )

    mock_enrollment_map.assert_not_called()
    assert dtos[0].is_group_enrolled is None
    assert dtos[0].partner is None


def test_series_to_dtos_filters_metadata_by_language():
    group_id = uuid4()
    series = _make_series_with_metadata()
    mock_db = MagicMock()
    with patch(
        "pecha_api.plans.groups.groups_service.get_active_plan_count_map_by_series_ids",
        return_value={series.id: 2},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_partner_id_map_for_group",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_plan_schedule_by_series_ids",
        return_value={},
    ):
        all_metadata = _series_to_dtos(db=mock_db, series_list=[series], group_id=group_id)
        bo_metadata = _series_to_dtos(db=mock_db, series_list=[series], group_id=group_id, language="bo")
        missing_metadata = _series_to_dtos(db=mock_db, series_list=[series], group_id=group_id, language="zh")

    assert len(all_metadata[0].metadata) == 2
    assert bo_metadata[0].metadata.title == "Tibetan Series"
    assert bo_metadata[0].metadata.language == "BO"
    assert bo_metadata[0].plan_count == 2
    # No metadata for the requested language falls back to English.
    assert missing_metadata[0].metadata.title == "English Series"
    assert missing_metadata[0].metadata.language == "EN"


def test_series_to_dtos_includes_schedule_from_plans():
    from pecha_api.plans.plans_enums import PlanStatus
    from pecha_api.plans.series.series_repository import SeriesPlanScheduleRow

    group_id = uuid4()
    series = _make_series_with_metadata()
    series_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    last_plan_start = datetime(2026, 6, 10, tzinfo=timezone.utc)
    mock_db = MagicMock()
    schedule_rows = {
        series.id: [
            SeriesPlanScheduleRow(
                series_id=series.id,
                status=PlanStatus.PUBLISHED,
                language=LanguageCode.BO,
                display_order=0,
                start_date=series_start,
                deleted_at=None,
                total_days=3,
            ),
            SeriesPlanScheduleRow(
                series_id=series.id,
                status=PlanStatus.PUBLISHED,
                language=LanguageCode.BO,
                display_order=1,
                start_date=last_plan_start,
                deleted_at=None,
                total_days=2,
            ),
        ]
    }
    with patch(
        "pecha_api.plans.groups.groups_service.get_active_plan_count_map_by_series_ids",
        return_value={series.id: 2},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_enrolled_count_map_by_group_and_series_ids",
        return_value={series.id: 0},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_partner_id_map_for_group",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_plan_schedule_by_series_ids",
        return_value=schedule_rows,
    ):
        dtos = _series_to_dtos(
            db=mock_db,
            series_list=[series],
            group_id=group_id,
            language="bo",
            published_only=True,
        )

    assert dtos[0].start_date == series_start
    assert dtos[0].end_date == datetime(2026, 6, 11, tzinfo=timezone.utc)
    assert dtos[0].total_days == 5


def test_group_detail_series_metadata_filtered_by_language():
    group = _make_group()
    series = _make_series_with_metadata()

    mock_db = MagicMock()
    with patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id",
        return_value=[series],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_plans_by_group_id",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_active_plan_count_map_by_series_ids",
        return_value={series.id: 0},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_partner_id_map_for_group",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_plan_schedule_by_series_ids",
        return_value={},
    ):
        detail_all = _group_to_detail(group, db=mock_db)
        detail_bo = _group_to_detail(group, db=mock_db, language="bo")

    assert len(detail_all.series[0].metadata) == 2
    assert detail_bo.series[0].metadata.title == "Tibetan Series"
    assert detail_bo.series[0].metadata.language == "BO"


def test_get_author_group_detail_series_metadata_filtered_by_language():
    group = _make_group()
    series = _make_series_with_metadata()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group.id: 1},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id",
        return_value=[series],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_plans_by_group_id",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_active_plan_count_map_by_series_ids",
        return_value={series.id: 0},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_plan_schedule_by_series_ids",
        return_value={},
    ):
        _session_local_context(mock_session)
        result = get_author_group_detail(group_id=group.id, language="bo")

    assert result.series[0].metadata.title == "Tibetan Series"
    assert result.series[0].metadata.language == "BO"


def test_get_cms_group_detail_series_metadata_filtered_by_language():
    author = _make_author(is_admin=True)
    group = _make_group()
    series = _make_series_with_metadata()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group.id: 2},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id",
        return_value=[series],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_plans_by_group_id",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_active_plan_count_map_by_series_ids",
        return_value={series.id: 0},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_plan_schedule_by_series_ids",
        return_value={},
    ):
        _session_local_context(mock_session)
        result = get_cms_group_detail(token="t", group_id=group.id, language="bo")

    assert result.series[0].metadata.title == "Tibetan Series"
    assert result.series[0].metadata.language == "BO"


def test_group_summary_metadata_filtered_by_language():
    from pecha_api.plans.groups.groups_service import _group_to_summary

    group = _make_group()
    meta_en = MagicMock()
    meta_en.id = uuid4()
    meta_en.title = "English Group"
    meta_en.description = "EN desc"
    meta_en.language = "EN"
    meta_bo = MagicMock()
    meta_bo.id = uuid4()
    meta_bo.title = "Tibetan Group"
    meta_bo.description = "BO desc"
    meta_bo.language = "BO"
    group.metadata_entries = [meta_en, meta_bo]
    group.tags = []
    group.members = []

    summary_all = _group_to_summary(group)
    summary_bo = _group_to_summary(group, language="bo")

    assert len(summary_all.metadata) == 2
    assert summary_bo.metadata.title == "Tibetan Group"
    assert summary_bo.metadata.language == "BO"


def test_group_summary_metadata_falls_back_to_en_when_language_missing():
    from pecha_api.plans.groups.groups_service import _group_to_summary

    group = _make_group()
    meta_en = MagicMock()
    meta_en.id = uuid4()
    meta_en.title = "English Group"
    meta_en.description = "EN desc"
    meta_en.language = "EN"
    group.metadata_entries = [meta_en]
    group.tags = []
    group.members = []

    # Requesting 'bo' which is absent -> falls back to EN, never blank.
    summary_bo = _group_to_summary(group, language="bo")

    assert summary_bo.metadata is not None
    assert summary_bo.metadata.title == "English Group"
    assert summary_bo.metadata.language == "EN"


def test_group_detail_metadata_falls_back_to_en_when_language_missing():
    from pecha_api.plans.groups.groups_service import _group_to_detail

    group = _make_group()
    meta_en = MagicMock()
    meta_en.id = uuid4()
    meta_en.title = "English Group"
    meta_en.description = "EN desc"
    meta_en.language = "EN"
    group.metadata_entries = [meta_en]
    group.tags = []
    group.members = []
    group.social_links = []

    # db=None skips series/plans loading; we only assert metadata fallback here.
    detail_bo = _group_to_detail(group, language="bo")

    assert detail_bo.metadata is not None
    assert detail_bo.metadata.title == "English Group"
    assert detail_bo.metadata.language == "EN"


def test_list_cms_groups_scopes_to_member_groups_for_non_admin():
    author = _make_author(is_admin=False)
    group = _make_group()
    membership = MagicMock()
    membership.group_id = group.id

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [membership]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_roles_map",
        return_value={group.id: "OWNER"},
    ):
        mock_session.return_value.__enter__.return_value = mock_db
        mock_session.return_value.__exit__.return_value = False
        result = list_cms_groups(token="t", skip=0, limit=10)

    assert mock_paginated.call_args.kwargs["group_ids"] == [group.id]
    assert result.groups[0].my_role == AuthorGroupMemberRole.OWNER


def test_list_cms_groups_includes_my_role_from_batch_lookup():
    author = _make_author(is_admin=True)
    group = _make_group()

    mock_db = MagicMock()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_roles_map",
        return_value={group.id: "ADMIN"},
    ) as mock_roles:
        mock_session.return_value.__enter__.return_value = mock_db
        mock_session.return_value.__exit__.return_value = False
        result = list_cms_groups(token="t", skip=0, limit=10)

    mock_roles.assert_called_once()
    assert result.groups[0].my_role == AuthorGroupMemberRole.ADMIN


def test_follow_group_requires_public_group():
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            follow_group(token="t", group_id=uuid4())
    assert exc.value.detail == GROUP_NOT_FOUND


def test_follow_group_success():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=True)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_follow",
    ) as mock_follow:
        _session_local_context(mock_session)
        follow_group(token="t", group_id=group.id)
    mock_follow.assert_called_once()


def test_unfollow_group_calls_repository():
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.remove_group_follow",
    ) as mock_unfollow, patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group",
        return_value=False,
    ):
        _session_local_context(mock_session)
        unfollow_group(token="t", group_id=uuid4())
    mock_unfollow.assert_called_once()


def test_unfollow_group_drops_chat_room_membership_when_not_joined():
    user = MagicMock()
    user.id = uuid4()
    group_id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.remove_group_follow",
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.leave_group_chat_room",
    ) as mock_leave_chat_room:
        mock_db = _session_local_context(mock_session)
        unfollow_group(token="t", group_id=group_id)
    mock_leave_chat_room.assert_called_once_with(db=mock_db, group_id=group_id, user_id=user.id)


def test_unfollow_group_keeps_chat_room_membership_when_still_joined():
    """Chat access is granted to joiners OR followers, so unfollowing a group
    the user is still a joiner of must not kick them out of its chat room."""
    user = MagicMock()
    user.id = uuid4()
    group_id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.remove_group_follow",
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group",
        return_value=True,
    ), patch(
        "pecha_api.plans.groups.groups_service.leave_group_chat_room",
    ) as mock_leave_chat_room:
        mock_db = _session_local_context(mock_session)
        unfollow_group(token="t", group_id=group_id)
    mock_leave_chat_room.assert_not_called()


def test_list_followed_groups():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_following_group_ids_by_user",
        return_value=[group.id],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        result = list_followed_groups(token="t", skip=0, limit=20)
    assert result.total == 1


def test_get_followed_group_returns_group_when_following():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group()
    meta = MagicMock()
    meta.id = uuid4()
    meta.title = "Followed Group"
    meta.description = None
    meta.language = "EN"
    group.metadata_entries = [meta]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_following_group",
        return_value=True,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={group.id: 5},
    ):
        _session_local_context(mock_session)
        result = get_followed_group(token="t", group_id=group.id)

    assert result.id == group.id
    assert result.follower_count == 5


def test_get_followed_group_returns_404_when_not_following():
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_following_group",
        return_value=False,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_followed_group(token="t", group_id=uuid4())
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


def test_get_followed_group_returns_404_when_group_missing():
    user = MagicMock()
    user.id = uuid4()
    group_id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_following_group",
        return_value=True,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_followed_group(token="t", group_id=group_id)
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


def test_join_group_requires_public_group():
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            join_group(token="t", group_id=uuid4())
    assert exc.value.detail == GROUP_NOT_FOUND


def test_follow_group_rejects_community_type():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=True, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            follow_group(token="t", group_id=group.id)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_join_group_rejects_page_type():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=True, group_type=AuthorGroupType.PAGE)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            join_group(token="t", group_id=group.id)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_join_group_success():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=True, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_join",
    ) as mock_join:
        _session_local_context(mock_session)
        join_group(token="t", group_id=group.id)
    mock_join.assert_called_once()


def test_leave_group_calls_repository():
    user = MagicMock()
    user.id = uuid4()
    group_id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.remove_group_accumulator_joins_for_group",
    ) as mock_remove_accumulator_joins, patch(
        "pecha_api.plans.groups.groups_service.leave_group_membership",
    ) as mock_leave_membership, patch(
        "pecha_api.plans.groups.groups_service.is_user_following_group",
        return_value=False,
    ):
        mock_db = _session_local_context(mock_session)
        leave_group(token="t", group_id=group_id)
    mock_remove_accumulator_joins.assert_called_once_with(
        db=mock_db,
        user_id=user.id,
        group_id=group_id,
    )
    mock_leave_membership.assert_called_once_with(
        db=mock_db,
        user_id=user.id,
        group_id=group_id,
    )


def test_leave_group_drops_chat_room_membership_when_not_following():
    user = MagicMock()
    user.id = uuid4()
    group_id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.remove_group_accumulator_joins_for_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.leave_group_membership",
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_following_group",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.leave_group_chat_room",
    ) as mock_leave_chat_room:
        mock_db = _session_local_context(mock_session)
        leave_group(token="t", group_id=group_id)
    mock_leave_chat_room.assert_called_once_with(db=mock_db, group_id=group_id, user_id=user.id)


def test_leave_group_keeps_chat_room_membership_when_still_following():
    """Chat access is granted to joiners OR followers, so leaving a group the
    user still follows must not kick them out of its chat room."""
    user = MagicMock()
    user.id = uuid4()
    group_id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.remove_group_accumulator_joins_for_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.leave_group_membership",
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_following_group",
        return_value=True,
    ), patch(
        "pecha_api.plans.groups.groups_service.leave_group_chat_room",
    ) as mock_leave_chat_room:
        mock_db = _session_local_context(mock_session)
        leave_group(token="t", group_id=group_id)
    mock_leave_chat_room.assert_not_called()


def test_list_joined_groups():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_ids_by_user",
        return_value=[group.id],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        result = list_joined_groups(token="t", skip=0, limit=20)
    assert result.total == 1


def test_get_joined_group_returns_group_when_joined():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group()
    meta = MagicMock()
    meta.id = uuid4()
    meta.title = "Joined Group"
    meta.sub_title = None
    meta.description = None
    meta.language = "en"
    group.metadata_entries = [meta]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group",
        return_value=True,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={group.id: 3},
    ):
        _session_local_context(mock_session)
        result = get_joined_group(token="t", group_id=group.id)

    assert result.id == group.id
    assert result.joiner_count == 3


def test_get_joined_group_returns_404_when_not_joined():
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group",
        return_value=False,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_joined_group(token="t", group_id=uuid4())
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


def test_create_group_member_invite_creates_notification():
    author = _make_author()
    group = _make_group()
    target_author = MagicMock()
    target_author.id = uuid4()
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = group.id
    invite.target_email = "invitee@example.org"
    invite.role = AuthorGroupMemberRole.AUTHOR
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.created_at = datetime.now(timezone.utc)
    invite.created_by = author.email
    invite.accepted_at = None
    invite.rejected_at = None
    invite.revoked_at = None

    notification = MagicMock()
    notification.id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=lambda db, group_id, author_id: (
            MagicMock(role=AuthorGroupMemberRole.OWNER) if author_id == author.id else None
        ),
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=target_author,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_invite",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_invite",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_notification_record",
        return_value=notification,
    ), patch(
        "pecha_api.plans.groups.groups_service.send_group_invitation_email",
    ):
        _session_local_context(mock_session)
        result = create_group_member_invite(
            token="t",
            group_id=group.id,
            request=CreateGroupInviteRequest(
                target_email="invitee@example.org",
                role=AuthorGroupMemberRole.AUTHOR,
            ),
        )
    assert result.invite.target_email == "invitee@example.org"
    assert result.notification_id == notification.id


def test_create_group_member_invite_blocks_existing_member():
    author = _make_author()
    group = _make_group()
    target_author = MagicMock()
    target_author.id = uuid4()

    def _get_member(db, group_id, author_id):
        if author_id == author.id:
            return MagicMock(role=AuthorGroupMemberRole.OWNER)
        if author_id == target_author.id:
            return MagicMock(role=AuthorGroupMemberRole.AUTHOR)
        return None

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=_get_member,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=target_author,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            create_group_member_invite(
                token="t",
                group_id=group.id,
                request=CreateGroupInviteRequest(
                    target_email="invitee@example.org",
                    role=AuthorGroupMemberRole.AUTHOR,
                ),
            )
    assert "already a member" in exc.value.detail.lower()


def test_create_group_member_invite_cannot_invite_as_owner():
    author = _make_author()
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=AuthorGroupMemberRole.OWNER),
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            create_group_member_invite(
                token="t",
                group_id=group.id,
                request=CreateGroupInviteRequest(
                    target_email="invitee@example.org",
                    role=AuthorGroupMemberRole.OWNER,
                ),
            )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.value.detail == OWNER_ROLE_NOT_ASSIGNABLE


def test_create_group_member_invite_admin_cannot_invite_as_admin():
    author = _make_author()
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=AuthorGroupMemberRole.ADMIN),
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            create_group_member_invite(
                token="t",
                group_id=group.id,
                request=CreateGroupInviteRequest(
                    target_email="invitee@example.org",
                    role=AuthorGroupMemberRole.ADMIN,
                ),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_update_group_member_role_admin_cannot_assign_admin_to_other():
    author = _make_author()
    group = _make_group()
    target_id = uuid4()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.ADMIN
    target = MagicMock()
    target.role = AuthorGroupMemberRole.AUTHOR

    def _get_member(db, group_id, author_id):
        if author_id == author.id:
            return current
        if author_id == target_id:
            return target
        return None

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=_get_member,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            update_group_member_role(
                token="t",
                group_id=group.id,
                author_id=target_id,
                request=UpdateGroupMemberRoleRequest(role=AuthorGroupMemberRole.ADMIN),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_create_group_member_invite_blocks_pending_invite():
    author = _make_author()
    group = _make_group()
    target_author = MagicMock()
    target_author.id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=lambda db, group_id, author_id: (
            MagicMock(role=AuthorGroupMemberRole.OWNER) if author_id == author.id else None
        ),
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=target_author,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_invite",
        return_value=True,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            create_group_member_invite(
                token="t",
                group_id=group.id,
                request=CreateGroupInviteRequest(
                    target_email="invitee@example.org",
                    role=AuthorGroupMemberRole.AUTHOR,
                ),
            )
    assert "pending invitation" in exc.value.detail.lower()


def test_accept_group_invite_email_mismatch():
    author = _make_author(email="other@example.org")
    invite = MagicMock()
    invite.target_email = "invitee@example.org"
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            accept_group_invite_by_id(token="t", invite_id=uuid4())
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_accept_group_invite_expired():
    author = _make_author(email="invitee@example.org")
    invite = MagicMock()
    invite.target_email = "invitee@example.org"
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            accept_group_invite_by_id(token="t", invite_id=uuid4())
    assert "expired" in exc.value.detail.lower()


def test_accept_group_invite_success_adds_member():
    author = _make_author(email="invitee@example.org")
    group = _make_group()
    invite = MagicMock()
    invite.target_email = "invitee@example.org"
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.role = AuthorGroupMemberRole.AUTHOR
    invite.group_id = group.id
    invite.id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.add_group_member",
    ) as mock_add, patch(
        "pecha_api.plans.groups.groups_service.save_invite",
    ), patch(
        "pecha_api.plans.groups.groups_service._mark_invite_notification_read",
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        accept_group_invite_by_id(token="t", invite_id=invite.id)
    mock_add.assert_called_once()


def test_update_group_member_role_cannot_promote_to_owner():
    author = _make_author()
    group = _make_group()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.ADMIN
    target = MagicMock()
    target.role = AuthorGroupMemberRole.ADMIN

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=lambda db, group_id, author_id: target if author_id == author.id else current,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            update_group_member_role(
                token="t",
                group_id=group.id,
                author_id=author.id,
                request=UpdateGroupMemberRoleRequest(role=AuthorGroupMemberRole.OWNER),
            )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.value.detail == OWNER_ROLE_NOT_ASSIGNABLE


def test_update_group_member_role_blocks_last_owner_demotion():
    author = _make_author()
    group = _make_group()
    target_id = uuid4()
    target = MagicMock()
    target.role = AuthorGroupMemberRole.OWNER
    current = MagicMock()
    current.role = AuthorGroupMemberRole.OWNER

    def _get_member(db, group_id, author_id):
        if author_id == author.id:
            return current
        if author_id == target_id:
            return target
        return None

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=_get_member,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_owner_count",
        return_value=1,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            update_group_member_role(
                token="t",
                group_id=group.id,
                author_id=target_id,
                request=UpdateGroupMemberRoleRequest(role=AuthorGroupMemberRole.ADMIN),
            )
    assert "OWNER" in exc.value.detail


def test_delete_group_member_blocks_last_owner_removal():
    author = _make_author(is_admin=True)
    group = _make_group()
    target = MagicMock()
    target.role = AuthorGroupMemberRole.OWNER

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=target,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_owner_count",
        return_value=1,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            delete_group_member(token="t", group_id=group.id, author_id=uuid4())
    assert "owner" in exc.value.detail.lower()


def test_delete_group_member_self_remove_as_author():
    author = _make_author()
    group = _make_group()
    member = MagicMock()
    member.role = AuthorGroupMemberRole.AUTHOR

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=member,
    ), patch(
        "pecha_api.plans.groups.groups_service.remove_group_member",
    ) as mock_remove:
        _session_local_context(mock_session)
        delete_group_member(token="t", group_id=group.id, author_id=author.id)
    mock_remove.assert_called_once()


def test_delete_group_member_self_remove_last_owner_blocked():
    author = _make_author()
    group = _make_group()
    member = MagicMock()
    member.role = AuthorGroupMemberRole.OWNER

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=member,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_owner_count",
        return_value=1,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            delete_group_member(token="t", group_id=group.id, author_id=author.id)
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_delete_group_member_admin_cannot_remove_owner():
    author = _make_author()
    group = _make_group()
    target_id = uuid4()
    target = MagicMock()
    target.role = AuthorGroupMemberRole.OWNER
    current = MagicMock()
    current.role = AuthorGroupMemberRole.ADMIN

    def _get_member(db, group_id, author_id):
        if author_id == target_id:
            return target
        if author_id == author.id:
            return current
        return None

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=_get_member,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            delete_group_member(token="t", group_id=group.id, author_id=target_id)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_replace_group_tags_invalid_tag_ids():
    author = _make_author()
    group = _make_group()
    tag_id = uuid4()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.OWNER

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=current,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_tags_by_ids",
        return_value=[],
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            replace_group_tags(
                token="t",
                group_id=group.id,
                request=ReplaceGroupTagsRequest(tag_ids=[tag_id]),
            )
    assert "tags" in exc.value.detail.lower()


def test_update_author_group_forbidden_for_viewer():
    author = _make_author()
    group = _make_group()
    viewer = MagicMock()
    viewer.role = AuthorGroupMemberRole.VIEWER

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=viewer,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            update_author_group(
                token="t",
                group_id=group.id,
                request=UpdateAuthorGroupRequest(slug="updated"),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_delete_author_group_success_as_owner():
    author = _make_author()
    group = _make_group()
    owner = MagicMock()
    owner.role = AuthorGroupMemberRole.OWNER

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=owner,
    ), patch(
        "pecha_api.plans.groups.groups_service.update_group",
    ) as mock_update:
        _session_local_context(mock_session)
        delete_author_group(token="t", group_id=group.id)

    assert group.deleted_at is not None
    assert group.deleted_by == author.email
    mock_update.assert_called_once()


def test_delete_author_group_forbidden_for_admin_member():
    author = _make_author()
    group = _make_group()
    admin = MagicMock()
    admin.role = AuthorGroupMemberRole.ADMIN

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=admin,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            delete_author_group(token="t", group_id=group.id)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_delete_author_group_not_found():
    author = _make_author()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            delete_author_group(token="t", group_id=uuid4())
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


def test_revoke_group_invite_not_found():
    author = _make_author()
    group = _make_group()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.ADMIN

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=current,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            revoke_group_invite(token="t", group_id=group.id, invite_id=uuid4())
    assert exc.value.detail == "Invite not found"


def test_replace_group_social_links_by_id_delegates_to_repository():
    author = _make_author()
    group = _make_group()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.ADMIN
    loaded = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        side_effect=[group, loaded],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=current,
    ), patch(
        "pecha_api.plans.groups.groups_service.replace_group_social_links",
    ) as mock_links, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        replace_group_social_links_by_id(
            token="t",
            group_id=group.id,
            request=ReplaceGroupSocialLinksRequest(
                social_links=[GroupSocialLinkInput(platform="twitter", url="https://x.com/g")]
            ),
        )
    mock_links.assert_called_once()


def test_reject_group_invite_by_id_success():
    author = _make_author(email="invitee@example.org")
    invite = MagicMock()
    invite.target_email = "invitee@example.org"
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.id = uuid4()
    invite.group_id = uuid4()
    invite.role = AuthorGroupMemberRole.AUTHOR
    invite.group = None
    invite.created_at = datetime.now(timezone.utc)
    invite.created_by = "owner@example.org"
    invite.accepted_at = None
    invite.rejected_at = None
    invite.revoked_at = None

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.save_invite",
    ), patch(
        "pecha_api.plans.groups.groups_service._mark_invite_notification_read",
    ):
        _session_local_context(mock_session)
        result = reject_group_invite_by_id(token="t", invite_id=invite.id)
    assert result.status == AuthorGroupInviteStatus.REJECTED


def test_list_my_pending_group_invites():
    author = _make_author(email="invitee@example.org")
    invite = MagicMock()
    invite.target_email = "invitee@example.org"
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.id = uuid4()
    invite.group_id = uuid4()
    invite.role = AuthorGroupMemberRole.AUTHOR.value
    invite.group = MagicMock()
    invite.group.metadata_entries = []
    invite.accepted_at = None
    invite.rejected_at = None
    invite.revoked_at = None
    invite.created_at = datetime.now(timezone.utc)
    invite.created_by = "owner@example.org"

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_pending_invites_by_email",
        return_value=[invite],
    ):
        _session_local_context(mock_session)
        result = list_my_pending_group_invites(token="t")
    assert result.total == 1


def test_list_group_invites_as_admin_member():
    author = _make_author()
    group = _make_group()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.ADMIN
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = group.id
    invite.target_email = "invitee@example.org"
    invite.role = AuthorGroupMemberRole.AUTHOR.value
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.accepted_at = None
    invite.rejected_at = None
    invite.revoked_at = None
    invite.created_at = datetime.now(timezone.utc)
    invite.created_by = author.email
    invite.group = group
    group.metadata_entries = []

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=current,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_invites_by_group",
        return_value=[invite],
    ):
        _session_local_context(mock_session)
        result = list_group_invites(token="t", group_id=group.id, status_filter=None)
    assert result.total == 1


def test_revoke_group_invite_success():
    author = _make_author()
    group = _make_group()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.OWNER
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = group.id
    invite.role = AuthorGroupMemberRole.AUTHOR.value
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.target_email = "invitee@example.org"
    target_author = MagicMock()
    target_author.id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=current,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.revoke_invite",
    ) as mock_revoke, patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=target_author,
    ), patch(
        "pecha_api.plans.groups.groups_service._mark_invite_notification_read",
    ):
        _session_local_context(mock_session)
        revoke_group_invite(token="t", group_id=group.id, invite_id=invite.id)
    mock_revoke.assert_called_once()


def test_create_group_member_invite_builds_notification_with_group_title():
    author = _make_author()
    author.first_name = "Jane"
    author.last_name = "Doe"
    group = _make_group()
    metadata = MagicMock()
    metadata.language = LanguageCode.EN
    metadata.title = "English Group"
    loaded_group = _make_group()
    loaded_group.metadata_entries = [metadata]
    target_author = MagicMock()
    target_author.id = uuid4()
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = group.id
    invite.target_email = "invitee@example.org"
    invite.role = AuthorGroupMemberRole.AUTHOR
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.created_at = datetime.now(timezone.utc)
    invite.created_by = author.email
    invite.accepted_at = None
    invite.rejected_at = None
    invite.revoked_at = None
    notification = MagicMock()
    notification.id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        side_effect=[group, loaded_group],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=lambda db, group_id, author_id: (
            MagicMock(role=AuthorGroupMemberRole.OWNER)
            if author_id == author.id
            else None
        ),
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=target_author,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_invite",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_invite",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_notification_record",
        return_value=notification,
    ) as mock_notify, patch(
        "pecha_api.plans.groups.groups_service.send_group_invitation_email",
    ):
        _session_local_context(mock_session)
        create_group_member_invite(
            token="t",
            group_id=group.id,
            request=CreateGroupInviteRequest(
                target_email="invitee@example.org",
                role=AuthorGroupMemberRole.AUTHOR,
            ),
        )
    assert mock_notify.call_args.kwargs["title"] == "Invitation to join English Group"
    assert "Jane Doe" in mock_notify.call_args.kwargs["description"]


def test_create_group_member_invite_requires_target_email():
    author = _make_author()
    group = _make_group()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=AuthorGroupMemberRole.OWNER),
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            create_group_member_invite(
                token="t",
                group_id=group.id,
                request=CreateGroupInviteRequest(target_email="   ", role=AuthorGroupMemberRole.AUTHOR),
            )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_create_group_member_invite_unknown_target_email_still_invites():
    """An email with no Author account yet must still succeed: the invite is
    created and the invitation email is sent, but no in-app notification can
    be created (there's no author id to attach it to) — notification_id is
    None. See notify_pending_group_invites for the notification backfill
    that runs once this person registers and verifies."""
    author = _make_author()
    group = _make_group()
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = group.id
    invite.target_email = "missing@example.org"
    invite.role = AuthorGroupMemberRole.AUTHOR
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.created_at = datetime.now(timezone.utc)
    invite.created_by = author.email
    invite.accepted_at = None
    invite.rejected_at = None
    invite.revoked_at = None

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=AuthorGroupMemberRole.OWNER),
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_invite",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_invite",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_notification_record",
    ) as mock_create_notification, patch(
        "pecha_api.plans.groups.groups_service.send_group_invitation_email",
    ) as mock_send_email:
        _session_local_context(mock_session)
        result = create_group_member_invite(
            token="t",
            group_id=group.id,
            request=CreateGroupInviteRequest(
                target_email="missing@example.org",
                role=AuthorGroupMemberRole.AUTHOR,
            ),
        )
    assert result.invite.target_email == "missing@example.org"
    assert result.notification_id is None
    mock_create_notification.assert_not_called()
    mock_send_email.assert_called_once()


def test_create_group_member_invite_unknown_target_email_uses_non_raising_lookup():
    """Regression guard: the author-lookup used for target_email resolution
    must be find_author_by_email (returns None on no match), not
    get_author_by_email (raises HTTPException 404 "Author not found" on no
    match). Exercises the real find_author_by_email against a db mock that
    returns no row, instead of mocking the lookup function itself, so a
    future accidental revert to get_author_by_email is caught here rather
    than surfacing as a raw 404 in production."""
    author = _make_author()
    group = _make_group()
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = group.id
    invite.target_email = "missing@example.org"
    invite.role = AuthorGroupMemberRole.AUTHOR
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.created_at = datetime.now(timezone.utc)
    invite.created_by = author.email
    invite.accepted_at = None
    invite.rejected_at = None
    invite.revoked_at = None

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=AuthorGroupMemberRole.OWNER),
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_invite",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_invite",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.send_group_invitation_email",
    ):
        mock_db = _session_local_context(mock_session)
        # No mocking of find_author_by_email: the real repository function
        # runs against this db mock's query chain, which yields no row.
        mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = None

        result = create_group_member_invite(
            token="t",
            group_id=group.id,
            request=CreateGroupInviteRequest(
                target_email="missing@example.org",
                role=AuthorGroupMemberRole.AUTHOR,
            ),
        )
    assert result.invite.target_email == "missing@example.org"
    assert result.notification_id is None


def _make_invite_for_email(email, group_name="Test Group", created_by="owner@example.org"):
    invite = MagicMock()
    invite.id = uuid4()
    invite.target_email = email
    invite.created_by = created_by
    invite.group = MagicMock()
    invite.group.metadata_entries = [MagicMock(language="EN", title=group_name)]
    return invite


def test_notify_pending_group_invites_creates_one_notification_per_invite():
    author = _make_author(email="invitee@example.org")
    invites = [_make_invite_for_email(author.email), _make_invite_for_email(author.email)]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.list_pending_invites_by_email",
        return_value=invites,
    ), patch(
        "pecha_api.plans.groups.groups_service.notification_exists_for_reference",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_notification_record",
    ) as mock_create_notification:
        _session_local_context(mock_session)
        notify_pending_group_invites(author)

    assert mock_create_notification.call_count == 2
    called_reference_ids = {
        call.kwargs["reference_id"] for call in mock_create_notification.call_args_list
    }
    assert called_reference_ids == {invite.id for invite in invites}


def test_notify_pending_group_invites_is_idempotent():
    author = _make_author(email="invitee@example.org")
    invites = [_make_invite_for_email(author.email)]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.list_pending_invites_by_email",
        return_value=invites,
    ), patch(
        "pecha_api.plans.groups.groups_service.notification_exists_for_reference",
        return_value=True,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_notification_record",
    ) as mock_create_notification:
        _session_local_context(mock_session)
        notify_pending_group_invites(author)

    mock_create_notification.assert_not_called()


def test_notify_pending_group_invites_swallows_errors():
    author = _make_author(email="invitee@example.org")

    with patch(
        "pecha_api.plans.groups.groups_service.SessionLocal",
        side_effect=RuntimeError("db down"),
    ):
        # Must not raise: a notification-layer failure can never break signup/login.
        notify_pending_group_invites(author)


def test_accept_group_invite_group_missing_after_invite_found():
    author = _make_author(email="invitee@example.org")
    invite = MagicMock()
    invite.target_email = "invitee@example.org"
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.group_id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            accept_group_invite_by_id(token="t", invite_id=uuid4())
    assert exc.value.detail == GROUP_NOT_FOUND


def test_accept_group_invite_skips_add_when_already_member():
    author = _make_author(email="invitee@example.org")
    group = _make_group()
    invite = MagicMock()
    invite.target_email = "invitee@example.org"
    invite.status = AuthorGroupInviteStatus.PENDING.value
    invite.expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    invite.role = AuthorGroupMemberRole.AUTHOR
    invite.group_id = group.id
    invite.id = uuid4()
    existing = MagicMock()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=existing,
    ), patch(
        "pecha_api.plans.groups.groups_service.add_group_member",
    ) as mock_add, patch(
        "pecha_api.plans.groups.groups_service.save_invite",
    ), patch(
        "pecha_api.plans.groups.groups_service._mark_invite_notification_read",
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        accept_group_invite_by_id(token="t", invite_id=invite.id)
    mock_add.assert_not_called()


def test_list_group_invites_group_not_found():
    author = _make_author()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            list_group_invites(token="t", group_id=uuid4(), status_filter=None)
    assert exc.value.detail == GROUP_NOT_FOUND


def test_revoke_group_invite_not_pending():
    author = _make_author()
    group = _make_group()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.OWNER
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = group.id
    invite.role = AuthorGroupMemberRole.AUTHOR.value
    invite.status = AuthorGroupInviteStatus.ACCEPTED.value

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=current,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            revoke_group_invite(token="t", group_id=group.id, invite_id=invite.id)
    assert "pending" in exc.value.detail.lower()


def test_revoke_group_invite_wrong_group():
    author = _make_author()
    group = _make_group()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.OWNER
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = uuid4()
    invite.role = AuthorGroupMemberRole.AUTHOR.value
    invite.status = AuthorGroupInviteStatus.PENDING.value

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=current,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            revoke_group_invite(token="t", group_id=group.id, invite_id=invite.id)
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_revoke_group_invite_admin_cannot_revoke_admin_invite():
    author = _make_author()
    group = _make_group()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.ADMIN
    invite = MagicMock()
    invite.id = uuid4()
    invite.group_id = group.id
    invite.role = AuthorGroupMemberRole.ADMIN.value
    invite.status = AuthorGroupInviteStatus.PENDING.value

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=current,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_invite_by_id",
        return_value=invite,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            revoke_group_invite(token="t", group_id=group.id, invite_id=invite.id)
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_update_group_member_role_cannot_assign_owner():
    author = _make_author()
    group = _make_group()
    target_id = uuid4()
    current = MagicMock()
    current.role = AuthorGroupMemberRole.OWNER
    target = MagicMock()
    target.role = AuthorGroupMemberRole.ADMIN

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=lambda db, group_id, author_id: current if author_id == author.id else target,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            update_group_member_role(
                token="t",
                group_id=group.id,
                author_id=target_id,
                request=UpdateGroupMemberRoleRequest(role=AuthorGroupMemberRole.OWNER),
            )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.value.detail == OWNER_ROLE_NOT_ASSIGNABLE


def test_transfer_group_ownership_success():
    owner = _make_author()
    group = _make_group()
    new_owner_id = uuid4()
    owner_member = MagicMock()
    owner_member.role = AuthorGroupMemberRole.OWNER
    new_member = MagicMock()
    new_member.role = AuthorGroupMemberRole.ADMIN
    loaded = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=owner,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        side_effect=[group, loaded],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        side_effect=lambda db, group_id, author_id: (
            owner_member if author_id == owner.id else new_member
        ),
    ), patch(
        "pecha_api.plans.groups.groups_service.set_group_member_role",
    ) as mock_set_role, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ):
        _session_local_context(mock_session)
        transfer_group_ownership(
            token="t",
            group_id=group.id,
            new_owner_author_id=new_owner_id,
        )
    assert mock_set_role.call_count == 2


def test_transfer_group_ownership_requires_current_owner():
    author = _make_author()
    group = _make_group()
    admin_member = MagicMock()
    admin_member.role = AuthorGroupMemberRole.ADMIN

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=admin_member,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            transfer_group_ownership(
                token="t",
                group_id=group.id,
                new_owner_author_id=uuid4(),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_get_group_accumulations_success():
    """Test successful retrieval of group accumulations"""
    group = _make_group()
    mantra_id_1 = uuid4()
    mantra_id_2 = uuid4()
    
    # Mock repository row
    mock_row_1 = MagicMock()
    mock_row_1.mantra_id = mantra_id_1
    mock_row_1.total_count = 1200
    
    mock_row_2 = MagicMock()
    mock_row_2.mantra_id = mantra_id_2
    mock_row_2.total_count = 800
    
    # Mock mantra with metadata
    mock_mantra_1 = MagicMock()
    mock_metadata_1 = MagicMock()
    mock_metadata_1.language.value = "EN"
    mock_metadata_1.title = "Medicine Buddha Mantra"
    mock_mantra_1.metadata_entries = [mock_metadata_1]
    
    mock_mantra_2 = MagicMock()
    mock_metadata_2 = MagicMock()
    mock_metadata_2.language.value = "EN"
    mock_metadata_2.title = "Chenrezig Mantra"
    mock_mantra_2.metadata_entries = [mock_metadata_2]
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_mantra_accumulations",
        return_value=([mock_row_1, mock_row_2], 2, 2000),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_mantras_by_ids",
        return_value={mantra_id_1: mock_mantra_1, mantra_id_2: mock_mantra_2},
    ):
        _session_local_context(mock_session)
        result = get_group_accumulations(group_id=group.id, language="en", skip=0, limit=20)
    
    assert result.group_id == group.id
    assert result.total_count == 2000
    assert result.total == 2
    assert len(result.mantras) == 2
    assert result.mantras[0].mantra_id == mantra_id_1
    assert result.mantras[0].count == 1200
    assert result.mantras[0].mantra_title == "Medicine Buddha Mantra"
    assert result.mantras[1].mantra_id == mantra_id_2
    assert result.mantras[1].count == 800


def test_get_group_accumulations_empty():
    """Test group accumulations when no mantras exist"""
    group = _make_group()
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_mantra_accumulations",
        return_value=([], 0, 0),
    ):
        _session_local_context(mock_session)
        result = get_group_accumulations(group_id=group.id)
    
    assert result.group_id == group.id
    assert result.total_count == 0
    assert result.total == 0
    assert len(result.mantras) == 0


def test_get_group_accumulations_group_not_found():
    """Test 404 when group doesn't exist"""
    group_id = uuid4()
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_group_accumulations(group_id=group_id)
    
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


def test_get_group_accumulations_with_language_fallback():
    """Test language fallback when requested language not available"""
    group = _make_group()
    mantra_id = uuid4()
    
    mock_row = MagicMock()
    mock_row.mantra_id = mantra_id
    mock_row.total_count = 500
    
    # Mock mantra with only EN metadata
    mock_mantra = MagicMock()
    mock_metadata_en = MagicMock()
    mock_metadata_en.language.value = "EN"
    mock_metadata_en.title = "Tara Mantra"
    mock_mantra.metadata_entries = [mock_metadata_en]
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_mantra_accumulations",
        return_value=([mock_row], 1, 500),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_mantras_by_ids",
        return_value={mantra_id: mock_mantra},
    ):
        _session_local_context(mock_session)
        # Request BO language but only EN available
        result = get_group_accumulations(group_id=group.id, language="bo")
    
    assert result.mantras[0].mantra_title == "Tara Mantra"  # Falls back to EN


def test_get_group_accumulations_pagination():
    """Test pagination parameters are passed correctly"""
    group = _make_group()
    mantra_id = uuid4()
    
    mock_row = MagicMock()
    mock_row.mantra_id = mantra_id
    mock_row.total_count = 300
    
    mock_mantra = MagicMock()
    mock_metadata = MagicMock()
    mock_metadata.language.value = "EN"
    mock_metadata.title = "Manjushri Mantra"
    mock_mantra.metadata_entries = [mock_metadata]
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_mantra_accumulations",
        return_value=([mock_row], 10, 5000),
    ) as mock_get_accumulations, patch(
        "pecha_api.plans.groups.groups_service.get_mantras_by_ids",
        return_value={mantra_id: mock_mantra},
    ):
        _session_local_context(mock_session)
        result = get_group_accumulations(group_id=group.id, skip=5, limit=1)
    
    # Verify pagination params passed to repository
    mock_get_accumulations.assert_called_once()
    call_kwargs = mock_get_accumulations.call_args[1]
    assert call_kwargs["skip"] == 5
    assert call_kwargs["limit"] == 1
    
    # Verify response
    assert result.skip == 5
    assert result.limit == 1
    assert result.total == 10
    assert result.total_count == 5000


def test_get_group_member_accumulations_success():
    """Test getting member contributions for a group accumulator"""
    group = _make_group()
    group_accumulator_id = uuid4()
    user_id_1 = uuid4()
    user_id_2 = uuid4()
    
    # Mock group accumulator
    mock_group_accumulator = MagicMock()
    mock_group_accumulator.id = group_accumulator_id
    mock_group_accumulator.group_id = group.id
    
    # Mock member contribution rows
    mock_row_1 = MagicMock()
    mock_row_1.user_id = user_id_1
    mock_row_1.total_count = 500
    
    mock_row_2 = MagicMock()
    mock_row_2.user_id = user_id_2
    mock_row_2.total_count = 300
    
    # Mock users
    mock_user_1 = MagicMock()
    mock_user_1.id = user_id_1
    mock_user_1.username = "user1"
    mock_user_1.firstname = "John"
    mock_user_1.lastname = "Doe"
    mock_user_1.avatar_url = "https://example.com/avatar1.jpg"
    
    mock_user_2 = MagicMock()
    mock_user_2.id = user_id_2
    mock_user_2.username = "user2"
    mock_user_2.firstname = "Jane"
    mock_user_2.lastname = "Smith"
    mock_user_2.avatar_url = None
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_by_id",
        return_value=mock_group_accumulator,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_member_contributions",
        return_value=([mock_row_1, mock_row_2], 2),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_users_by_ids",
        return_value={user_id_1: mock_user_1, user_id_2: mock_user_2},
    ):
        _session_local_context(mock_session)
        result = get_group_member_accumulations(
            group_id=group.id,
            accumulation_id=group_accumulator_id,
            skip=0,
            limit=20,
        )
    
    assert result.total_members == 2
    assert len(result.list) == 2
    assert result.list[0].username == "user1"
    assert result.list[0].fullname == "John Doe"
    assert result.list[0].avatar_url == "https://example.com/avatar1.jpg"
    assert result.list[0].count == 500
    assert result.list[1].username == "user2"
    assert result.list[1].fullname == "Jane Smith"
    assert result.list[1].avatar_url is None
    assert result.list[1].count == 300


def test_get_group_member_accumulations_group_not_found():
    """Test error when group doesn't exist"""
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_group_member_accumulations(
                group_id=uuid4(),
                accumulation_id=uuid4(),
                skip=0,
                limit=20,
            )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


def test_get_group_member_accumulations_accumulator_not_found():
    """Test error when group accumulator doesn't exist"""
    group = _make_group()
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_group_member_accumulations(
                group_id=group.id,
                accumulation_id=uuid4(),
                skip=0,
                limit=20,
            )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == "Group accumulator not found"


def test_get_group_member_accumulations_wrong_group():
    """Test error when accumulator doesn't belong to the group"""
    group = _make_group()
    other_group_id = uuid4()
    accumulator_id = uuid4()
    
    mock_group_accumulator = MagicMock()
    mock_group_accumulator.id = accumulator_id
    mock_group_accumulator.group_id = other_group_id
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_by_id",
        return_value=mock_group_accumulator,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_group_member_accumulations(
                group_id=group.id,
                accumulation_id=accumulator_id,
                skip=0,
                limit=20,
            )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == "Group accumulator does not belong to this group"


def test_get_group_member_accumulations_empty():
    """Test when no members have contributed"""
    group = _make_group()
    group_accumulator_id = uuid4()
    
    mock_group_accumulator = MagicMock()
    mock_group_accumulator.id = group_accumulator_id
    mock_group_accumulator.group_id = group.id
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_by_id",
        return_value=mock_group_accumulator,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_member_contributions",
        return_value=([], 0),
    ):
        _session_local_context(mock_session)
        result = get_group_member_accumulations(
            group_id=group.id,
            accumulation_id=group_accumulator_id,
            skip=0,
            limit=20,
        )
    
    assert result.total_members == 0
    assert len(result.list) == 0
    assert result.skip == 0
    assert result.limit == 20


def test_get_group_member_accumulations_fullname_fallback():
    """Test fullname falls back to email when name is empty"""
    group = _make_group()
    group_accumulator_id = uuid4()
    user_id = uuid4()
    
    mock_group_accumulator = MagicMock()
    mock_group_accumulator.id = group_accumulator_id
    mock_group_accumulator.group_id = group.id
    
    mock_row = MagicMock()
    mock_row.user_id = user_id
    mock_row.total_count = 100
    
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.username = "user123"
    mock_user.firstname = ""
    mock_user.lastname = ""
    mock_user.email = "user@example.com"
    mock_user.avatar_url = None
    
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_by_id",
        return_value=mock_group_accumulator,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_member_contributions",
        return_value=([mock_row], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_users_by_ids",
        return_value={user_id: mock_user},
    ):
        _session_local_context(mock_session)
        result = get_group_member_accumulations(
            group_id=group.id,
            accumulation_id=group_accumulator_id,
            skip=0,
            limit=20,
        )
    
    assert result.list[0].fullname == "user@example.com"


def test_as_aware_utc_adds_timezone_for_naive_datetime():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    aware = _as_aware_utc(naive)
    assert aware.tzinfo == timezone.utc
    assert aware.replace(tzinfo=None) == naive


def test_as_aware_utc_preserves_existing_timezone():
    original = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert _as_aware_utc(original) is original


@pytest.mark.asyncio
async def test_get_group_practices_group_not_found():
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            await get_group_practices(group_id=uuid4())
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


@pytest.mark.asyncio
async def test_get_group_practices_private_group_hidden():
    group = _make_group(is_public=False)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            await get_group_practices(group_id=group.id)
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_group_practices_merges_and_sorts_by_created_at():
    group = _make_group()
    series_id = uuid4()
    accumulator_id = uuid4()
    collection_id = uuid4()

    series = MagicMock()
    series.id = series_id
    series.created_at = datetime(2026, 1, 3, tzinfo=timezone.utc)

    series_dto = GroupSeriesListItemDTO(
        id=series_id,
        author_id=uuid4(),
        featured=False,
        status=PlanStatus.PUBLISHED,
    )
    accumulator = GroupAccumulatorDTO(
        id=accumulator_id,
        group_id=group.id,
        title="Om Mani",
        member_count=2,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    collection = GroupRecitationCollectionDTO(
        id=collection_id,
        group_id=group.id,
        name="Morning",
        item_count=1,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    )

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id",
        return_value=[series],
    ), patch(
        "pecha_api.plans.groups.groups_service._series_to_dtos",
        return_value=[series_dto],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_service",
        return_value=GroupAccumulatorsResponse(
            accumulators=[accumulator],
            total=1,
            skip=0,
            limit=1000,
        ),
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_collections_service",
        new_callable=AsyncMock,
        return_value=GroupRecitationCollectionsResponse(
            collections=[collection],
            skip=0,
            limit=1000,
            total=1,
        ),
    ):
        _session_local_context(mock_session)
        result = await get_group_practices(group_id=group.id, skip=0, limit=20)

    assert result.total == 3
    assert result.skip == 0
    assert result.limit == 20
    assert [card.type for card in result.practices] == [
        GroupPracticeType.SERIES,
        GroupPracticeType.ACCUMULATOR,
        GroupPracticeType.COLLECTION,
    ]
    assert result.practices[0].series.id == series_id
    assert result.practices[1].accumulator.id == accumulator_id
    assert result.practices[2].collection.id == collection_id


@pytest.mark.asyncio
async def test_get_group_practices_pagination():
    group = _make_group()
    older = GroupAccumulatorDTO(
        id=uuid4(),
        group_id=group.id,
        title="Older",
        member_count=0,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    newer = GroupAccumulatorDTO(
        id=uuid4(),
        group_id=group.id,
        title="Newer",
        member_count=0,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service._series_to_dtos",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_service",
        return_value=GroupAccumulatorsResponse(
            accumulators=[older, newer],
            total=2,
            skip=0,
            limit=1000,
        ),
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_collections_service",
        new_callable=AsyncMock,
        return_value=GroupRecitationCollectionsResponse(
            collections=[],
            skip=0,
            limit=1000,
            total=0,
        ),
    ):
        _session_local_context(mock_session)
        result = await get_group_practices(group_id=group.id, skip=1, limit=1)

    assert result.total == 2
    assert len(result.practices) == 1
    assert result.practices[0].accumulator.id == older.id


@pytest.mark.asyncio
async def test_get_group_practices_with_valid_token_passes_user_id():
    group = _make_group()
    user = MagicMock()
    user.id = uuid4()
    series = MagicMock()
    series.id = uuid4()
    series.created_at = datetime(2026, 1, 1)  # naive datetime path
    series_dto = GroupSeriesListItemDTO(
        id=series.id,
        author_id=uuid4(),
        featured=False,
        status=PlanStatus.PUBLISHED,
    )

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ) as mock_validate, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id",
        return_value=[series],
    ), patch(
        "pecha_api.plans.groups.groups_service._series_to_dtos",
        return_value=[series_dto],
    ) as mock_series_to_dtos, patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_service",
        return_value=GroupAccumulatorsResponse(accumulators=[], total=0, skip=0, limit=1000),
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_collections_service",
        new_callable=AsyncMock,
        return_value=GroupRecitationCollectionsResponse(collections=[], skip=0, limit=1000, total=0),
    ):
        _session_local_context(mock_session)
        result = await get_group_practices(group_id=group.id, token="valid-token", language="en")

    mock_validate.assert_called_once_with(token="valid-token")
    assert mock_series_to_dtos.call_args.kwargs["user_id"] == user.id
    assert result.total == 1


@pytest.mark.asyncio
async def test_get_group_practices_with_invalid_token_continues_anonymously():
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid"),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service._series_to_dtos",
        return_value=[],
    ) as mock_series_to_dtos, patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_service",
        return_value=GroupAccumulatorsResponse(accumulators=[], total=0, skip=0, limit=1000),
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_collections_service",
        new_callable=AsyncMock,
        return_value=GroupRecitationCollectionsResponse(collections=[], skip=0, limit=1000, total=0),
    ):
        _session_local_context(mock_session)
        result = await get_group_practices(group_id=group.id, token="bad-token")

    assert mock_series_to_dtos.call_args.kwargs["user_id"] is None
    assert result.total == 0
    assert result.practices == []


def _make_feed_user():
    user = MagicMock()
    user.id = uuid4()
    return user


def _make_feed_series(group_id, created_at):
    series = MagicMock()
    series.id = uuid4()
    series.group_id = group_id
    series.created_at = created_at
    return series


def _make_feed_plan(group_id, created_at):
    plan = MagicMock()
    plan.id = uuid4()
    plan.group_id = group_id
    plan.created_at = created_at
    return plan


def _make_feed_accumulator(group_id, created_at):
    accumulator = MagicMock()
    accumulator.id = uuid4()
    accumulator.group_id = group_id
    accumulator.created_at = created_at
    return accumulator


def _feed_series_dto(series):
    return GroupSeriesListItemDTO(
        id=series.id,
        author_id=uuid4(),
        featured=False,
        status=PlanStatus.PUBLISHED,
    )


def _feed_accumulator_dto(accumulator, is_joined, member_count):
    return GroupAccumulatorDTO(
        id=accumulator.id,
        group_id=accumulator.group_id,
        title="Accumulator",
        is_joined=is_joined,
        member_count=member_count,
        created_at=accumulator.created_at,
    )


def _feed_plan_dto(plan_info, group_id):
    return PlanDTO(
        id=plan_info.plan.id,
        title="Plan",
        description="Desc",
        language="EN",
        total_days=1,
        status=PlanStatus.PUBLISHED,
        subscription_count=0,
        group_id=group_id,
    )


def _plan_aggregate(plan):
    aggregate = MagicMock()
    aggregate.plan = plan
    return aggregate


def _make_feed_collection(group_id, created_at):
    collection = MagicMock()
    collection.id = uuid4()
    collection.group_id = group_id
    collection.created_at = created_at
    collection.name = "Collection"
    collection.img_url = None
    return collection


def test_get_group_practices_feed_merges_and_sorts_by_created_at():
    group = _make_group()
    user = _make_feed_user()
    series = _make_feed_series(group.id, datetime(2026, 1, 4, tzinfo=timezone.utc))
    plan = _make_feed_plan(group.id, datetime(2026, 1, 3, tzinfo=timezone.utc))
    accumulator = _make_feed_accumulator(group.id, datetime(2026, 1, 2, tzinfo=timezone.utc))
    collection = _make_feed_collection(group.id, datetime(2026, 1, 1, tzinfo=timezone.utc))

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.resolve_public_group_scope",
        return_value=([group.id], {group.id}),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_for_group_ids",
        return_value=([series], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service._series_to_dtos",
        return_value=[_feed_series_dto(series)],
    ) as mock_series_to_dtos, patch(
        "pecha_api.plans.groups.groups_service.get_standalone_plans_for_group_ids",
        return_value=([plan], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_plans_with_aggregates_by_ids",
        return_value=[_plan_aggregate(plan)],
    ), patch(
        "pecha_api.plans.groups.groups_service._plan_aggregate_to_dto",
        side_effect=_feed_plan_dto,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_for_group_ids",
        return_value=([accumulator], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_accumulator_ids_by_user",
        return_value=[accumulator.id],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_joiners_counts",
        return_value={accumulator.id: 5},
    ), patch(
        "pecha_api.plans.groups.groups_service._group_accumulator_to_dto",
        side_effect=_feed_accumulator_dto,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collections_for_group_ids_with_total",
        return_value=([collection], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collection_item_counts",
        return_value={collection.id: 4},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_by_ids",
        return_value=[group],
    ):
        _session_local_context(mock_session)
        result = get_group_practices_feed(token="valid-token", skip=0, limit=20)

    assert result.total == 4
    assert result.include_unfollowed is False
    assert [card.type for card in result.practices] == [
        GroupPracticeType.SERIES,
        GroupPracticeType.PLAN,
        GroupPracticeType.ACCUMULATOR,
        GroupPracticeType.COLLECTION,
    ]
    assert result.practices[0].series.id == series.id
    assert result.practices[1].plan.id == plan.id
    assert result.practices[2].accumulator.id == accumulator.id
    assert result.practices[2].accumulator.is_joined is True
    assert result.practices[2].accumulator.member_count == 5
    assert result.practices[3].collection.id == collection.id
    assert result.practices[3].collection.item_count == 4
    assert all(card.is_joined for card in result.practices)
    assert all(card.group_id == group.id for card in result.practices)
    assert result.practices[0].group_slug == group.slug
    assert mock_series_to_dtos.call_args.kwargs["user_id"] == user.id
    assert mock_series_to_dtos.call_args.kwargs["published_only"] is True


def test_get_group_practices_feed_guest_uses_public_scope_without_user_lookups():
    group = _make_group()
    accumulator = _make_feed_accumulator(group.id, datetime(2026, 1, 2, tzinfo=timezone.utc))

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
    ) as mock_validate, patch(
        "pecha_api.plans.groups.groups_service.resolve_public_group_scope",
        return_value=([group.id], set()),
    ) as mock_scope, patch(
        "pecha_api.plans.groups.groups_service.get_series_for_group_ids",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_standalone_plans_for_group_ids",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_for_group_ids",
        return_value=([accumulator], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_accumulator_ids_by_user",
    ) as mock_joined_acc, patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_joiners_counts",
        return_value={accumulator.id: 5},
    ), patch(
        "pecha_api.plans.groups.groups_service._group_accumulator_to_dto",
        side_effect=_feed_accumulator_dto,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collections_for_group_ids_with_total",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collection_item_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_by_ids",
        return_value=[group],
    ):
        _session_local_context(mock_session)
        result = get_group_practices_feed(token=None, skip=0, limit=20)

    mock_validate.assert_not_called()
    mock_joined_acc.assert_not_called()
    mock_scope.assert_called_once()
    assert mock_scope.call_args.kwargs["user_id"] is None
    assert result.total == 1
    assert result.practices[0].is_joined is False
    assert result.practices[0].accumulator.is_joined is False


def test_get_group_practices_feed_marks_unfollowed_groups():
    joined_group = _make_group(slug="joined-group")
    other_group = _make_group(slug="other-group")
    user = _make_feed_user()
    accumulator = _make_feed_accumulator(
        other_group.id, datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.resolve_public_group_scope",
        return_value=([joined_group.id, other_group.id], {joined_group.id}),
    ) as mock_scope, patch(
        "pecha_api.plans.groups.groups_service.get_series_for_group_ids",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_standalone_plans_for_group_ids",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_plans_with_aggregates_by_ids",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_for_group_ids",
        return_value=([accumulator], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_accumulator_ids_by_user",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_joiners_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service._group_accumulator_to_dto",
        side_effect=_feed_accumulator_dto,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collections_for_group_ids_with_total",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collection_item_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_by_ids",
        return_value=[other_group],
    ):
        _session_local_context(mock_session)
        result = get_group_practices_feed(
            token="valid-token", should_include_unfollowed=True
        )

    assert mock_scope.call_args.kwargs["should_include_unfollowed"] is True
    assert result.include_unfollowed is True
    assert result.total == 1
    assert result.practices[0].is_joined is False
    assert result.practices[0].group_id == other_group.id
    assert result.practices[0].group_slug == "other-group"


def test_get_group_practices_feed_group_filter_restricts_scope():
    group_a = _make_group(slug="group-a")
    group_b = _make_group(slug="group-b")
    user = _make_feed_user()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.resolve_public_group_scope",
        return_value=([group_a.id, group_b.id], {group_a.id, group_b.id}),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_for_group_ids",
        return_value=([], 0),
    ) as mock_series, patch(
        "pecha_api.plans.groups.groups_service.get_standalone_plans_for_group_ids",
        return_value=([], 0),
    ) as mock_plans, patch(
        "pecha_api.plans.groups.groups_service.get_plans_with_aggregates_by_ids",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_for_group_ids",
        return_value=([], 0),
    ) as mock_accumulators, patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_accumulator_ids_by_user",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_joiners_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collections_for_group_ids_with_total",
        return_value=([], 0),
    ) as mock_collections, patch(
        "pecha_api.plans.groups.groups_service.get_collection_item_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_by_ids",
        return_value=[],
    ):
        _session_local_context(mock_session)
        result = get_group_practices_feed(token="valid-token", group_id=group_b.id)

    assert mock_series.call_args.kwargs["group_ids"] == [group_b.id]
    assert mock_plans.call_args.kwargs["group_ids"] == [group_b.id]
    assert mock_accumulators.call_args.kwargs["group_ids"] == [group_b.id]
    assert mock_collections.call_args.kwargs["group_ids"] == [group_b.id]
    assert result.total == 0


def test_get_group_practices_feed_group_filter_outside_scope_returns_empty():
    group = _make_group()
    user = _make_feed_user()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.resolve_public_group_scope",
        return_value=([group.id], {group.id}),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_for_group_ids",
    ) as mock_series:
        _session_local_context(mock_session)
        result = get_group_practices_feed(token="valid-token", group_id=uuid4())

    mock_series.assert_not_called()
    assert result.total == 0
    assert result.practices == []


def test_get_group_practices_feed_pagination():
    group = _make_group()
    user = _make_feed_user()
    older = _make_feed_accumulator(group.id, datetime(2026, 1, 1, tzinfo=timezone.utc))
    newer = _make_feed_accumulator(group.id, datetime(2026, 1, 2, tzinfo=timezone.utc))

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.resolve_public_group_scope",
        return_value=([group.id], {group.id}),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_for_group_ids",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_standalone_plans_for_group_ids",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_plans_with_aggregates_by_ids",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_for_group_ids",
        return_value=([older, newer], 2),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_accumulator_ids_by_user",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_joiners_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service._group_accumulator_to_dto",
        side_effect=_feed_accumulator_dto,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collections_for_group_ids_with_total",
        return_value=([], 0),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collection_item_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_by_ids",
        return_value=[group],
    ):
        _session_local_context(mock_session)
        result = get_group_practices_feed(token="valid-token", skip=1, limit=1)

    assert result.total == 2
    assert len(result.practices) == 1
    assert result.practices[0].accumulator.id == older.id


def test_restricted_ids_for_timezone_returns_none_outside_china_timezone():
    with patch(
        "pecha_api.plans.groups.groups_service.is_china_timezone", return_value=False
    ), patch(
        "pecha_api.plans.groups.groups_service.get_restricted_item_ids"
    ) as mock_get_restricted_ids:
        result = _restricted_ids_for_timezone(RestrictedItemType.SERIES, "America/New_York")

    assert result is None
    mock_get_restricted_ids.assert_not_called()


def test_restricted_ids_for_timezone_returns_none_when_no_restricted_items():
    with patch(
        "pecha_api.plans.groups.groups_service.is_china_timezone", return_value=True
    ), patch(
        "pecha_api.plans.groups.groups_service.get_restricted_item_ids",
        return_value=frozenset(),
    ):
        result = _restricted_ids_for_timezone(RestrictedItemType.SERIES, "Asia/Shanghai")

    assert result is None


def test_restricted_ids_for_timezone_returns_list_when_china_timezone_has_restrictions():
    restricted_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_service.is_china_timezone", return_value=True
    ), patch(
        "pecha_api.plans.groups.groups_service.get_restricted_item_ids",
        return_value=frozenset({restricted_id}),
    ) as mock_get_restricted_ids:
        result = _restricted_ids_for_timezone(RestrictedItemType.GROUP_ACCUMULATOR, "Asia/Shanghai")

    assert result == [restricted_id]
    mock_get_restricted_ids.assert_called_once_with(RestrictedItemType.GROUP_ACCUMULATOR)


def test_get_group_practices_feed_passes_restricted_ids_to_source_queries():
    """When the caller is in a China timezone, each source query must receive
    the restricted-id set to exclude at the query layer, so a fixed fetch
    window never omits eligible items that fall past a restricted one."""
    group = _make_group()
    user = _make_feed_user()
    restricted_series_id = uuid4()
    restricted_plan_id = uuid4()
    restricted_accumulator_id = uuid4()
    restricted_collection_id = uuid4()

    def _restricted_ids(item_type):
        return {
            RestrictedItemType.SERIES: frozenset({restricted_series_id}),
            RestrictedItemType.PLAN: frozenset({restricted_plan_id}),
            RestrictedItemType.GROUP_ACCUMULATOR: frozenset({restricted_accumulator_id}),
            RestrictedItemType.GROUP_RECITATION_COLLECTION: frozenset({restricted_collection_id}),
        }[item_type]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.resolve_public_group_scope",
        return_value=([group.id], {group.id}),
    ), patch(
        "pecha_api.plans.groups.groups_service.filter_items_for_timezone",
        side_effect=lambda items, **_: list(items),
    ), patch(
        "pecha_api.plans.groups.groups_service.is_china_timezone", return_value=True
    ), patch(
        "pecha_api.plans.groups.groups_service.get_restricted_item_ids",
        side_effect=_restricted_ids,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_for_group_ids",
        return_value=([], 0),
    ) as mock_series, patch(
        "pecha_api.plans.groups.groups_service.get_standalone_plans_for_group_ids",
        return_value=([], 0),
    ) as mock_plans, patch(
        "pecha_api.plans.groups.groups_service.get_plans_with_aggregates_by_ids",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_for_group_ids",
        return_value=([], 0),
    ) as mock_accumulators, patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_accumulator_ids_by_user",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_joiners_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collections_for_group_ids_with_total",
        return_value=([], 0),
    ) as mock_collections, patch(
        "pecha_api.plans.groups.groups_service.get_collection_item_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_by_ids",
        return_value=[],
    ):
        _session_local_context(mock_session)
        get_group_practices_feed(
            token="valid-token", timezone_name="Asia/Shanghai"
        )

    assert mock_series.call_args.kwargs["exclude_ids"] == [restricted_series_id]
    assert mock_plans.call_args.kwargs["exclude_ids"] == [restricted_plan_id]
    assert mock_accumulators.call_args.kwargs["exclude_ids"] == [restricted_accumulator_id]
    assert mock_collections.call_args.kwargs["exclude_ids"] == [restricted_collection_id]


def test_get_group_practices_feed_no_exclude_ids_outside_china_timezone():
    group = _make_group()
    user = _make_feed_user()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.resolve_public_group_scope",
        return_value=([group.id], {group.id}),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_for_group_ids",
        return_value=([], 0),
    ) as mock_series, patch(
        "pecha_api.plans.groups.groups_service.get_standalone_plans_for_group_ids",
        return_value=([], 0),
    ) as mock_plans, patch(
        "pecha_api.plans.groups.groups_service.get_plans_with_aggregates_by_ids",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulators_for_group_ids",
        return_value=([], 0),
    ) as mock_accumulators, patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_accumulator_ids_by_user",
        return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_accumulator_joiners_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_collections_for_group_ids_with_total",
        return_value=([], 0),
    ) as mock_collections, patch(
        "pecha_api.plans.groups.groups_service.get_collection_item_counts",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_by_ids",
        return_value=[],
    ):
        _session_local_context(mock_session)
        get_group_practices_feed(token="valid-token")

    assert mock_series.call_args.kwargs["exclude_ids"] is None
    assert mock_plans.call_args.kwargs["exclude_ids"] is None
    assert mock_accumulators.call_args.kwargs["exclude_ids"] is None
    assert mock_collections.call_args.kwargs["exclude_ids"] is None


def _make_metadata_entry(language, title):
    entry = MagicMock()
    entry.language = language
    entry.title = title
    return entry


def test_group_card_title_falls_back_to_slug_without_metadata():
    group = _make_group(slug="no-metadata-group")
    group.metadata_entries = []

    assert _group_card_title(group) == "no-metadata-group"


def test_group_card_title_returns_entry_matching_requested_language():
    group = _make_group()
    group.metadata_entries = [
        _make_metadata_entry("EN", "English Title"),
        _make_metadata_entry("BO", "Tibetan Title"),
    ]

    assert _group_card_title(group, language="BO") == "Tibetan Title"


def test_group_card_title_falls_back_to_first_entry_when_no_language_matches():
    group = _make_group()
    group.metadata_entries = [_make_metadata_entry("FR", "French Title")]

    assert _group_card_title(group, language="BO") == "French Title"


# --- get_group_permission tests ---

from pecha_api.plans.groups.groups_service import get_group_permission


def _make_user(user_id=None, email="user@example.org", phone_number=None):
    user = MagicMock()
    user.id = user_id or uuid4()
    user.email = email
    user.phone_number = phone_number
    return user


def test_get_group_permission_app_user_no_author():
    """App user token (no CMS author) → has_permission: false, author_id: null"""
    user = _make_user(email="appuser@example.org")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(user.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found"),
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.is_super_admin is False
    assert result.author_id is None


def _no_matching_user():
    """Simulate an Author-only token: no live Users row exists at the subject id
    (exact-id lookup) and the broader user resolver also finds nothing."""
    return patch.multiple(
        "pecha_api.plans.groups.groups_service",
        get_user_by_id=MagicMock(
            side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
        ),
        validate_and_extract_user_details=MagicMock(
            side_effect=HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not a user")
        ),
    )


def test_get_group_permission_inactive_author():
    """Inactive author → has_permission: false even if they have a role"""
    author = _make_author(email="inactive@example.org", is_active=False)
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_super_admin_not_a_member():
    """Super admin who isn't a member of this group → has_permission: true (bypass),
    but role reflects their real (absent) membership rather than a fabricated OWNER.

    Owner-only operations like ownership transfer have no super-admin bypass, so
    this DTO must not claim an OWNER role the super admin does not actually hold.
    """
    author = _make_author(email="admin@example.org", is_admin=True)
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=None,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is True
    assert result.role is None
    assert result.is_super_admin is True
    assert result.author_id == author.id


def test_get_group_permission_reviewer_with_owner_role_can_manage():
    """Reviewer platform role with an OWNER group membership → has_permission: true.

    The actual group-settings/member-management guards this endpoint
    represents (_assert_role_allowed) only check group role and the
    super-admin bypass; they never check the reviewer platform role (that
    gate only exists on content operations). Reporting has_permission:
    false here would contradict what those real guards actually allow.
    """
    author = _make_author(email="reviewer@example.org", platform_role=PlatformRole.REVIEWER)
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=AuthorGroupMemberRole.OWNER,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is True
    assert result.role == AuthorGroupMemberRole.OWNER
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_group_member():
    """Group member with ADMIN role → has_permission: true (ADMIN can manage group settings/members)"""
    author = _make_author(email="member@example.org")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=AuthorGroupMemberRole.ADMIN,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is True
    assert result.can_create_content is True
    assert result.role == AuthorGroupMemberRole.ADMIN
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_owner_role():
    """Group OWNER → has_permission: true"""
    author = _make_author(email="owner@example.org")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=AuthorGroupMemberRole.OWNER,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is True
    assert result.role == AuthorGroupMemberRole.OWNER
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_author_role_no_management():
    """AUTHOR role can create content but cannot manage group → has_permission: false"""
    author = _make_author(email="author@example.org")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=AuthorGroupMemberRole.AUTHOR,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.can_create_content is True
    assert result.role == AuthorGroupMemberRole.AUTHOR
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_viewer_role_no_management():
    """VIEWER role can only read → has_permission: false, can_create_content: false"""
    author = _make_author(email="viewer@example.org")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=AuthorGroupMemberRole.VIEWER,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.can_create_content is False
    assert result.role == AuthorGroupMemberRole.VIEWER
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_author_not_member():
    """Author account exists but not a member of this group → has_permission: false"""
    author = _make_author(email="notmember@example.org")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=None,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_group_not_found():
    """Unknown/deleted group → 404"""
    author = _make_author()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ), _no_matching_user():
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_group_permission(token="t", group_id=uuid4())

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


def test_get_group_permission_unresolvable_identity_no_group_existence_oracle():
    """A cryptographically valid token whose subject matches neither a User
    nor an Author (e.g. a deleted account) must always get 401 - regardless
    of whether the requested group exists. Group lookup must never run
    before identity resolution, or a 404-vs-401 split would let such a
    token enumerate which group ids (including private ones) exist.
    """
    unresolvable_subject = uuid4()

    for group_lookup_result in (None, _make_group()):
        with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
            "pecha_api.plans.groups.groups_service.validate_token",
            return_value={"sub": str(unresolvable_subject)},
        ), patch(
            "pecha_api.plans.groups.groups_service.find_author_by_id",
            return_value=None,
        ), patch(
            "pecha_api.plans.groups.groups_service.get_group_by_id",
            return_value=group_lookup_result,
        ) as mock_get_group, _no_matching_user():
            _session_local_context(mock_session)
            with pytest.raises(HTTPException) as exc:
                get_group_permission(token="t", group_id=uuid4())

        assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
        mock_get_group.assert_not_called()


def test_get_group_permission_group_not_found_no_author():
    """Unknown/deleted group with app user token → 404 (not has_permission: false)"""
    user = _make_user(email="test@example.org")
    group_id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(user.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found"),
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_group_permission(token="t", group_id=group_id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == GROUP_NOT_FOUND


def test_get_group_permission_invalid_token():
    """Invalid/expired token → 401 (not has_permission: false)"""
    with patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        side_effect=Exception("Invalid token"),
    ):
        with pytest.raises(HTTPException) as exc:
            get_group_permission(token="invalid", group_id=uuid4())

    assert exc.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc.value.detail == "Invalid or expired token"


def test_get_group_permission_user_uuid_matches_unrelated_author():
    """A regular user's id happens to collide with an unrelated Author's id →
    the User match must win; the token must never be evaluated with that
    unrelated Author's permissions (even though find_author_by_id *does*
    return a match here). The token carries the live user's own email, as
    any real token minted for this account would - it is what lets the
    code positively rule out the colliding Author.

    This tests Issue 3 & 8: Cross-domain subject confusion prevention.
    """
    user = _make_user(email="regularuser@example.org")
    colliding_author = _make_author(
        author_id=user.id, email="unrelated-author@example.org", is_admin=True
    )
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(user.id), "email": user.email},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=colliding_author,  # same id, unrelated Author record
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=None,  # this user's own email has no Author account
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        return_value=user,  # live Users row exists at this exact id
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_user_id",
        return_value=None,  # this user has no persisted Author link
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.is_super_admin is False
    assert result.author_id is None


def test_get_group_permission_stale_email_claim_does_not_deny_rightful_author():
    """A token whose email claim no longer matches the Author's current
    record (e.g. their profile changed after the token was minted) must
    still resolve as that Author when no live User competes for the same
    id - there is no other live account this token could actually belong
    to, so the mismatch is just staleness, not evidence of impersonation.
    """
    author = _make_author(author_id=uuid4(), email="new-email@example.org", is_admin=False)
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id), "email": "old-email@example.org"},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=AuthorGroupMemberRole.OWNER,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is True
    assert result.role == AuthorGroupMemberRole.OWNER
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_phone_only_author_no_collision():
    """A legitimate Author with no email on record (phone-only) and no
    colliding User must still resolve to their real Author permissions.
    There is no email claim to corroborate against, so the id match alone
    is trusted - matching how Author tokens are validated everywhere else.
    """
    author = _make_author(author_id=uuid4(), email=None, is_admin=False)
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=AuthorGroupMemberRole.OWNER,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is True
    assert result.role == AuthorGroupMemberRole.OWNER
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_author_uuid_collides_with_user_is_not_author():
    """A live User at the same id as an Author is a website login, not a
    CMS identity. Contact claims must not disambiguate the collision.
    """
    colliding_user = _make_user(email="unrelated-user@example.org")
    author = _make_author(
        author_id=colliding_user.id, email="author@example.org", is_admin=False
    )
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id), "email": "author@example.org"},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        return_value=colliding_user,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.is_super_admin is False
    assert result.author_id is None


def test_get_group_permission_phone_only_user_uuid_collides_with_author():
    """A live phone-only User (no email at all, so their real token carries
    no email claim) whose id collides with an Author must resolve as the
    User, not the Author - even though there's no email evidence available
    on either side. With a live competing User and no way to positively
    confirm the Author, id alone must not be trusted, in either direction.
    """
    phone_user = _make_user(email=None, phone_number="+15550001111")
    colliding_author = _make_author(
        author_id=phone_user.id, email="unrelated-author@example.org", is_admin=True
    )
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(phone_user.id)},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=colliding_author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        return_value=phone_user,  # live Users row exists at this exact id
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.is_super_admin is False
    assert result.author_id is None


def test_get_group_permission_phone_only_author_uuid_collides_with_user_is_not_author():
    """A phone match does not bind a colliding User token to that Author."""
    colliding_user = _make_user(email="unrelated-user@example.org", phone_number="+15559998888")
    author = _make_author(author_id=colliding_user.id, email=None, is_admin=False)
    author.phone_number = "+15551234567"
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id), "phone_number": "+15551234567"},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        return_value=colliding_user,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.is_super_admin is False
    assert result.author_id is None


def test_get_group_permission_stale_phone_claim_does_not_deny_rightful_author():
    """A token whose phone_number claim no longer matches the Author's
    current record (e.g. they linked/changed their phone after the token
    was minted, which does not force reissuance - see link_phone_identity)
    must still resolve as that Author when no live User competes for the
    same id. Mirrors the email case: staleness alone is never grounds for
    rejection when there's no other live account the token could belong to.
    """
    author = _make_author(author_id=uuid4(), email=None, is_admin=False)
    author.phone_number = "+15559998888"
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(author.id), "phone_number": "+15551234567"},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_role",
        return_value=AuthorGroupMemberRole.ADMIN,
    ), _no_matching_user():
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is True
    assert result.role == AuthorGroupMemberRole.ADMIN
    assert result.is_super_admin is False
    assert result.author_id == author.id


def test_get_group_permission_website_user_does_not_resolve_author_by_email():
    """A website User token must not inherit CMS access from a shared email."""
    user = _make_user(email="shared@example.org")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(user.id), "email": "shared@example.org"},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=_make_author(email="shared@example.org", is_admin=False),
    ) as by_email, patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    by_email.assert_not_called()
    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.author_id is None


def test_get_group_permission_website_user_does_not_resolve_author_by_phone():
    """A website User token must not inherit CMS access from a shared phone."""
    user = _make_user(email=None, phone_number="+15551234567")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(user.id), "phone_number": "+15551234567"},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)
    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.author_id is None


def test_get_group_permission_no_contact_match_no_author():
    """A website User with no Author at their subject id has no CMS access.
    """
    user = _make_user(email="nobody-links-to-me@example.org")
    group = _make_group()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_token",
        return_value={"sub": str(user.id), "email": "nobody-links-to-me@example.org"},
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_email",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_user_by_id",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.find_author_by_user_id",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        result = get_group_permission(token="t", group_id=group.id)

    assert result.group_id == group.id
    assert result.has_permission is False
    assert result.role is None
    assert result.author_id is None


def test_get_author_group_detail_private_group_is_teaser_for_non_joiner():
    """Discoverable, but no members, contacts or content until you join."""
    private_group = _make_group(is_public=False)
    member = MagicMock()
    member.author_id = uuid4()
    member.role = AuthorGroupMemberRole.OWNER
    member.author = MagicMock(first_name="A", last_name="B", email="owner@example.org")
    private_group.members = [member]
    private_group.social_links = [MagicMock(id=uuid4(), platform="web", url="https://x")]

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=private_group,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id",
    ) as mock_series, patch(
        "pecha_api.plans.groups.groups_service.get_plans_by_group_id",
    ) as mock_plans:
        _session_local_context(mock_session)
        result = get_author_group_detail(group_id=private_group.id)

    assert result.id == private_group.id
    assert result.is_public is False
    # no moderator emails, no contact links, no content
    assert result.members == []
    assert result.social_links == []
    assert result.series == []
    assert result.plans == []
    mock_series.assert_not_called()
    mock_plans.assert_not_called()


def test_get_author_group_detail_private_group_full_for_joiner():
    private_group = _make_group(is_public=False)
    user = MagicMock()
    user.id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=private_group,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=True,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_room_by_group_id", return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id", return_value=[],
    ) as mock_series, patch(
        "pecha_api.plans.groups.groups_service.get_plans_by_group_id", return_value=[],
    ):
        _session_local_context(mock_session)
        result = get_author_group_detail(group_id=private_group.id, token="t")

    assert result.id == private_group.id
    mock_series.assert_called_once()


def _detail_with_chat_room(
    *,
    joined=False,
    following=False,
    room=None,
    token=None,
):
    """Run the public group detail with the chat lookups pinned, so a case only
    has to say who the caller is and whether the room exists."""
    group = _make_group(is_public=True)
    user = MagicMock()
    user.id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=joined,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_following_group", return_value=following,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_room_by_group_id", return_value=room,
    ) as mock_get_room, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_status_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id", return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_plans_by_group_id", return_value=[],
    ):
        _session_local_context(mock_session)
        return get_author_group_detail(group_id=group.id, token=token), mock_get_room


def test_group_detail_carries_the_chat_room_id_for_a_joiner():
    """The group page can open the chat without a second round trip."""
    room = MagicMock(id=uuid4())

    result, _ = _detail_with_chat_room(joined=True, room=room, token="t")

    assert result.chat_room_id == room.id


def test_group_detail_carries_the_chat_room_id_for_a_follower():
    """Followers may chat too, so withholding the id would hide a room they
    can actually open."""
    room = MagicMock(id=uuid4())

    result, _ = _detail_with_chat_room(following=True, room=room, token="t")

    assert result.chat_room_id == room.id


def test_group_detail_has_no_chat_room_id_before_the_room_exists():
    """A room is created by the chat routes on first use - reading a group
    page must not create one, nor make the viewer its creator."""
    result, _ = _detail_with_chat_room(joined=True, room=None, token="t")

    assert result.chat_room_id is None


def test_group_detail_has_no_chat_room_id_for_an_outsider():
    result, mock_get_room = _detail_with_chat_room(
        joined=False, following=False, room=MagicMock(id=uuid4()), token="t"
    )

    assert result.chat_room_id is None
    # Not eligible, so the room is never even looked up.
    mock_get_room.assert_not_called()


def test_group_detail_has_no_chat_room_id_for_an_anonymous_caller():
    result, mock_get_room = _detail_with_chat_room(
        joined=True, room=MagicMock(id=uuid4()), token=None
    )

    assert result.chat_room_id is None
    mock_get_room.assert_not_called()


def test_get_author_group_detail_public_group_unaffected():
    public_group = _make_group(is_public=True)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=public_group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id", return_value=[],
    ) as mock_series, patch(
        "pecha_api.plans.groups.groups_service.get_plans_by_group_id", return_value=[],
    ):
        _session_local_context(mock_session)
        result = get_author_group_detail(group_id=public_group.id)

    assert result.is_public is True
    mock_series.assert_called_once()


def test_list_group_members_private_group_returns_members_without_token():
    group = _make_group(is_public=False)
    user = _make_joiner("bob", "bob@example.org", firstname="Bob", lastname="Jones")
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_joiners_paginated",
        return_value=([user], 1),
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member_roles_by_emails",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service._user_avatar_url",
        return_value=None,
    ):
        _session_local_context(mock_session)
        result = list_group_members(group_id=group.id, skip=0, limit=20)

    assert result.total_members == 1
    assert result.list[0].username == "bob"


def _make_join_request(
    *,
    group_id=None,
    user_id=None,
    request_status=AuthorGroupJoinRequestStatus.PENDING,
    message="let me in",
):
    join_request = MagicMock()
    join_request.id = uuid4()
    join_request.group_id = group_id or uuid4()
    join_request.user_id = user_id or uuid4()
    join_request.message = message
    join_request.status = request_status.value
    join_request.reviewed_by = None
    join_request.reviewed_at = None
    join_request.created_at = datetime.now(timezone.utc)
    return join_request


def test_join_group_private_group_directs_to_request_flow():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_join",
    ) as mock_join:
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            join_group(token="t", group_id=group.id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.value.detail == GROUP_IS_PRIVATE_USE_REQUEST
    mock_join.assert_not_called()


def test_submit_group_join_request_creates_pending_request():
    user = MagicMock()
    user.id = uuid4()
    user.firstname = "Tenzin"
    user.lastname = "Tib"
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    created = _make_join_request(group_id=group.id, user_id=user.id)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_visibility",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_join_request",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_join_request",
        return_value=created,
    ) as mock_create, patch(
        "pecha_api.plans.groups.groups_service.list_group_member_ids_by_roles",
        return_value=[],
    ):
        _session_local_context(mock_session)
        result = submit_group_join_request(
            token="t",
            group_id=group.id,
            request=CreateGroupJoinRequest(message="  let me in  "),
        )

    assert result.status == AuthorGroupJoinRequestStatus.PENDING
    assert result.id == created.id
    assert set(result.model_dump().keys()) == {"id", "status"}
    assert mock_create.call_args.kwargs["join_request"].message == "let me in"


def test_submit_group_join_request_rejects_public_group():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=True, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            submit_group_join_request(
                token="t", group_id=group.id, request=CreateGroupJoinRequest()
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_submit_group_join_request_rejects_existing_member():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_visibility",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group",
        return_value=True,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            submit_group_join_request(
                token="t", group_id=group.id, request=CreateGroupJoinRequest()
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "already a member" in exc.value.detail


def test_submit_group_join_request_rejects_duplicate_pending():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_visibility",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group",
        return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_join_request",
        return_value=True,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            submit_group_join_request(
                token="t", group_id=group.id, request=CreateGroupJoinRequest()
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "already pending" in exc.value.detail


def test_submit_group_join_request_rejects_page_type():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=False, group_type=AuthorGroupType.PAGE)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            submit_group_join_request(
                token="t", group_id=group.id, request=CreateGroupJoinRequest()
            )

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_approve_group_join_request_adds_joiner():
    author = _make_author(is_admin=True)
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    join_request = _make_join_request(group_id=group.id)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_by_id",
        return_value=join_request,
    ), patch(
        # A MagicMock session makes every ban lookup return a row; the ban
        # cases have their own tests in test_group_bans.py.
        "pecha_api.plans.groups.groups_service.get_group_ban_expiry",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_join",
    ) as mock_join, patch(
        "pecha_api.plans.groups.groups_service.save_join_request",
    ) as mock_save:
        _session_local_context(mock_session)
        result = approve_group_join_request(
            token="t", group_id=group.id, request_id=join_request.id
        )

    mock_join.assert_called_once()
    assert mock_join.call_args.kwargs["user_id"] == join_request.user_id
    assert join_request.status == AuthorGroupJoinRequestStatus.APPROVED.value
    assert join_request.reviewed_by == author.id
    assert join_request.reviewed_at is not None
    mock_save.assert_called_once()
    assert result.status == AuthorGroupJoinRequestStatus.APPROVED


def test_reject_group_join_request_leaves_membership_unchanged():
    author = _make_author(is_admin=True)
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    join_request = _make_join_request(group_id=group.id)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_by_id",
        return_value=join_request,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_join",
    ) as mock_join, patch(
        "pecha_api.plans.groups.groups_service.save_join_request",
    ):
        _session_local_context(mock_session)
        result = reject_group_join_request(
            token="t", group_id=group.id, request_id=join_request.id
        )

    mock_join.assert_not_called()
    assert result.status == AuthorGroupJoinRequestStatus.REJECTED


def test_approve_group_join_request_rejects_already_reviewed():
    author = _make_author(is_admin=True)
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    join_request = _make_join_request(
        group_id=group.id, request_status=AuthorGroupJoinRequestStatus.APPROVED
    )

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_by_id",
        return_value=join_request,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            approve_group_join_request(
                token="t", group_id=group.id, request_id=join_request.id
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_approve_group_join_request_rejects_request_from_other_group():
    author = _make_author(is_admin=True)
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    join_request = _make_join_request(group_id=uuid4())

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_by_id",
        return_value=join_request,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            approve_group_join_request(
                token="t", group_id=group.id, request_id=join_request.id
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == JOIN_REQUEST_NOT_FOUND


def test_list_group_join_requests_requires_management_role():
    author = _make_author()
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    member = MagicMock()
    member.role = AuthorGroupMemberRole.VIEWER

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=member,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            list_group_join_requests(token="t", group_id=group.id, skip=0, limit=20)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_list_group_join_requests_returns_requester_profile():
    author = _make_author(is_admin=True)
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    join_request = _make_join_request(group_id=group.id)
    requester = MagicMock()
    requester.firstname = "Tenzin"
    requester.lastname = "Tib"
    requester.email = "tenzin@example.com"
    requester.avatar_url = None
    join_request.user = requester

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_join_requests_by_group",
        return_value=([join_request], 1),
    ):
        _session_local_context(mock_session)
        result = list_group_join_requests(token="t", group_id=group.id, skip=0, limit=20)

    assert result.total == 1
    assert result.requests[0].user_name == "Tenzin Tib"
    assert result.requests[0].email == "tenzin@example.com"
    assert result.requests[0].status == AuthorGroupJoinRequestStatus.PENDING


def test_list_group_join_requests_omits_email_when_user_has_none():
    author = _make_author(is_admin=True)
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    join_request = _make_join_request(group_id=group.id)
    requester = MagicMock()
    requester.firstname = "Dawa"
    requester.lastname = ""
    requester.email = None
    requester.avatar_url = None
    join_request.user = requester

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id",
        return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_join_requests_by_group",
        return_value=([join_request], 1),
    ):
        _session_local_context(mock_session)
        result = list_group_join_requests(token="t", group_id=group.id, skip=0, limit=20)

    assert result.requests[0].email is None


def test_flipping_group_public_approves_pending_join_requests():
    group_id = uuid4()
    pending = [_make_join_request(group_id=group_id), _make_join_request(group_id=group_id)]
    mock_db = MagicMock()

    with patch(
        "pecha_api.plans.groups.groups_service.list_pending_join_requests_by_group",
        return_value=pending,
    ) as mock_list, patch(
        # A MagicMock session makes every ban lookup return a row; the ban
        # cases have their own tests in test_group_bans.py.
        "pecha_api.plans.groups.groups_service.get_group_ban_expiry",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_join",
    ) as mock_join:
        _approve_pending_join_requests_on_publish(mock_db, group_id=group_id)

    # same atomicity guarantee as moderator approval
    assert mock_list.call_args.kwargs["for_update"] is True
    assert all(c.kwargs["commit"] is False for c in mock_join.call_args_list)
    # the caller's update_group commit closes the transaction
    mock_db.commit.assert_not_called()

    assert mock_join.call_count == 2
    assert all(
        item.status == AuthorGroupJoinRequestStatus.APPROVED.value for item in pending
    )
    # auto-approval has no human reviewer
    assert all(item.reviewed_by is None for item in pending)


def test_submit_group_join_request_notifies_moderators():
    user = MagicMock()
    user.id = uuid4()
    user.firstname = "Tenzin"
    user.lastname = "Tib"
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    group.metadata_entries = [_make_metadata_entry("EN", "Chanting Circle")]
    created = _make_join_request(group_id=group.id, user_id=user.id)
    owner_id, admin_id = uuid4(), uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_visibility", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_join_request", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_join_request", return_value=created,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_member_ids_by_roles",
        return_value=[owner_id, admin_id],
    ), patch(
        "pecha_api.plans.groups.groups_service.create_notification_record",
    ) as mock_notify:
        _session_local_context(mock_session)
        result = submit_group_join_request(
            token="t", group_id=group.id, request=CreateGroupJoinRequest()
        )

    assert result.status == AuthorGroupJoinRequestStatus.PENDING
    assert mock_notify.call_count == 2
    recipients = {call.kwargs["recipient_author_id"] for call in mock_notify.call_args_list}
    assert recipients == {owner_id, admin_id}
    first = mock_notify.call_args_list[0].kwargs
    assert first["category"] == "group_join_request"
    # reference_id is the GROUP, so Studio can route to its review screen
    assert first["reference_id"] == group.id
    assert "Chanting Circle" in first["title"]
    assert "Tenzin Tib" in first["description"]


def test_submit_group_join_request_survives_notification_failure():
    """A notification outage must not lose the join request."""
    user = MagicMock()
    user.id = uuid4()
    user.firstname = "Tenzin"
    user.lastname = "Tib"
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    created = _make_join_request(group_id=group.id, user_id=user.id)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_visibility", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_join_request", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_join_request", return_value=created,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_member_ids_by_roles",
        return_value=[uuid4()],
    ), patch(
        "pecha_api.plans.groups.groups_service.create_notification_record",
        side_effect=RuntimeError("notification service down"),
    ):
        _session_local_context(mock_session)
        result = submit_group_join_request(
            token="t", group_id=group.id, request=CreateGroupJoinRequest()
        )

    assert result.id == created.id


def test_submit_group_join_request_without_moderators_sends_nothing():
    user = MagicMock()
    user.id = uuid4()
    user.firstname = "Tenzin"
    user.lastname = "Tib"
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    created = _make_join_request(group_id=group.id, user_id=user.id)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_visibility", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_join_request", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_join_request", return_value=created,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_member_ids_by_roles", return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.create_notification_record",
    ) as mock_notify:
        _session_local_context(mock_session)
        submit_group_join_request(
            token="t", group_id=group.id, request=CreateGroupJoinRequest()
        )

    mock_notify.assert_not_called()


def test_approve_join_request_keeps_row_lock_until_commit():
    """upsert must not commit mid-transaction: that would release the FOR UPDATE
    lock while the request is still PENDING, letting a second moderator in."""
    author = _make_author(is_admin=True)
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    join_request = _make_join_request(group_id=group.id)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_by_id",
        return_value=join_request,
    ) as mock_get, patch(
        # A MagicMock session makes every ban lookup return a row; the ban
        # cases have their own tests in test_group_bans.py.
        "pecha_api.plans.groups.groups_service.get_group_ban_expiry",
        return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_join",
    ) as mock_join, patch(
        "pecha_api.plans.groups.groups_service.save_join_request",
    ):
        _session_local_context(mock_session)
        approve_group_join_request(
            token="t", group_id=group.id, request_id=join_request.id
        )

    assert mock_get.call_args.kwargs["for_update"] is True
    assert mock_join.call_args.kwargs["commit"] is False


def test_submit_join_request_locks_group_against_concurrent_publish():
    """Publication must not flip the group public between our read and insert."""
    user = MagicMock()
    user.id = uuid4()
    user.firstname = "Tenzin"
    user.lastname = "Tib"
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    created = _make_join_request(group_id=group.id, user_id=user.id)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_visibility", return_value=False,
    ) as mock_lock, patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.has_pending_join_request", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_join_request", return_value=created,
    ), patch(
        "pecha_api.plans.groups.groups_service.list_group_member_ids_by_roles", return_value=[],
    ):
        _session_local_context(mock_session)
        submit_group_join_request(
            token="t", group_id=group.id, request=CreateGroupJoinRequest()
        )

    mock_lock.assert_called_once()


def test_submit_join_request_rejects_group_published_under_us():
    """The locked read is authoritative, not the earlier unlocked one."""
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.assert_user_not_banned_from_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_visibility", return_value=True,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_join_request",
    ) as mock_create:
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            submit_group_join_request(
                token="t", group_id=group.id, request=CreateGroupJoinRequest()
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "public" in exc.value.detail
    mock_create.assert_not_called()


def test_group_detail_exposes_my_pending_join_request():
    """The app renders the button from this, so a pending request must show."""
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_status_map",
        return_value={group.id: "PENDING"},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_room_by_group_id", return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ):
        _session_local_context(mock_session)
        result = get_author_group_detail(group_id=group.id, token="t")

    assert result.my_join_request_status == AuthorGroupJoinRequestStatus.PENDING


def test_group_detail_status_is_none_for_anonymous():
    group = _make_group(is_public=True)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_status_map",
    ) as mock_map, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_series_by_group_id", return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_plans_by_group_id", return_value=[],
    ):
        _session_local_context(mock_session)
        result = get_author_group_detail(group_id=group.id)

    assert result.my_join_request_status is None
    mock_map.assert_not_called()


def test_group_listing_exposes_join_request_status_per_group():
    user = MagicMock()
    user.id = uuid4()
    requested = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)
    untouched = _make_group(is_public=False, group_type=AuthorGroupType.COMMUNITY)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_ids_by_user", return_value=[],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([requested, untouched], 2),
    ), patch(
        "pecha_api.plans.groups.groups_service.filter_items_for_timezone",
        side_effect=lambda items, **kw: items,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_status_map",
        return_value={requested.id: "PENDING"},
    ):
        _session_local_context(mock_session)
        result = list_public_groups(skip=0, limit=20, token="t")

    by_id = {g.id: g.my_join_request_status for g in result.groups}
    assert by_id[requested.id] == AuthorGroupJoinRequestStatus.PENDING
    assert by_id[untouched.id] is None


# --- Group publish/draft status ---
# status decides whether a group reaches the app; is_public decides how a
# published group behaves.


def test_create_author_group_defaults_to_draft_status():
    author = _make_author()
    created = _make_group(group_status=AuthorGroupStatus.DRAFT)
    created.metadata_entries = []

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_slug", return_value=None,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group", return_value=created,
    ) as mock_create, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=created,
    ):
        _session_local_context(mock_session)
        result = create_author_group(
            token="t",
            request=CreateAuthorGroupRequest(slug="s", metadata=[_metadata_input()]),
        )

    # Left at the model default, so a new group is never live until published.
    assert mock_create.call_args.kwargs["group"].status is None
    assert result.status == AuthorGroupStatus.DRAFT


def test_update_group_status_publishes_as_owner():
    author = _make_author()
    group = _make_group(group_status=AuthorGroupStatus.DRAFT)
    group.metadata_entries = []

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=AuthorGroupMemberRole.OWNER),
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_status",
    ), patch(
        "pecha_api.plans.groups.groups_service.update_group",
    ) as mock_update, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ):
        _session_local_context(mock_session)
        result = update_group_status(
            token="t",
            group_id=group.id,
            request=UpdateAuthorGroupStatusRequest(status=AuthorGroupStatus.PUBLISHED),
        )

    assert mock_update.call_args.kwargs["group"].status == AuthorGroupStatus.PUBLISHED
    assert result.status == AuthorGroupStatus.PUBLISHED


def test_update_group_status_allows_admin():
    author = _make_author()
    group = _make_group(group_status=AuthorGroupStatus.DRAFT)
    group.metadata_entries = []

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=AuthorGroupMemberRole.ADMIN),
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_status",
    ), patch(
        "pecha_api.plans.groups.groups_service.update_group",
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ):
        _session_local_context(mock_session)
        result = update_group_status(
            token="t",
            group_id=group.id,
            request=UpdateAuthorGroupStatusRequest(status=AuthorGroupStatus.PUBLISHED),
        )

    assert result.status == AuthorGroupStatus.PUBLISHED


@pytest.mark.parametrize(
    "role", [AuthorGroupMemberRole.AUTHOR, AuthorGroupMemberRole.VIEWER]
)
def test_update_group_status_rejects_non_settings_roles(role):
    author = _make_author()
    group = _make_group(group_status=AuthorGroupStatus.DRAFT)

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=role),
    ), patch(
        "pecha_api.plans.groups.groups_service.update_group",
    ) as mock_update:
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            update_group_status(
                token="t",
                group_id=group.id,
                request=UpdateAuthorGroupStatusRequest(status=AuthorGroupStatus.PUBLISHED),
            )

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_update.assert_not_called()


def test_update_group_status_not_found():
    author = _make_author()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=None,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            update_group_status(
                token="t",
                group_id=uuid4(),
                request=UpdateAuthorGroupStatusRequest(status=AuthorGroupStatus.PUBLISHED),
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_update_group_status_leaves_is_public_untouched():
    """Publishing must not change public/private behaviour."""
    author = _make_author()
    group = _make_group(is_public=False, group_status=AuthorGroupStatus.DRAFT)
    group.metadata_entries = []

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_member",
        return_value=MagicMock(role=AuthorGroupMemberRole.OWNER),
    ), patch(
        "pecha_api.plans.groups.groups_service.lock_group_status",
    ), patch(
        "pecha_api.plans.groups.groups_service.update_group",
    ) as mock_update, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ):
        _session_local_context(mock_session)
        result = update_group_status(
            token="t",
            group_id=group.id,
            request=UpdateAuthorGroupStatusRequest(status=AuthorGroupStatus.PUBLISHED),
        )

    assert mock_update.call_args.kwargs["group"].is_public is False
    assert result.is_public is False
    assert result.status == AuthorGroupStatus.PUBLISHED


def test_list_public_groups_filters_to_published_only():
    group = _make_group(group_type=AuthorGroupType.COMMUNITY)
    group.metadata_entries = []
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([group], 1),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.filter_items_for_timezone",
        side_effect=lambda items, **kw: items,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ):
        _session_local_context(mock_session)
        list_public_groups(skip=0, limit=10)

    assert mock_paginated.call_args.kwargs["status"] == AuthorGroupStatus.PUBLISHED
    # is_public stays unfiltered so private groups can still receive requests.
    assert mock_paginated.call_args.kwargs.get("is_public") is None


@pytest.mark.parametrize(
    "group_status", [AuthorGroupStatus.DRAFT, AuthorGroupStatus.UNPUBLISHED]
)
def test_get_author_group_detail_hides_unpublished_group(group_status):
    group = _make_group(group_status=group_status)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_author_group_detail(group_id=group.id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_get_author_group_detail_hides_draft_group_even_from_joiner():
    """Drafts are hidden from everyone app-side, joiners included."""
    group = _make_group(group_status=AuthorGroupStatus.DRAFT)
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=True,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_author_group_detail(group_id=group.id, token="t")

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_group_practices_hides_unpublished_group():
    group = _make_group(group_status=AuthorGroupStatus.DRAFT)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            await get_group_practices(group_id=group.id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_list_group_members_hides_unpublished_group():
    group = _make_group(group_status=AuthorGroupStatus.DRAFT)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            list_group_members(group_id=group.id, skip=0, limit=10)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_join_group_rejects_unpublished_group():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(group_type=AuthorGroupType.COMMUNITY, group_status=AuthorGroupStatus.DRAFT)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_join",
    ) as mock_join:
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            join_group(token="t", group_id=group.id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_join.assert_not_called()


def test_follow_group_rejects_unpublished_group():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(group_status=AuthorGroupStatus.UNPUBLISHED)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.upsert_group_follow",
    ) as mock_follow:
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            follow_group(token="t", group_id=group.id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_follow.assert_not_called()


def test_submit_group_join_request_rejects_unpublished_group():
    user = MagicMock()
    user.id = uuid4()
    group = _make_group(
        is_public=False,
        group_type=AuthorGroupType.COMMUNITY,
        group_status=AuthorGroupStatus.DRAFT,
    )
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.create_group_join_request",
    ) as mock_create:
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            submit_group_join_request(
                token="t",
                group_id=group.id,
                request=CreateGroupJoinRequest(message=None),
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_create.assert_not_called()


def test_list_joined_groups_filters_to_published():
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_ids_by_user",
        return_value=[uuid4()],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([], 0),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ):
        _session_local_context(mock_session)
        list_joined_groups(token="t", skip=0, limit=10)

    assert mock_paginated.call_args.kwargs["status"] == AuthorGroupStatus.PUBLISHED


def test_list_followed_groups_filters_to_published():
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_following_group_ids_by_user",
        return_value=[uuid4()],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([], 0),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ):
        _session_local_context(mock_session)
        list_followed_groups(token="t", skip=0, limit=10)

    assert mock_paginated.call_args.kwargs["status"] == AuthorGroupStatus.PUBLISHED


def test_list_cms_groups_does_not_filter_status_by_default():
    """Studio must keep seeing drafts — the gate is app-side only."""
    author = _make_author(is_admin=True)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([], 0),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_member_roles_map", return_value={},
    ):
        _session_local_context(mock_session)
        list_cms_groups(token="t", skip=0, limit=10)

    assert mock_paginated.call_args.kwargs["status"] is None


def test_get_cms_group_detail_returns_draft_group_to_member():
    author = _make_author(is_admin=True)
    group = _make_group(group_status=AuthorGroupStatus.DRAFT)
    group.metadata_entries = []

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_author_details",
        return_value=author,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ):
        _session_local_context(mock_session)
        result = get_cms_group_detail(token="t", group_id=group.id)

    assert result.status == AuthorGroupStatus.DRAFT


def test_published_private_group_still_uses_teaser_flow():
    """Regression guard: a published private group still shows as a teaser."""
    group = _make_group(is_public=False, group_status=AuthorGroupStatus.PUBLISHED)
    group.metadata_entries = []
    user = MagicMock()
    user.id = uuid4()

    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ), patch(
        "pecha_api.plans.groups.groups_service.is_user_joined_group", return_value=False,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_join_request_status_map", return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_room_by_group_id", return_value=None,
    ):
        _session_local_context(mock_session)
        result = get_author_group_detail(group_id=group.id, token="t")

    assert result.is_public is False
    assert result.members == []
    assert result.series == []


def test_get_group_accumulations_hides_unpublished_group():
    group = _make_group(group_status=AuthorGroupStatus.DRAFT)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_group_accumulations(group_id=group.id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_get_group_member_accumulations_hides_unpublished_group():
    group = _make_group(group_status=AuthorGroupStatus.UNPUBLISHED)
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.get_group_by_id", return_value=group,
    ):
        _session_local_context(mock_session)
        with pytest.raises(HTTPException) as exc:
            get_group_member_accumulations(group_id=group.id, accumulation_id=uuid4())

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
