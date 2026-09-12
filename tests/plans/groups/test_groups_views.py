from datetime import datetime, timezone, timedelta
from uuid import uuid4
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.plans.groups.groups_enums import (
    AuthorGroupMemberRole,
    AuthorGroupStatus,
    AuthorGroupType,
)
from pecha_api.plans.plans_enums import PlanStatus
from pecha_api.plans.groups.groups_response_models import (
    AuthorGroupDetailDTO,
    AuthorGroupListResponse,
    AuthorGroupSummaryDTO,
    GroupAccumulationsResponse,
    GroupInviteCreatedResponse,
    GroupMantraAccumulationDTO,
    GroupMemberAccumulationDTO,
    GroupMemberAccumulationsResponse,
    GroupMetadataDTO,
    GroupPracticeCardDTO,
    GroupPracticeFeedItemDTO,
    GroupPracticesFeedResponse,
    GroupPracticesResponse,
    GroupPracticeType,
    GroupSeriesListItemDTO,
    UserFollowedAuthorGroupDTO,
    UserFollowedAuthorGroupListResponse,
    UserJoinedAuthorGroupDTO,
    UserJoinedAuthorGroupListResponse,
    AuthorGroupMemberProfileDTO,
    AuthorGroupMembersListResponse,
)
from pecha_api.group_accumulator.group_accumulator_response_models import GroupAccumulatorDTO
from pecha_api.group_recitation_collection.response_models import GroupRecitationCollectionDTO
client = TestClient(api)


def _metadata() -> list[GroupMetadataDTO]:
    return [
        GroupMetadataDTO(
            id=uuid4(),
            title="Bodhichitta Authors",
            description="Meditation and Dharma writers",
            language="EN",
        )
    ]


def _group_detail() -> AuthorGroupDetailDTO:
    return AuthorGroupDetailDTO(
        id=uuid4(),
        slug="bodhichitta-authors",
        group_type=AuthorGroupType.PAGE,
        is_public=True,
        metadata=_metadata(),
        members=[],
        tags=[],
        social_links=[],
        series=[],
        plans=[],
        follower_count=0,
    )


def test_create_cms_group_success():
    group_detail = _group_detail()
    payload = {
        "slug": "bodhichitta-authors",
        "is_public": True,
        "metadata": [{"title": "Bodhichitta Authors", "description": "Dharma", "language": "EN"}],
    }
    with patch(
        "pecha_api.plans.groups.groups_views.create_author_group",
        return_value=group_detail,
    ) as mock_service:
        response = client.post(
            "/cms/author/groups",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    mock_service.assert_called_once()
    assert response.json()["slug"] == "bodhichitta-authors"


def test_get_public_groups_success():
    group_summary = AuthorGroupSummaryDTO(
        id=uuid4(),
        slug="bodhichitta-authors",
        group_type=AuthorGroupType.PAGE,
        is_public=True,
        metadata=_metadata(),
        tags=[],
        follower_count=4,
        member_count=2,
    )
    response_model = AuthorGroupListResponse(groups=[group_summary], skip=0, limit=20, total=1)
    with patch(
        "pecha_api.plans.groups.groups_views.list_public_groups",
        return_value=response_model,
    ) as mock_service:
        response = client.get("/author/groups")

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        search=None,
        language=None,
        tag_id=None,
        group_type=AuthorGroupType.COMMUNITY,
        skip=0,
        limit=20,
        token=None,
        timezone_name=None,
    )
    assert response.json()["total"] == 1


def test_get_public_groups_with_auth_passes_token():
    group_summary = AuthorGroupSummaryDTO(
        id=uuid4(),
        slug="bodhichitta-authors",
        group_type=AuthorGroupType.PAGE,
        is_public=True,
        metadata=_metadata(),
        tags=[],
        follower_count=4,
        member_count=2,
    )
    response_model = AuthorGroupListResponse(groups=[group_summary], skip=0, limit=20, total=1)
    with patch(
        "pecha_api.plans.groups.groups_views.list_public_groups",
        return_value=response_model,
    ) as mock_service:
        response = client.get("/author/groups", headers={"Authorization": "Bearer dummy"})

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        search=None,
        language=None,
        tag_id=None,
        group_type=AuthorGroupType.COMMUNITY,
        skip=0,
        limit=20,
        token="dummy",
        timezone_name=None,
    )


