"""Tests for verse of the day like service."""
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.verse_of_day.like_service import (
    _isoformat,
    _liker_avatar_url,
    _liker_first_name,
    _require_verse,
    get_verse_likes_service,
    like_verse_of_day_service,
    list_verse_likers_service,
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


class TestListVerseLikersService:

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.get_verse_likers", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service._require_verse", new_callable=AsyncMock)
    async def test_list_likers_success(
        self,
        mock_require: AsyncMock,
        mock_get_likers: AsyncMock,
    ) -> None:
        verse_id = uuid4()

        class MockUser:
            firstname = "Pema"
            lastname = None
            avatar_url = None

        like_created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        class MockLike:
            user_id = uuid4()
            user = MockUser()
            created_at = like_created_at

        mock_get_likers.return_value = ([MockLike()], 1)

        result = await list_verse_likers_service(verse_id=verse_id, skip=0, limit=20)

        assert result.total == 1
        assert result.likes[0].first_name == "Pema"
        assert result.likes[0].created_at == like_created_at.isoformat()
        mock_require.assert_awaited_once_with(verse_id)

    @pytest.mark.asyncio
    @patch("pecha_api.verse_of_day.like_service.get_verse_likers", new_callable=AsyncMock)
    @patch("pecha_api.verse_of_day.like_service._require_verse", new_callable=AsyncMock)
    async def test_list_likers_missing_user(
        self,
        mock_require: AsyncMock,
        mock_get_likers: AsyncMock,
    ) -> None:
        verse_id = uuid4()

        class MockLike:
            user_id = uuid4()
            user = None
            created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        mock_get_likers.return_value = ([MockLike()], 1)

        result = await list_verse_likers_service(verse_id=verse_id)

        assert result.likes[0].first_name == "Unknown"
        assert result.likes[0].last_name is None
        assert result.likes[0].avatar_url is None


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

    def test_isoformat_datetime(self) -> None:
        value = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
        assert _isoformat(value) == value.isoformat()

    def test_liker_first_name_unknown_user(self) -> None:
        assert _liker_first_name(None) == "Unknown"

    def test_liker_first_name_fallback_when_empty(self) -> None:
        user = MagicMock()
        user.firstname = "   "
        assert _liker_first_name(user) == "User"

    def test_liker_avatar_url_no_user(self) -> None:
        assert _liker_avatar_url(None) is None

    def test_liker_avatar_url_no_avatar(self) -> None:
        user = MagicMock()
        user.avatar_url = None
        assert _liker_avatar_url(user) is None

    @patch("pecha_api.verse_of_day.like_service.generate_presigned_access_url")
    @patch("pecha_api.verse_of_day.like_service.get", return_value="test-bucket")
    def test_liker_avatar_url_success(
        self, mock_get: MagicMock, mock_presign: MagicMock
    ) -> None:
        user = MagicMock()
        user.avatar_url = "avatars/user.png"
        mock_presign.return_value = "https://signed.example/avatar"

        assert _liker_avatar_url(user) == "https://signed.example/avatar"
        mock_presign.assert_called_once_with(
            bucket_name="test-bucket",
            s3_key="avatars/user.png",
        )

    @patch(
        "pecha_api.verse_of_day.like_service.generate_presigned_access_url",
        side_effect=RuntimeError("s3 down"),
    )
    @patch("pecha_api.verse_of_day.like_service.get", return_value="test-bucket")
    def test_liker_avatar_url_presign_failure(
        self, mock_get: MagicMock, mock_presign: MagicMock
    ) -> None:
        user = MagicMock()
        user.avatar_url = "avatars/user.png"

        assert _liker_avatar_url(user) is None


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
