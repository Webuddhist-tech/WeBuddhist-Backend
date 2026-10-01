"""Tests for verse of the day comment like service."""
from datetime import datetime, timezone as tz
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.verse_of_day.comment_like_service import (
    like_verse_comment_service,
    list_verse_comment_likers_service,
    unlike_verse_comment_service,
)


class MockUser:
    def __init__(
        self,
        firstname: Optional[str] = "Sam",
        lastname: Optional[str] = "Lee",
        avatar_url: Optional[str] = None,
    ) -> None:
        self.id: UUID = uuid4()
        self.firstname = firstname
        self.lastname = lastname
        self.avatar_url = avatar_url


class MockComment:
    def __init__(self, verse_id: Optional[UUID] = None) -> None:
        self.id: UUID = uuid4()
        self.verse_id: UUID = verse_id or uuid4()


class MockLike:
    def __init__(self, user: Optional[MockUser] = None) -> None:
        self.user_id: UUID = user.id if user else uuid4()
        self.user = user
        self.created_at = datetime.now(tz.utc)


class TestLikeVerseCommentService:

    @pytest.mark.asyncio
    @patch(
        "pecha_api.verse_of_day.comment_like_service.count_comment_likes",
        new_callable=AsyncMock,
    )
    @patch(
        "pecha_api.verse_of_day.comment_like_service.create_like",
        new_callable=AsyncMock,
    )
    @patch(
        "pecha_api.verse_of_day.comment_like_service.get_comment_by_id",
        new_callable=AsyncMock,
    )
    @patch(
        "pecha_api.verse_of_day.comment_like_service._require_verse",
        new_callable=AsyncMock,
    )
    async def test_like_comment_success(
        self,
        mock_require_verse: AsyncMock,
        mock_get_comment: AsyncMock,
        mock_create_like: AsyncMock,
        mock_count: AsyncMock,
    ) -> None:
        comment = MockComment()
        user_id = uuid4()
        mock_get_comment.return_value = comment
        mock_create_like.return_value = (MockLike(), True)
        mock_count.return_value = 1

        result = await like_verse_comment_service(
            comment_id=comment.id,
            user_id=user_id,
        )

        assert result.comment_id == comment.id
        assert result.user_id == user_id
        assert result.like_count == 1
        assert result.is_new is True
        mock_require_verse.assert_awaited_once_with(comment.verse_id)

    @pytest.mark.asyncio
    @patch(
        "pecha_api.verse_of_day.comment_like_service.get_comment_by_id",
        new_callable=AsyncMock,
    )
    async def test_like_comment_not_found(self, mock_get_comment: AsyncMock) -> None:
        mock_get_comment.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await like_verse_comment_service(comment_id=uuid4(), user_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail == NOT_FOUND


class TestUnlikeVerseCommentService:

    @pytest.mark.asyncio
    @patch(
        "pecha_api.verse_of_day.comment_like_service.delete_like",
        new_callable=AsyncMock,
    )
    @patch(
        "pecha_api.verse_of_day.comment_like_service.get_comment_by_id",
        new_callable=AsyncMock,
    )
    @patch(
        "pecha_api.verse_of_day.comment_like_service._require_verse",
        new_callable=AsyncMock,
    )
    async def test_unlike_comment_success(
        self,
        mock_require_verse: AsyncMock,
        mock_get_comment: AsyncMock,
        mock_delete_like: AsyncMock,
    ) -> None:
        comment = MockComment()
        user_id = uuid4()
        mock_get_comment.return_value = comment

        await unlike_verse_comment_service(comment_id=comment.id, user_id=user_id)

        mock_delete_like.assert_awaited_once_with(
            comment_id=comment.id,
            user_id=user_id,
        )
        mock_require_verse.assert_awaited_once_with(comment.verse_id)


class TestListVerseCommentLikersService:

    @pytest.mark.asyncio
    @patch(
        "pecha_api.verse_of_day.comment_like_service.generate_presigned_access_url",
        return_value="https://example.com/avatar.jpg",
    )
    @patch(
        "pecha_api.verse_of_day.comment_like_service.get_comment_likers",
        new_callable=AsyncMock,
    )
    @patch(
        "pecha_api.verse_of_day.comment_like_service.get_comment_by_id",
        new_callable=AsyncMock,
    )
    @patch(
        "pecha_api.verse_of_day.comment_like_service._require_verse",
        new_callable=AsyncMock,
    )
    async def test_list_likers_success(
        self,
        mock_require_verse: AsyncMock,
        mock_get_comment: AsyncMock,
        mock_get_likers: AsyncMock,
        _mock_avatar: MagicMock,
    ) -> None:
        comment = MockComment()
        user = MockUser(firstname="Tenzin", avatar_url="avatars/tenzin.jpg")
        mock_get_comment.return_value = comment
        mock_get_likers.return_value = ([MockLike(user=user)], 1)

        result = await list_verse_comment_likers_service(comment_id=comment.id)

        assert result.total == 1
        assert result.likes[0].first_name == "Tenzin"
        assert result.likes[0].avatar_url == "https://example.com/avatar.jpg"
        mock_require_verse.assert_awaited_once_with(comment.verse_id)
