from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone as tz

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.group_posts.response_models import (
    GroupPostDTO,
    GroupPostLinkDTO,
    GroupPostMediaDTO,
    GroupPostsResponse,
)

client = TestClient(api)


def _post_dto(group_id=None, caption="Hello", post_status="PUBLISHED") -> GroupPostDTO:
    now = datetime.now(tz.utc).isoformat()
    return GroupPostDTO(
        id=uuid4(),
        group_id=group_id or uuid4(),
        caption=caption,
        status=post_status,
        published_at=now,
        media=[
            GroupPostMediaDTO(
                id=uuid4(),
                media_type="IMAGE",
                url="https://presigned.example/a.webp",
                width=1080,
                height=1350,
                display_order=1,
            )
        ],
        links=[
            GroupPostLinkDTO(
                id=uuid4(),
                type="EXTERNAL",
                url="https://example.com",
                label="Full guide",
                display_order=1,
            )
        ],
        created_at=now,
        updated_at=now,
    )


class TestPublicGroupPostsViews:

    @patch('pecha_api.group_posts.views.list_group_posts_cached', new_callable=AsyncMock)
    def test_list_group_posts(self, mock_service):
        group_id = uuid4()
        dto = _post_dto(group_id=group_id)
        mock_service.return_value = GroupPostsResponse(posts=[dto], skip=0, limit=10, total=1)

        response = client.get(f"/groups/author/{group_id}/posts?skip=0&limit=10")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert body["posts"][0]["caption"] == "Hello"
        assert body["posts"][0]["media"][0]["url"] == "https://presigned.example/a.webp"
        mock_service.assert_called_once_with(
            group_id=group_id,
            skip=0,
            limit=10,
            token=None,
        )

    @patch('pecha_api.group_posts.views.list_public_group_posts_cached', new_callable=AsyncMock)
    def test_list_public_group_posts_forwards_include_unfollowed(self, mock_service):
        mock_service.return_value = GroupPostsResponse(
            posts=[],
            skip=0,
            limit=20,
            total=0,
        )

        response = client.get("/groups/author/posts?include_unfollowed=true")

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(
            skip=0,
            limit=20,
            token=None,
            should_include_unfollowed=True,
        )

    @patch('pecha_api.group_posts.views.validate_and_extract_user_details')
    @patch('pecha_api.group_posts.views.list_public_group_posts_cached', new_callable=AsyncMock)
    def test_list_public_group_posts_uses_authenticated_user(
        self,
        mock_service,
        mock_validate_user,
    ):
        user_id = uuid4()
        mock_validate_user.return_value = MagicMock(id=user_id)
        mock_service.return_value = GroupPostsResponse(
            posts=[],
            skip=0,
            limit=20,
            total=0,
        )

        response = client.get(
            "/groups/author/posts",
            headers={"Authorization": "Bearer user-token"},
        )

        assert response.status_code == status.HTTP_200_OK
        # The token is forwarded; resolving it to a user is the cache
        # wrapper's job, and only on a miss.
        assert mock_service.call_args.kwargs["token"] == "user-token"

    @patch('pecha_api.group_posts.views.list_group_posts_cached', new_callable=AsyncMock)
    def test_list_group_posts_invalid_limit(self, mock_service):
        response = client.get(f"/groups/author/{uuid4()}/posts?limit=0")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_service.assert_not_called()

    @patch('pecha_api.group_posts.views.get_group_post_detail_cached', new_callable=AsyncMock)
    def test_get_group_post_detail(self, mock_service):
        group_id = uuid4()
        dto = _post_dto(group_id=group_id)
        mock_service.return_value = dto

        response = client.get(f"/groups/author/posts/{dto.id}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(dto.id)
        mock_service.assert_called_once_with(post_id=dto.id, token=None)

    @patch('pecha_api.group_posts.views.get_group_post_detail_cached', new_callable=AsyncMock)
    def test_get_group_post_detail_not_found(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found"
        )

        response = client.get(f"/groups/author/posts/{uuid4()}")

        assert response.status_code == status.HTTP_404_NOT_FOUND