def test_get_public_groups_with_auth_excludes_joined_groups_through_service():
    joined_group_id = uuid4()
    user = MagicMock()
    user.id = uuid4()
    with patch("pecha_api.plans.groups.groups_service.SessionLocal") as mock_session, patch(
        "pecha_api.plans.groups.groups_service.validate_and_extract_user_details",
        return_value=user,
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joined_group_ids_by_user",
        return_value=[joined_group_id],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_groups_paginated",
        return_value=([], 0),
    ) as mock_paginated, patch(
        "pecha_api.plans.groups.groups_service.get_followers_count_map",
        return_value={},
    ), patch(
        "pecha_api.plans.groups.groups_service.get_joiners_count_map",
        return_value={},
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_session.return_value.__exit__.return_value = False
        response = client.get("/author/groups", headers={"Authorization": "Bearer dummy"})

    assert response.status_code == status.HTTP_200_OK
    assert mock_paginated.call_args.kwargs["exclude_group_ids"] == [joined_group_id]
    assert response.json()["total"] == 0


def test_create_group_invite_success():
    from pecha_api.plans.groups.groups_enums import AuthorGroupInviteStatus
    from pecha_api.plans.groups.groups_response_models import GroupInviteDTO

    group_id = uuid4()
    invite_id = uuid4()
    invite_dto = GroupInviteDTO(
        id=invite_id,
        group_id=group_id,
        group_name="Bodhichitta Authors",
        target_email="author@example.org",
        role=AuthorGroupMemberRole.AUTHOR,
        status=AuthorGroupInviteStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        created_at=datetime.now(timezone.utc),
        created_by="owner@example.org",
        inviter_name="Group Owner",
        inviter_email="owner@example.org",
    )
    invite_response = GroupInviteCreatedResponse(
        invite=invite_dto,
        notification_id=uuid4(),
    )
    payload = {"target_email": "author@example.org", "role": "AUTHOR"}
    with patch(
        "pecha_api.plans.groups.groups_views.create_group_member_invite",
        return_value=invite_response,
    ) as mock_service:
        response = client.post(
            f"/cms/author/groups/{group_id}/members/invites",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["invite"]["id"] == str(invite_id)
    mock_service.assert_called_once()


def test_get_my_pending_group_invites_delegates_to_service():
    from pecha_api.plans.groups.groups_response_models import GroupInviteListResponse

    with patch(
        "pecha_api.plans.groups.groups_views.list_my_pending_group_invites",
        return_value=GroupInviteListResponse(invites=[], total=0),
    ) as mock_service:
        response = client.get(
            "/cms/author/groups/invites/me",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(token="dummy")


def test_reject_group_invite_by_id_delegates_to_service():
    from pecha_api.plans.groups.groups_enums import AuthorGroupInviteStatus
    from pecha_api.plans.groups.groups_response_models import GroupInviteDTO

    invite_id = uuid4()
    invite_dto = GroupInviteDTO(
        id=invite_id,
        group_id=uuid4(),
        group_name="Test Group",
        target_email="invitee@example.org",
        role=AuthorGroupMemberRole.AUTHOR,
        status=AuthorGroupInviteStatus.REJECTED,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        created_at=datetime.now(timezone.utc),
        created_by="owner@example.org",
        inviter_name="Group Owner",
        inviter_email="owner@example.org",
    )
    with patch(
        "pecha_api.plans.groups.groups_views.reject_group_invite_by_id",
        return_value=invite_dto,
    ) as mock_service:
        response = client.post(
            f"/cms/author/groups/invites/{invite_id}/reject",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(token="dummy", invite_id=invite_id)


def test_accept_group_invite_by_id_delegates_to_service():
    invite_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.accept_group_invite_by_id",
        return_value=_group_detail(),
    ) as mock_service:
        response = client.post(
            f"/cms/author/groups/invites/{invite_id}/accept",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once()


def test_put_cms_group_delegates_to_service():
    group_id = uuid4()
    detail = _group_detail()
    with patch(
        "pecha_api.plans.groups.groups_views.update_author_group",
        return_value=detail,
    ) as mock_service:
        response = client.put(
            f"/cms/author/groups/{group_id}",
            json={"slug": "updated-slug", "is_public": False},
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once()


def test_patch_cms_group_delegates_to_service():
    group_id = uuid4()
    detail = _group_detail()
    with patch(
        "pecha_api.plans.groups.groups_views.update_author_group",
        return_value=detail,
    ) as mock_service:
        response = client.patch(
            f"/cms/author/groups/{group_id}",
            json={"slug": "updated-slug"},
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once()


def test_delete_cms_group_delegates_to_service():
    group_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.delete_author_group",
    ) as mock_service:
        response = client.delete(
            f"/cms/author/groups/{group_id}",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_service.assert_called_once_with(token="dummy", group_id=group_id)


def test_get_cms_group_by_id():
    group_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.get_cms_group_detail",
        return_value=_group_detail(),
    ) as mock_service:
        response = client.get(
            f"/cms/author/groups/{group_id}",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once()


def test_get_cms_groups_with_filters():
    summary = AuthorGroupSummaryDTO(
        id=uuid4(),
        slug="g",
        group_type=AuthorGroupType.PAGE,
        is_public=True,
        metadata=_metadata(),
        tags=[],
        follower_count=0,
        member_count=1,
    )
    listing = AuthorGroupListResponse(groups=[summary], skip=5, limit=10, total=1)
    tag_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.list_cms_groups",
        return_value=listing,
    ) as mock_service:
        response = client.get(
            f"/cms/author/groups?search=foo&language=EN&skip=5&limit=10&tag_id={tag_id}",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        token="dummy",
        search="foo",
        language="EN",
        tag_id=tag_id,
        is_public=None,
        group_type=None,
        group_status=None,
        for_transfer=False,
        skip=5,
        limit=10,
    )


def test_put_cms_group_relations():
    group_id = uuid4()
    detail = _group_detail()
    tag_id = uuid4()
    plan_id = uuid4()
    series_id = uuid4()
    headers = {"Authorization": "Bearer dummy"}

    with patch("pecha_api.plans.groups.groups_views.replace_group_tags", return_value=detail) as mock_tags:
        assert client.put(f"/cms/author/groups/{group_id}/tags", json={"tag_ids": [str(tag_id)]}, headers=headers).status_code == 200
        mock_tags.assert_called_once()

    with patch(
        "pecha_api.plans.groups.groups_views.replace_group_social_links_by_id",
        return_value=detail,
    ) as mock_links:
        assert (
            client.put(
                f"/cms/author/groups/{group_id}/social-links",
                json={"social_links": [{"platform": "x", "url": "https://x.com/g"}]},
                headers=headers,
            ).status_code
            == 200
        )
        mock_links.assert_called_once()


def test_revoke_invite_and_member_endpoints():
    group_id = uuid4()
    invite_id = uuid4()
    author_id = uuid4()
    headers = {"Authorization": "Bearer dummy"}

    with patch("pecha_api.plans.groups.groups_views.revoke_group_invite") as mock_revoke:
        response = client.post(f"/cms/author/groups/{group_id}/members/invites/{invite_id}/revoke", headers=headers)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_revoke.assert_called_once()

    with patch("pecha_api.plans.groups.groups_views.update_group_member_role", return_value=_group_detail()) as mock_role:
        response = client.patch(
            f"/cms/author/groups/{group_id}/members/{author_id}/role",
            json={"role": "ADMIN"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_200_OK
        mock_role.assert_called_once()

    with patch("pecha_api.plans.groups.groups_views.delete_group_member") as mock_delete:
        response = client.delete(f"/cms/author/groups/{group_id}/members/{author_id}", headers=headers)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_delete.assert_called_once()


def test_get_public_group_by_id():
    group_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.get_author_group_detail",
        return_value=_group_detail(),
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.json()["slug"] == "bodhichitta-authors"
    mock_service.assert_called_once_with(group_id=group_id, language=None, token=None)


def test_get_public_group_by_id_with_language():
    group_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.get_author_group_detail",
        return_value=_group_detail(),
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}?language=bo")
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(group_id=group_id, language="bo", token=None)


def test_get_public_group_members():
    group_id = uuid4()
    response_model = AuthorGroupMembersListResponse(
        total_members=1,
        list=[
            AuthorGroupMemberProfileDTO(
                username="alice",
                fullname="Alice Smith",
                avatar_url="https://example.com/avatar.webp",
            )
        ],
        skip=0,
        limit=20,
    )
    with patch(
        "pecha_api.plans.groups.groups_views.list_group_members",
        return_value=response_model,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/members?skip=0&limit=20")
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(group_id=group_id, skip=0, limit=20)
    body = response.json()
    assert body["total_members"] == 1
    assert body["list"][0]["username"] == "alice"
    assert body["list"][0]["fullname"] == "Alice Smith"
    assert body["list"][0]["avatar_url"] == "https://example.com/avatar.webp"


def test_get_public_group_practices():
    group_id = uuid4()
    practices_response = GroupPracticesResponse(
        practices=[
            GroupPracticeCardDTO(
                type=GroupPracticeType.SERIES,
                series=GroupSeriesListItemDTO(
                    id=uuid4(),
                    author_id=uuid4(),
                    featured=False,
                    status=PlanStatus.PUBLISHED,
                ),
            ),
            GroupPracticeCardDTO(
                type=GroupPracticeType.ACCUMULATOR,
                accumulator=GroupAccumulatorDTO(
                    id=uuid4(),
                    group_id=group_id,
                    title="Om Mani Padme Hum",
                    member_count=3,
                    created_at=datetime.now(timezone.utc),
                ),
            ),
            GroupPracticeCardDTO(
                type=GroupPracticeType.COLLECTION,
                collection=GroupRecitationCollectionDTO(
                    id=uuid4(),
                    group_id=group_id,
                    name="Morning Recitations",
                    item_count=5,
                    created_at=datetime.now(timezone.utc).isoformat(),
                ),
            ),
        ],
        skip=0,
        limit=20,
        total=3,
    )
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_practices",
        return_value=practices_response,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/practices?skip=0&limit=20")
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        group_id=group_id,
        skip=0,
        limit=20,
        language=None,
        token=None,
        timezone_name=None,
    )
    body = response.json()
    assert body["total"] == 3
    types = {card["type"] for card in body["practices"]}
    assert types == {"series", "accumulator", "collection"}


def test_get_group_practices_feed_success():
    group_id = uuid4()
    feed_response = GroupPracticesFeedResponse(
        practices=[
            GroupPracticeFeedItemDTO(
                type=GroupPracticeType.ACCUMULATOR,
                practice_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                is_joined=True,
                group_id=group_id,
                group_name="Test Group",
                group_slug="test-group",
                accumulator=GroupAccumulatorDTO(
                    id=uuid4(),
                    group_id=group_id,
                    title="Om Mani Padme Hum",
                    member_count=3,
                    created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                ),
            ),
        ],
        skip=0,
        limit=20,
        total=1,
        include_unfollowed=False,
    )
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_practices_feed",
        return_value=feed_response,
    ) as mock_service:
        response = client.get(
            "/author/groups/practices",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        token="dummy",
        group_id=None,
        should_include_unfollowed=False,
        skip=0,
        limit=20,
        language=None,
        timezone_name=None,
    )
    body = response.json()
    assert body["total"] == 1
    assert body["include_unfollowed"] is False
    assert body["practices"][0]["type"] == "accumulator"
    assert body["practices"][0]["is_joined"] is True
    assert body["practices"][0]["group_name"] == "Test Group"


def test_get_group_practices_feed_passes_filters():
    group_id = uuid4()
    feed_response = GroupPracticesFeedResponse(
        practices=[], skip=5, limit=10, total=0, include_unfollowed=True
    )
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_practices_feed",
        return_value=feed_response,
    ) as mock_service:
        response = client.get(
            f"/author/groups/practices?group_id={group_id}&include_unfollowed=true&skip=5&limit=10&language=en",
            headers={"Authorization": "Bearer dummy", "X-Timezone": "Asia/Kolkata"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        token="dummy",
        group_id=group_id,
        should_include_unfollowed=True,
        skip=5,
        limit=10,
        language="en",
        timezone_name="Asia/Kolkata",
    )


def test_get_group_practices_feed_allows_guest():
    feed_response = GroupPracticesFeedResponse(
        practices=[], skip=0, limit=20, total=0, include_unfollowed=False
    )
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_practices_feed",
        return_value=feed_response,
    ) as mock_service:
        response = client.get("/author/groups/practices")
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        token=None,
        group_id=None,
        should_include_unfollowed=False,
        skip=0,
        limit=20,
        language=None,
        timezone_name=None,
    )


def test_follow_and_unfollow_group():
    group_id = uuid4()
    headers = {"Authorization": "Bearer dummy"}
    with patch("pecha_api.plans.groups.groups_views.follow_group") as mock_follow:
        assert client.post(f"/author/groups/{group_id}/follow", headers=headers).status_code == status.HTTP_204_NO_CONTENT
        mock_follow.assert_called_once()
    with patch("pecha_api.plans.groups.groups_views.unfollow_group") as mock_unfollow:
        assert client.delete(f"/author/groups/{group_id}/follow", headers=headers).status_code == status.HTTP_204_NO_CONTENT
        mock_unfollow.assert_called_once()


def test_get_my_followed_groups():
    listing = UserFollowedAuthorGroupListResponse(groups=[], skip=0, limit=20, total=0)
    with patch(
        "pecha_api.plans.groups.groups_views.list_followed_groups",
        return_value=listing,
    ) as mock_service:
        response = client.get(
            "/users/me/following/author/groups?skip=0&limit=20&language=bo",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(token="dummy", skip=0, limit=20, language="bo")


def test_get_my_followed_group_by_id():
    group_id = uuid4()
    group_summary = UserFollowedAuthorGroupDTO(
        id=group_id,
        metadata=_metadata(),
        tags=[],
        follower_count=4,
    )
    with patch(
        "pecha_api.plans.groups.groups_views.get_followed_group",
        return_value=group_summary,
    ) as mock_service:
        response = client.get(
            f"/users/me/following/author/groups?group_id={group_id}&language=bo",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == str(group_id)
    mock_service.assert_called_once_with(token="dummy", group_id=group_id, language="bo")


def test_join_and_leave_group():
    group_id = uuid4()
    headers = {"Authorization": "Bearer dummy"}
    with patch("pecha_api.plans.groups.groups_views.join_group") as mock_join:
        assert client.post(f"/author/groups/{group_id}/join", headers=headers).status_code == status.HTTP_204_NO_CONTENT
        mock_join.assert_called_once()
    with patch("pecha_api.plans.groups.groups_views.leave_group") as mock_leave:
        assert client.delete(f"/author/groups/{group_id}/join", headers=headers).status_code == status.HTTP_204_NO_CONTENT
        mock_leave.assert_called_once()


def test_get_my_joined_groups():
    listing = UserJoinedAuthorGroupListResponse(groups=[], skip=0, limit=20, total=0)
    with patch(
        "pecha_api.plans.groups.groups_views.list_joined_groups",
        return_value=listing,
    ) as mock_service:
        response = client.get(
            "/users/me/joined/author/groups?skip=0&limit=20&language=bo",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(token="dummy", skip=0, limit=20, language="bo")


def test_get_my_joined_group_by_id():
    group_id = uuid4()
    group_summary = UserJoinedAuthorGroupDTO(
        id=group_id,
        metadata=_metadata(),
        tags=[],
        joiner_count=2,
    )
    with patch(
        "pecha_api.plans.groups.groups_views.get_joined_group",
        return_value=group_summary,
    ) as mock_service:
        response = client.get(
            f"/users/me/joined/author/groups?group_id={group_id}&language=bo",
            headers={"Authorization": "Bearer dummy"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == str(group_id)
    mock_service.assert_called_once_with(token="dummy", group_id=group_id, language="bo")


def test_get_group_accumulations_success():
    """Test getting group accumulations with mantras"""
    group_id = uuid4()
    mantra_id_1 = uuid4()
    mantra_id_2 = uuid4()
    
    response_model = GroupAccumulationsResponse(
        group_id=group_id,
        mantras=[
            GroupMantraAccumulationDTO(
                mantra_id=mantra_id_1,
                mantra_slug="medicine-buddha",
                mantra_title="Medicine Buddha Mantra",
                count=1200,
            ),
            GroupMantraAccumulationDTO(
                mantra_id=mantra_id_2,
                mantra_slug="chenrezig",
                mantra_title="Chenrezig Mantra",
                count=800,
            ),
        ],
        total_count=2000,
        total=2,
        skip=0,
        limit=20,
    )
    
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_accumulations",
        return_value=response_model,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/accumulations")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["group_id"] == str(group_id)
    assert data["total_count"] == 2000
    assert data["total"] == 2
    assert len(data["mantras"]) == 2
    assert data["mantras"][0]["count"] == 1200
    assert data["mantras"][0]["mantra_title"] == "Medicine Buddha Mantra"
    mock_service.assert_called_once_with(
        group_id=group_id,
        language=None,
        skip=0,
        limit=20,
    )


def test_get_group_accumulations_with_language():
    """Test getting group accumulations with language parameter"""
    group_id = uuid4()
    mantra_id = uuid4()
    
    response_model = GroupAccumulationsResponse(
        group_id=group_id,
        mantras=[
            GroupMantraAccumulationDTO(
                mantra_id=mantra_id,
                mantra_slug="tara",
                mantra_title="སྒྲོལ་མའི་སྔགས།",
                count=500,
            ),
        ],
        total_count=500,
        total=1,
        skip=0,
        limit=20,
    )
    
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_accumulations",
        return_value=response_model,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/accumulations?language=bo")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["mantras"][0]["mantra_title"] == "སྒྲོལ་མའི་སྔགས།"
    mock_service.assert_called_once_with(
        group_id=group_id,
        language="bo",
        skip=0,
        limit=20,
    )


def test_get_group_accumulations_empty():
    """Test getting group accumulations when group has no mantras"""
    group_id = uuid4()
    
    response_model = GroupAccumulationsResponse(
        group_id=group_id,
        mantras=[],
        total_count=0,
        total=0,
        skip=0,
        limit=20,
    )
    
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_accumulations",
        return_value=response_model,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/accumulations")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total_count"] == 0
    assert data["total"] == 0
    assert len(data["mantras"]) == 0


def test_get_group_accumulations_with_pagination():
    """Test getting group accumulations with pagination"""
    group_id = uuid4()
    mantra_id = uuid4()
    
    response_model = GroupAccumulationsResponse(
        group_id=group_id,
        mantras=[
            GroupMantraAccumulationDTO(
                mantra_id=mantra_id,
                mantra_slug="manjushri",
                mantra_title="Manjushri Mantra",
                count=300,
            ),
        ],
        total_count=5000,
        total=10,
        skip=5,
        limit=1,
    )
    
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_accumulations",
        return_value=response_model,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/accumulations?skip=5&limit=1")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["skip"] == 5
    assert data["limit"] == 1
    assert data["total"] == 10
    assert data["total_count"] == 5000
    assert len(data["mantras"]) == 1
    mock_service.assert_called_once_with(
        group_id=group_id,
        language=None,
        skip=5,
        limit=1,
    )


def test_get_group_member_accumulations_success():
    """Test getting member contributions for a group accumulator"""
    group_id = uuid4()
    accumulation_id = uuid4()
    
    response_model = GroupMemberAccumulationsResponse(
        total_members=3,
        list=[
            GroupMemberAccumulationDTO(
                username="user1",
                fullname="John Doe",
                avatar_url="https://example.com/avatar1.jpg",
                count=500,
            ),
            GroupMemberAccumulationDTO(
                username="user2",
                fullname="Jane Smith",
                avatar_url="https://example.com/avatar2.jpg",
                count=300,
            ),
            GroupMemberAccumulationDTO(
                username=None,
                fullname="Bob Wilson",
                avatar_url=None,
                count=200,
            ),
        ],
        skip=0,
        limit=20,
    )
    
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_member_accumulations",
        return_value=response_model,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/accumulations/{accumulation_id}/members")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total_members"] == 3
    assert len(data["list"]) == 3
    assert data["list"][0]["username"] == "user1"
    assert data["list"][0]["fullname"] == "John Doe"
    assert data["list"][0]["count"] == 500
    assert data["list"][2]["username"] is None
    mock_service.assert_called_once_with(
        group_id=group_id,
        accumulation_id=accumulation_id,
        skip=0,
        limit=20,
    )


def test_get_group_member_accumulations_empty():
    """Test getting member contributions when no members have contributed"""
    group_id = uuid4()
    accumulation_id = uuid4()
    
    response_model = GroupMemberAccumulationsResponse(
        total_members=0,
        list=[],
        skip=0,
        limit=20,
    )
    
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_member_accumulations",
        return_value=response_model,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/accumulations/{accumulation_id}/members")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total_members"] == 0
    assert len(data["list"]) == 0


def test_get_group_member_accumulations_with_pagination():
    """Test getting member contributions with pagination"""
    group_id = uuid4()
    accumulation_id = uuid4()
    
    response_model = GroupMemberAccumulationsResponse(
        total_members=100,
        list=[
            GroupMemberAccumulationDTO(
                username="user10",
                fullname="Member Ten",
                avatar_url="https://example.com/avatar10.jpg",
                count=150,
            ),
        ],
        skip=10,
        limit=1,
    )
    
    with patch(
        "pecha_api.plans.groups.groups_views.get_group_member_accumulations",
        return_value=response_model,
    ) as mock_service:
        response = client.get(f"/author/groups/{group_id}/accumulations/{accumulation_id}/members?skip=10&limit=1")
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total_members"] == 100
    assert data["skip"] == 10
    assert data["limit"] == 1
    assert len(data["list"]) == 1
    mock_service.assert_called_once_with(
        group_id=group_id,
        accumulation_id=accumulation_id,
        skip=10,
        limit=1,
    )


def _join_request_dto(request_status=None):
    from pecha_api.plans.groups.groups_enums import AuthorGroupJoinRequestStatus
    from pecha_api.plans.groups.groups_response_models import GroupJoinRequestDTO

    return GroupJoinRequestDTO(
        id=uuid4(),
        status=request_status or AuthorGroupJoinRequestStatus.PENDING,
    )


def test_post_group_join_request_delegates_to_service():
    group_id = uuid4()
    dto = _join_request_dto()

    with patch(
        "pecha_api.plans.groups.groups_views.submit_group_join_request",
        return_value=dto,
    ) as mock_service:
        response = client.post(
            f"/author/groups/{group_id}/join-requests",
            json={"message": "let me in"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["status"] == "PENDING"
    assert mock_service.call_args.kwargs["request"].message == "let me in"


def test_post_group_join_request_allows_omitted_message():
    group_id = uuid4()

    with patch(
        "pecha_api.plans.groups.groups_views.submit_group_join_request",
        return_value=_join_request_dto(),
    ) as mock_service:
        response = client.post(
            f"/author/groups/{group_id}/join-requests",
            json={},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert mock_service.call_args.kwargs["request"].message is None


def test_post_group_join_request_rejects_overlong_message():
    group_id = uuid4()

    with patch(
        "pecha_api.plans.groups.groups_views.submit_group_join_request",
    ) as mock_service:
        response = client.post(
            f"/author/groups/{group_id}/join-requests",
            json={"message": "x" * 1001},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    mock_service.assert_not_called()


def test_post_group_join_request_requires_auth():
    response = client.post(f"/author/groups/{uuid4()}/join-requests", json={})
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_get_cms_group_join_requests_defaults_to_pending():
    from pecha_api.plans.groups.groups_enums import AuthorGroupJoinRequestStatus
    from pecha_api.plans.groups.groups_response_models import GroupJoinRequestListResponse

    group_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.list_group_join_requests",
        return_value=GroupJoinRequestListResponse(requests=[], skip=0, limit=20, total=0),
    ) as mock_service:
        response = client.get(
            f"/cms/author/groups/{group_id}/join-requests",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert (
        mock_service.call_args.kwargs["status_filter"]
        == AuthorGroupJoinRequestStatus.PENDING
    )


def test_get_cms_group_join_requests_honours_status_filter():
    from pecha_api.plans.groups.groups_enums import AuthorGroupJoinRequestStatus
    from pecha_api.plans.groups.groups_response_models import GroupJoinRequestListResponse

    group_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.list_group_join_requests",
        return_value=GroupJoinRequestListResponse(requests=[], skip=0, limit=20, total=0),
    ) as mock_service:
        response = client.get(
            f"/cms/author/groups/{group_id}/join-requests?status=APPROVED",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert (
        mock_service.call_args.kwargs["status_filter"]
        == AuthorGroupJoinRequestStatus.APPROVED
    )


def test_approve_cms_group_join_request_delegates_to_service():
    from pecha_api.plans.groups.groups_enums import AuthorGroupJoinRequestStatus

    group_id = uuid4()
    request_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.approve_group_join_request",
        return_value=_join_request_dto(AuthorGroupJoinRequestStatus.APPROVED),
    ) as mock_service:
        response = client.post(
            f"/cms/author/groups/{group_id}/join-requests/{request_id}/approve",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "APPROVED"
    mock_service.assert_called_once_with(
        token="dummy", group_id=group_id, request_id=request_id
    )


def test_reject_cms_group_join_request_delegates_to_service():
    from pecha_api.plans.groups.groups_enums import AuthorGroupJoinRequestStatus

    group_id = uuid4()
    request_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.reject_group_join_request",
        return_value=_join_request_dto(AuthorGroupJoinRequestStatus.REJECTED),
    ) as mock_service:
        response = client.post(
            f"/cms/author/groups/{group_id}/join-requests/{request_id}/reject",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "REJECTED"
    mock_service.assert_called_once_with(
        token="dummy", group_id=group_id, request_id=request_id
    )




def test_patch_cms_group_status_delegates_to_service():
    group_id = uuid4()
    detail = _group_detail()
    detail.status = AuthorGroupStatus.PUBLISHED
    with patch(
        "pecha_api.plans.groups.groups_views.update_group_status",
        return_value=detail,
    ) as mock_service:
        response = client.patch(
            f"/cms/author/groups/{group_id}/status",
            json={"status": "PUBLISHED"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "PUBLISHED"
    kwargs = mock_service.call_args.kwargs
    assert kwargs["token"] == "dummy"
    assert kwargs["group_id"] == group_id
    assert kwargs["request"].status == AuthorGroupStatus.PUBLISHED


def test_patch_cms_group_status_rejects_unknown_status():
    with patch(
        "pecha_api.plans.groups.groups_views.update_group_status",
    ) as mock_service:
        response = client.patch(
            f"/cms/author/groups/{uuid4()}/status",
            json={"status": "NOT_A_STATUS"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    mock_service.assert_not_called()


def test_get_cms_groups_passes_status_filter():
    listing = AuthorGroupListResponse(groups=[], skip=0, limit=20, total=0)
    with patch(
        "pecha_api.plans.groups.groups_views.list_cms_groups",
        return_value=listing,
    ) as mock_service:
        response = client.get(
            "/cms/author/groups?status=DRAFT",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert mock_service.call_args.kwargs["group_status"] == AuthorGroupStatus.DRAFT
