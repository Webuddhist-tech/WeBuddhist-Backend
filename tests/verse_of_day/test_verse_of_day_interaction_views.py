"""Tests for verse of the day like and comment HTTP routes."""
from datetime import datetime, timezone as tz
from typing import Optional
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.verse_of_day.comment_response_models import (
    VerseOfDayCommentDTO,
    VerseOfDayCommentsResponse,
)
from pecha_api.verse_of_day.like_response_models import (
    LikeVerseOfDayResponse,
    VerseOfDayLikesResponse,
)

client = TestClient(api)
AUTH_HEADERS = {"Authorization": "Bearer test-token"}


def _comment_dto(verse_id: Optional[UUID] = None) -> VerseOfDayCommentDTO:
    now = datetime.now(tz.utc).isoformat()
    return VerseOfDayCommentDTO(
        id=uuid4(),
        verse_id=verse_id or uuid4(),
        user={
            "first_name": "First",
            "last_name": "Last",
            "avatar_url": None,
        },
        text="Lovely verse.",
        created_at=now,
        updated_at=now,
    )


class TestVerseOfDayLikeViews:

    @patch("pecha_api.verse_of_day.like_views.get_verse_likes_service")
    def test_get_likes(self, mock_service: MagicMock) -> None:
        verse_id = uuid4()
        mock_service.return_value = VerseOfDayLikesResponse(
            verse_id=verse_id,
            like_count=5,
            liked_by_me=False,
        )

        response = client.get(f"/verse-of-day/{verse_id}/likes")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["like_count"] == 5
        assert body["liked_by_me"] is False

    @patch("pecha_api.verse_of_day.like_views.get_verse_likes_service")
    @patch("pecha_api.verse_of_day.like_views.validate_and_extract_user_details")
    def test_get_likes_invalid_token_treated_as_anonymous(
        self, mock_validate: MagicMock, mock_service: MagicMock
    ) -> None:
        verse_id = uuid4()
        mock_validate.side_effect = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
        mock_service.return_value = VerseOfDayLikesResponse(
            verse_id=verse_id,
            like_count=1,
            liked_by_me=False,
        )

        response = client.get(
            f"/verse-of-day/{verse_id}/likes",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(verse_id=verse_id, user_id=None)

    @patch("pecha_api.verse_of_day.like_views.get_verse_likes_service")
    @patch("pecha_api.verse_of_day.like_views.validate_and_extract_user_details")
    def test_get_likes_database_error_propagates(
        self, mock_validate: MagicMock, mock_service: MagicMock
    ) -> None:
        verse_id = uuid4()
        mock_validate.side_effect = RuntimeError("database unavailable")

        with pytest.raises(RuntimeError, match="database unavailable"):
            client.get(
                f"/verse-of-day/{verse_id}/likes",
                headers=AUTH_HEADERS,
            )

        mock_service.assert_not_called()

    @patch("pecha_api.verse_of_day.like_views.validate_and_extract_user_details")
    @patch("pecha_api.verse_of_day.like_views.like_verse_of_day_service")
    def test_like_new(self, mock_service: MagicMock, mock_validate: MagicMock) -> None:
        verse_id = uuid4()
        user_id = uuid4()
        mock_validate.return_value = MagicMock(id=user_id)
        mock_service.return_value = LikeVerseOfDayResponse(
            verse_id=verse_id,
            user_id=user_id,
            liked=True,
            like_count=1,
            created_at="2024-01-01T00:00:00+00:00",
            is_new=True,
        )

        response = client.post(
            f"/verse-of-day/{verse_id}/likes",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["is_new"] is True

    @patch("pecha_api.verse_of_day.like_views.validate_and_extract_user_details")
    @patch("pecha_api.verse_of_day.like_views.like_verse_of_day_service")
    def test_like_existing(self, mock_service: MagicMock, mock_validate: MagicMock) -> None:
        verse_id = uuid4()
        user_id = uuid4()
        mock_validate.return_value = MagicMock(id=user_id)
        mock_service.return_value = LikeVerseOfDayResponse(
            verse_id=verse_id,
            user_id=user_id,
            liked=True,
            like_count=2,
            created_at="2024-01-01T00:00:00+00:00",
            is_new=False,
        )

        response = client.post(
            f"/verse-of-day/{verse_id}/likes",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_200_OK

    @patch("pecha_api.verse_of_day.like_views.validate_and_extract_user_details")
    @patch("pecha_api.verse_of_day.like_views.unlike_verse_of_day_service")
    def test_unlike(self, mock_service: MagicMock, mock_validate: MagicMock) -> None:
        verse_id = uuid4()
        mock_validate.return_value = MagicMock(id=uuid4())

        response = client.delete(
            f"/verse-of-day/{verse_id}/likes",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_service.assert_called_once()


class TestVerseOfDayCommentViews:

    @patch("pecha_api.verse_of_day.comment_views.list_verse_comments_service")
    def test_list_comments(self, mock_service: MagicMock) -> None:
        verse_id = uuid4()
        dto = _comment_dto(verse_id=verse_id)
        mock_service.return_value = VerseOfDayCommentsResponse(
            comments=[dto],
            skip=0,
            limit=20,
            total=1,
        )

        response = client.get(f"/verse-of-day/{verse_id}/comments")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1
        assert response.json()["comments"][0]["text"] == "Lovely verse."
        assert "email" not in response.json()["comments"][0]["user"]

    @patch("pecha_api.verse_of_day.comment_views.validate_and_extract_user_details")
    @patch("pecha_api.verse_of_day.comment_views.create_verse_comment_service")
    def test_create_comment(self, mock_service: MagicMock, mock_validate: MagicMock) -> None:
        verse_id = uuid4()
        user = MagicMock()
        user.id = uuid4()
        mock_validate.return_value = user
        mock_service.return_value = _comment_dto(verse_id=verse_id)

        response = client.post(
            f"/verse-of-day/{verse_id}/comments",
            headers=AUTH_HEADERS,
            json={"text": "Lovely verse."},
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_service.assert_called_once_with(
            verse_id=verse_id,
            user_id=user.id,
            text="Lovely verse.",
        )

    @patch("pecha_api.verse_of_day.comment_views.validate_and_extract_user_details")
    @patch("pecha_api.verse_of_day.comment_views.delete_verse_comment_service")
    def test_delete_comment(self, mock_service: MagicMock, mock_validate: MagicMock) -> None:
        comment_id = uuid4()
        mock_validate.return_value = MagicMock(id=uuid4())

        response = client.delete(
            f"/verse-of-day/comments/{comment_id}",
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_service.assert_called_once()
