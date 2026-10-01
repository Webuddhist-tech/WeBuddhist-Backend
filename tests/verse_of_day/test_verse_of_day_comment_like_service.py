"""Tests for verse of the day comment like service."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.verse_of_day.comment_like_service import (
    like_verse_comment_service,
    list_verse_comment_likers_service,
    unlike_verse_comment_service,
)


class MockLike:
    def __init__(self) -> None:
        self.user_id = uuid4()
        self.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.user = MagicMock(firstname="Pema", lastname=None, avatar_url=None)


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
    @patch("pecha_api.verse_of_day.comment_like_service._require_verse", new_callable=AsyncMock)
    @patch(
        "pecha_api.verse_of_day.comment_like_service._get_comment_verse_id",
        new_callable=AsyncMock,
    )
    async def test_like_creates_new(
        self,
        mock_get_verse_id: AsyncMock,
        mock_require_verse: AsyncMock,
        mock_create: AsyncMock,
        mock_count: AsyncMock,
    ) -> None:
        comment_id = uuid4()
        user_id = uuid4()
        mock_get_verse_id.return_value = uuid4()
        mock_create.return_value = (MockLike(), True)
        mock_count.return_value = 1

        result = await like_verse_comment_service(comment_id=comment_id, user_id=user_id)

        assert result.comment_id == comment_id
        assert result.is_new is True
        assert result.like_count == 1

    @pytest.mark.asyncio
    @patch(
        "pecha_api.verse_of_day.comment_like_service._get_comment_verse_id",
        new_callable=AsyncMock,
    )
    async def test_like_comment_not_found(self, mock_get_verse_id: AsyncMock) -> None:
        mock_get_verse_id.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

        with pytest.raises(HTTPException) as exc_info:
            await like_verse_comment_service(comment_id=uuid4(), user_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestUnlikeVerseCommentService:

    @pytest.mark.asyncio
    @patch(
        "pecha_api.verse_of_day.comment_like_service.delete_like",
        new_callable=AsyncMock,
    )
    @patch("pecha_api.verse_of_day.comment_like_service._require_verse", new_callable=AsyncMock)
    @patch(
        "pecha_api.verse_of_day.comment_like_service._get_comment_verse_id",
        new_callable=AsyncMock,
    )
    async def test_unlike_success(
        self,
        mock_get_verse_id: AsyncMock,
        mock_require_verse: AsyncMock,
        mock_delete: AsyncMock,
    ) -> None:
        comment_id = uuid4()
        mock_get_verse_id.return_value = uuid4()

        await unlike_verse_comment_service(comment_id=comment_id, user_id=uuid4())

        mock_delete.assert_awaited_once()


class TestListVerseCommentLikersService:

    @pytest.mark.asyncio
    @patch(
        "pecha_api.verse_of_day.comment_like_service.get_comment_likers",
        new_callable=AsyncMock,
    )
    @patch("pecha_api.verse_of_day.comment_like_service._require_verse", new_callable=AsyncMock)
    @patch(
        "pecha_api.verse_of_day.comment_like_service._get_comment_verse_id",
        new_callable=AsyncMock,
    )
    async def test_list_likers_success(
        self,
        mock_get_verse_id: AsyncMock,
        mock_require_verse: AsyncMock,
        mock_get_likers: AsyncMock,
    ) -> None:
        comment_id = uuid4()
        mock_get_verse_id.return_value = uuid4()
        mock_get_likers.return_value = ([MockLike()], 1)

        result = await list_verse_comment_likers_service(comment_id=comment_id)

        assert result.total == 1
        assert result.likes[0].first_name == "Pema"
