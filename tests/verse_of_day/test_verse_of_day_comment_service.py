"""Tests for verse of the day comment service."""
from datetime import datetime, timezone as tz
from typing import Optional
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.verse_of_day.comment_service import (
    build_comment_dto,
    create_verse_comment_service,
    delete_verse_comment_service,
    list_verse_comments_service,
)


class MockUser:
    def __init__(
        self,
        firstname: Optional[str] = None,
        lastname: Optional[str] = None,
        email: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> None:
        self.id: UUID = uuid4()
        self.firstname = firstname
        self.lastname = lastname
        self.email = email
        self.avatar_url = avatar_url


class MockComment:
    def __init__(
        self,
        user: Optional[MockUser] = None,
        user_id: Optional[UUID] = None,
        verse_id: Optional[UUID] = None,
        text: str = "Hello",
    ) -> None:
        self.id: UUID = uuid4()
        self.verse_id: UUID = verse_id or uuid4()
        self.user_id: UUID = user_id or (user.id if user else uuid4())
        self.user = user
        self.text = text
        self.created_at: datetime = datetime.now(tz.utc)
        self.updated_at: Optional[datetime] = None


class MockVerse:
    def __init__(self, verse_id: Optional[UUID] = None) -> None:
        self.id: UUID = verse_id or uuid4()


class TestBuildCommentDto:

    def test_omits_email_for_phone_user(self) -> None:
        user = MockUser(firstname="Sam", lastname=None, email=None)
        dto = build_comment_dto(MockComment(user=user))

        assert dto.user.first_name == "Sam"
        assert "email" not in dto.user.model_dump()

    def test_uses_placeholder_when_user_missing(self) -> None:
        comment = MockComment(user=None)
        dto = build_comment_dto(comment)

        assert dto.user.first_name == "Unknown"
        assert dto.user.avatar_url is None

    def test_default_first_name_when_blank(self) -> None:
        user = MockUser(firstname="   ", lastname="Lee")
        dto = build_comment_dto(MockComment(user=user))

        assert dto.user.first_name == "User"
        assert dto.user.last_name == "Lee"

    @patch(
        "pecha_api.verse_of_day.comment_service.generate_presigned_access_url",
        return_value="https://example.com/avatar.jpg",
    )
    def test_includes_presigned_avatar(self, mock_generate_url: MagicMock) -> None:
        user = MockUser(
            firstname="Tenzin",
            lastname="Kunsang",
            avatar_url="avatars/tenzin.jpg",
        )
        dto = build_comment_dto(MockComment(user=user))

        assert dto.user.avatar_url == "https://example.com/avatar.jpg"
        mock_generate_url.assert_called_once()

    @patch(
        "pecha_api.verse_of_day.comment_service.generate_presigned_access_url",
        side_effect=RuntimeError("s3 down"),
    )
    def test_avatar_generation_failure_returns_none(
        self, _mock_generate_url: MagicMock
    ) -> None:
        user = MockUser(firstname="Tenzin", avatar_url="avatars/tenzin.jpg")
        dto = build_comment_dto(MockComment(user=user))

        assert dto.user.avatar_url is None

    def test_updated_at_null_when_never_edited(self) -> None:
        comment = MockComment(user=MockUser(firstname="A"))
        comment.updated_at = None

        dto = build_comment_dto(comment)

        assert dto.updated_at is None
        assert dto.created_at == comment.created_at.isoformat()


class TestListVerseCommentsService:

    @patch("pecha_api.verse_of_day.comment_service.get_verse_comments")
    @patch("pecha_api.verse_of_day.comment_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.comment_service.SessionLocal")
    def test_list_comments_success(
        self,
        mock_session: MagicMock,
        mock_get_verse: MagicMock,
        mock_get_comments: MagicMock,
    ) -> None:
        verse_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_verse.return_value = MockVerse(verse_id)
        user = MockUser(firstname="Commenter")
        comment = MockComment(user=user, verse_id=verse_id)
        mock_get_comments.return_value = ([comment], 1)

        result = list_verse_comments_service(verse_id=verse_id, skip=0, limit=20)

        assert result.total == 1
        assert result.comments[0].text == "Hello"
        assert result.comments[0].user.first_name == "Commenter"

    @patch("pecha_api.verse_of_day.comment_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.comment_service.SessionLocal")
    def test_list_comments_verse_not_found(
        self, mock_session: MagicMock, mock_get_verse: MagicMock
    ) -> None:
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_verse.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            list_verse_comments_service(verse_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestCreateVerseCommentService:

    @patch("pecha_api.verse_of_day.comment_service.VerseOfDayComment")
    @patch("pecha_api.verse_of_day.comment_service.create_comment")
    @patch("pecha_api.verse_of_day.comment_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.comment_service.SessionLocal")
    def test_create_comment_success(
        self,
        mock_session: MagicMock,
        mock_get_verse: MagicMock,
        mock_create: MagicMock,
        mock_comment_model: MagicMock,
    ) -> None:
        verse_id = uuid4()
        user_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_verse.return_value = MockVerse(verse_id)
        user = MockUser(firstname="Writer")
        mock_create.return_value = MockComment(user=user, verse_id=verse_id, text="Nice")

        result = create_verse_comment_service(
            verse_id=verse_id,
            user_id=user_id,
            text="Nice",
        )

        assert result.text == "Nice"
        assert result.user.first_name == "Writer"
        mock_comment_model.assert_called_once()

    @patch("pecha_api.verse_of_day.comment_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.comment_service.SessionLocal")
    def test_create_comment_verse_not_found(
        self, mock_session: MagicMock, mock_get_verse: MagicMock
    ) -> None:
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_verse.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            create_verse_comment_service(
                verse_id=uuid4(),
                user_id=uuid4(),
                text="Hi",
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteVerseCommentService:

    @patch("pecha_api.verse_of_day.comment_service.delete_comment")
    @patch("pecha_api.verse_of_day.comment_service.get_comment_by_id")
    @patch("pecha_api.verse_of_day.comment_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.comment_service.SessionLocal")
    def test_delete_comment_success(
        self,
        mock_session: MagicMock,
        mock_get_verse: MagicMock,
        mock_get_comment: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        user_id = uuid4()
        verse_id = uuid4()
        comment = MockComment(user_id=user_id, verse_id=verse_id)
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_get_comment.return_value = comment
        mock_get_verse.return_value = MockVerse(verse_id)

        delete_verse_comment_service(comment_id=comment.id, user_id=user_id)

        mock_delete.assert_called_once_with(db=mock_db, comment=comment)

    @patch("pecha_api.verse_of_day.comment_service.get_comment_by_id")
    @patch("pecha_api.verse_of_day.comment_service.SessionLocal")
    def test_delete_comment_not_found(
        self, mock_session: MagicMock, mock_get_comment: MagicMock
    ) -> None:
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_comment.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_verse_comment_service(comment_id=uuid4(), user_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch("pecha_api.verse_of_day.comment_service.get_comment_by_id")
    @patch("pecha_api.verse_of_day.comment_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.comment_service.SessionLocal")
    def test_delete_comment_forbidden_for_non_author(
        self,
        mock_session: MagicMock,
        mock_get_verse: MagicMock,
        mock_get_comment: MagicMock,
    ) -> None:
        verse_id = uuid4()
        comment = MockComment(user_id=uuid4(), verse_id=verse_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_comment.return_value = comment
        mock_get_verse.return_value = MockVerse(verse_id)

        with pytest.raises(HTTPException) as exc_info:
            delete_verse_comment_service(comment_id=comment.id, user_id=uuid4())

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch("pecha_api.verse_of_day.comment_service.get_comment_by_id")
    @patch("pecha_api.verse_of_day.comment_service.get_verse_of_day_by_id")
    @patch("pecha_api.verse_of_day.comment_service.SessionLocal")
    def test_delete_comment_verse_not_found(
        self,
        mock_session: MagicMock,
        mock_get_verse: MagicMock,
        mock_get_comment: MagicMock,
    ) -> None:
        user_id = uuid4()
        comment = MockComment(user_id=user_id)
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_comment.return_value = comment
        mock_get_verse.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_verse_comment_service(comment_id=comment.id, user_id=user_id)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
