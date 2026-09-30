"""Tests for verse of the day like service."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.verse_of_day.like_service import (
    like_verse_of_day_service,
    unlike_verse_of_day_service,
)


class MockVerse:
    def __init__(self, verse_id=None):
        self.id = verse_id or uuid4()


class MockLike:
    def __init__(self, created_at=None):
        self.created_at = created_at or "2024-01-01T00:00:00"


class TestLikeVerseOfDayService:

    @patch("pecha_api.verse_of_day.like_service.count_verse_likes")
    @patch("pecha_api.verse_of_day.like_service.create_like")
    @patch("pecha_api.verse_of_day.like_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.like_service.SessionLocal")
    def test_like_creates_new(
        self,
        mock_session,
        mock_get_verse,
        mock_create_like,
        mock_count,
    ):
        verse_id = uuid4()
        user_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_verse.return_value = MockVerse(verse_id)
        mock_create_like.return_value = (MockLike(), True)
        mock_count.return_value = 1

        result = like_verse_of_day_service(verse_id=verse_id, user_id=user_id)

        assert result.verse_id == verse_id
        assert result.user_id == user_id
        assert result.liked is True
        assert result.like_count == 1
        assert result.is_new is True

    @patch("pecha_api.verse_of_day.like_service.count_verse_likes")
    @patch("pecha_api.verse_of_day.like_service.create_like")
    @patch("pecha_api.verse_of_day.like_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.like_service.SessionLocal")
    def test_like_already_liked(
        self,
        mock_session,
        mock_get_verse,
        mock_create_like,
        mock_count,
    ):
        verse_id = uuid4()
        user_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_verse.return_value = MockVerse(verse_id)
        mock_create_like.return_value = (MockLike(), False)
        mock_count.return_value = 3

        result = like_verse_of_day_service(verse_id=verse_id, user_id=user_id)

        assert result.is_new is False
        assert result.like_count == 3

    @patch("pecha_api.verse_of_day.like_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.like_service.SessionLocal")
    def test_like_verse_not_found(self, mock_session, mock_get_verse):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_verse.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            like_verse_of_day_service(verse_id=uuid4(), user_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestUnlikeVerseOfDayService:

    @patch("pecha_api.verse_of_day.like_service.delete_like")
    @patch("pecha_api.verse_of_day.like_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.like_service.SessionLocal")
    def test_unlike_success(self, mock_session, mock_get_verse, mock_delete):
        verse_id = uuid4()
        user_id = uuid4()
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_verse.return_value = MockVerse(verse_id)

        unlike_verse_of_day_service(verse_id=verse_id, user_id=user_id)

        mock_delete.assert_called_once_with(db=mock_db, verse_id=verse_id, user_id=user_id)
