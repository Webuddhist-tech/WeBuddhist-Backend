"""Tests for verse of the day like service."""
from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.verse_of_day.like_service import (
    _isoformat,
    _require_verse,
    get_verse_likes_service,
    like_verse_of_day_service,
    unlike_verse_of_day_service,
)


class MockLike:
    def __init__(self, created_at: Optional[str | datetime] = None) -> None:
        self.created_at: Optional[str | datetime] = created_at or "2024-01-01T00:00:00"


class TestLikeVerseOfDayService:

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.count_verse_likes", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service.create_like", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service._require_verse", new_callable=AsyncMock)
    async def test_like_creates_new(
        self,
        mock_require: AsyncMock,
        mock_create_like: AsyncMock,
        mock_count: AsyncMock,
    ) -> None:
        verse_id = uuid4()
        user_id = uuid4()
        mock_create_like.return_value = (MockLike(), True)
        mock_count.return_value = 1

        result = await like_verse_of_day_service(verse_id=verse_id, user_id=user_id)

        assert result.verse_id == verse_id
        assert result.user_id == user_id
        assert result.liked is True
        assert result.like_count == 1
        assert result.is_new is True
        mock_require.assert_awaited_once_with(verse_id)

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.count_verse_likes", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service.create_like", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service._require_verse", new_callable=AsyncMock)
    async def test_like_already_liked(
        self,
        mock_require: AsyncMock,
        mock_create_like: AsyncMock,
        mock_count: AsyncMock,
    ) -> None:
        verse_id = uuid4()
        user_id = uuid4()
        mock_create_like.return_value = (MockLike(), False)
        mock_count.return_value = 3

        result = await like_verse_of_day_service(verse_id=verse_id, user_id=user_id)

        assert result.is_new is False
        assert result.like_count == 3

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service._require_verse", new_callable=AsyncMock)
    async def test_like_verse_not_found(self, mock_require: AsyncMock) -> None:
        mock_require.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

        with pytest.raises(HTTPException) as exc_info:
            await like_verse_of_day_service(verse_id=uuid4(), user_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestUnlikeVerseOfDayService:

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.delete_like", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service._require_verse", new_callable=AsyncMock)
    async def test_unlike_success(
        self,
        mock_require: AsyncMock,
        mock_delete: AsyncMock,
    ) -> None:
        verse_id = uuid4()
        user_id = uuid4()

        await unlike_verse_of_day_service(verse_id=verse_id, user_id=user_id)

        mock_require.assert_awaited_once_with(verse_id)
        mock_delete.assert_awaited_once_with(verse_id=verse_id, user_id=user_id)


class TestGetVerseLikesService:

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.like_exists", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service.count_verse_likes", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service._require_verse", new_callable=AsyncMock)
    async def test_get_likes_anonymous(
        self,
        mock_require: AsyncMock,
        mock_count: AsyncMock,
        mock_exists: AsyncMock,
    ) -> None:
        verse_id = uuid4()
        mock_count.return_value = 10

        result = await get_verse_likes_service(verse_id=verse_id, user_id=None)

        assert result.like_count == 10
        assert result.liked_by_me is False
        mock_exists.assert_not_called()

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.like_exists", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service.count_verse_likes", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service._require_verse", new_callable=AsyncMock)
    async def test_get_likes_authenticated(
        self,
        mock_require: AsyncMock,
        mock_count: AsyncMock,
        mock_exists: AsyncMock,
    ) -> None:
        verse_id = uuid4()
        user_id = uuid4()
        mock_count.return_value = 2
        mock_exists.return_value = True

        result = await get_verse_likes_service(verse_id=verse_id, user_id=user_id)

        assert result.liked_by_me is True
        mock_exists.assert_awaited_once_with(verse_id=verse_id, user_id=user_id)


class TestLikeServiceHelpers:

    def test_isoformat_none(self) -> None:
        assert _isoformat(None) is None

    def test_isoformat_non_datetime_value(self) -> None:
        assert _isoformat(123) == "123"


class TestRequireVerse:

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.like_service.SessionLocal")
    async def test_require_verse_raises_when_missing(
        self,
        mock_session_local: MagicMock,
        mock_get_verse: MagicMock,
    ) -> None:
        db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = db
        mock_get_verse.return_value = None
        verse_id = uuid4()

        with pytest.raises(HTTPException) as exc_info:
            await _require_verse(verse_id)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail == NOT_FOUND
        mock_get_verse.assert_called_once_with(db=db, verse_id=verse_id)

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.like_service.SessionLocal")
    async def test_require_verse_ok_when_found(
        self,
        mock_session_local: MagicMock,
        mock_get_verse: MagicMock,
    ) -> None:
        db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = db
        mock_get_verse.return_value = MagicMock()
        verse_id = uuid4()

        await _require_verse(verse_id)

        mock_get_verse.assert_called_once_with(db=db, verse_id=verse_id)
