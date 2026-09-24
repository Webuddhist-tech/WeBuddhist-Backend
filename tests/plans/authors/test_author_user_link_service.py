from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from starlette import status

from pecha_api.plans.authors.author_user_link_service import (
    link_or_create_author_for_user,
    link_or_create_user_for_author,
)
from pecha_api.auth.auth_enums import RegistrationSource


def _make_user(email=None, phone_number=None, user_id=None) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    user.email = email
    user.phone_number = phone_number
    user.firstname = "John"
    user.lastname = "Doe"
    return user


def _make_author(email=None, phone_number=None, author_id=None, user_id=None) -> MagicMock:
    author = MagicMock()
    author.id = author_id or uuid4()
    author.email = email
    author.phone_number = phone_number
    author.first_name = "John"
    author.last_name = "Doe"
    author.user_id = user_id
    return author


class TestLinkOrCreateAuthorForUser:

    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_user_id')
    def test_returns_existing_link_without_further_lookups(
        self, mock_find_author_by_user_id: MagicMock
    ) -> None:
        db = MagicMock()
        user = _make_user(email="a@example.com")
        existing_author = _make_author(email="a@example.com", user_id=user.id)
        mock_find_author_by_user_id.return_value = existing_author

        result = link_or_create_author_for_user(db=db, user=user)

        assert result == existing_author
        mock_find_author_by_user_id.assert_called_once_with(db=db, user_id=user.id)

    @patch('pecha_api.plans.authors.author_user_link_service.link_author_to_user')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_email')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_user_id')
    def test_links_existing_unlinked_author_by_email(
        self,
        mock_find_author_by_user_id: MagicMock,
        mock_find_author_by_email: MagicMock,
        mock_link_author_to_user: MagicMock,
    ) -> None:
        db = MagicMock()
        user = _make_user(email="a@example.com")
        unlinked_author = _make_author(email="a@example.com", user_id=None)
        linked_author = _make_author(email="a@example.com", user_id=user.id)
        mock_find_author_by_user_id.return_value = None
        mock_find_author_by_email.return_value = unlinked_author
        mock_link_author_to_user.return_value = linked_author

        result = link_or_create_author_for_user(db=db, user=user)

        assert result == linked_author
        mock_find_author_by_email.assert_called_once_with(db=db, email="a@example.com")
        mock_link_author_to_user.assert_called_once_with(db=db, author=unlinked_author, user_id=user.id)

    @patch('pecha_api.plans.authors.author_user_link_service.link_author_to_user')
    @patch('pecha_api.plans.authors.author_user_link_service.get_author_by_phone')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_email')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_user_id')
    def test_links_existing_unlinked_author_by_phone_when_no_email_match(
        self,
        mock_find_author_by_user_id: MagicMock,
        mock_find_author_by_email: MagicMock,
        mock_get_author_by_phone: MagicMock,
        mock_link_author_to_user: MagicMock,
    ) -> None:
        db = MagicMock()
        user = _make_user(email=None, phone_number="+15551234567")
        unlinked_author = _make_author(phone_number="+15551234567", user_id=None)
        mock_find_author_by_user_id.return_value = None
        mock_find_author_by_email.return_value = None
        mock_get_author_by_phone.return_value = unlinked_author
        mock_link_author_to_user.return_value = unlinked_author

        result = link_or_create_author_for_user(db=db, user=user)

        assert result == unlinked_author
        mock_get_author_by_phone.assert_called_once_with(db=db, phone_number="+15551234567")
        mock_link_author_to_user.assert_called_once_with(db=db, author=unlinked_author, user_id=user.id)

    @patch('pecha_api.plans.authors.author_user_link_service.link_author_to_user')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_email')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_user_id')
    def test_does_not_relink_author_that_already_has_a_different_user_id(
        self,
        mock_find_author_by_user_id: MagicMock,
        mock_find_author_by_email: MagicMock,
        mock_link_author_to_user: MagicMock,
    ) -> None:
        """Defensive branch: if the matched Author already carries a
        user_id (shouldn't happen given the unique constraint, but the
        code checks explicitly), it's returned as-is without overwriting
        the link."""
        db = MagicMock()
        user = _make_user(email="a@example.com")
        already_linked_author = _make_author(email="a@example.com", user_id=uuid4())
        mock_find_author_by_user_id.return_value = None
        mock_find_author_by_email.return_value = already_linked_author

        result = link_or_create_author_for_user(db=db, user=user)

        assert result == already_linked_author
        mock_link_author_to_user.assert_not_called()

    @patch('pecha_api.plans.authors.author_user_link_service.save_author')
    @patch('pecha_api.plans.authors.author_user_link_service.get_author_by_phone')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_email')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_user_id')
    def test_creates_new_author_when_no_match_exists(
        self,
        mock_find_author_by_user_id: MagicMock,
        mock_find_author_by_email: MagicMock,
        mock_get_author_by_phone: MagicMock,
        mock_save_author: MagicMock,
    ) -> None:
        db = MagicMock()
        user = _make_user(email="new@example.com", phone_number="+15551234567")
        created_author = _make_author(email="new@example.com", user_id=user.id)
        mock_find_author_by_user_id.return_value = None
        mock_find_author_by_email.return_value = None
        mock_get_author_by_phone.return_value = None
        mock_save_author.return_value = created_author

        result = link_or_create_author_for_user(db=db, user=user)

        assert result == created_author
        saved_arg = mock_save_author.call_args.kwargs["author"]
        assert saved_arg.email == "new@example.com"
        assert saved_arg.phone_number == "+15551234567"
        assert saved_arg.user_id == user.id
        assert saved_arg.created_by == "new@example.com"

    @patch('pecha_api.plans.authors.author_user_link_service.get_author_by_phone')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_email')
    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_user_id')
    def test_returns_none_when_user_has_no_email_or_phone(
        self,
        mock_find_author_by_user_id: MagicMock,
        mock_find_author_by_email: MagicMock,
        mock_get_author_by_phone: MagicMock,
    ) -> None:
        db = MagicMock()
        user = _make_user(email=None, phone_number=None)
        mock_find_author_by_user_id.return_value = None

        result = link_or_create_author_for_user(db=db, user=user)

        assert result is None
        mock_find_author_by_email.assert_not_called()
        mock_get_author_by_phone.assert_not_called()

    @patch('pecha_api.plans.authors.author_user_link_service.find_author_by_user_id')
    def test_swallows_exceptions_and_returns_none(
        self, mock_find_author_by_user_id: MagicMock
    ) -> None:
        db = MagicMock()
        user = _make_user(email="a@example.com")
        mock_find_author_by_user_id.side_effect = RuntimeError("db exploded")

        result = link_or_create_author_for_user(db=db, user=user)

        assert result is None


class TestLinkOrCreateUserForAuthor:

    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_id')
    def test_returns_existing_linked_user(self, mock_get_user_by_id: MagicMock) -> None:
        db = MagicMock()
        existing_user = _make_user(email="a@example.com")
        author = _make_author(email="a@example.com", user_id=existing_user.id)
        mock_get_user_by_id.return_value = existing_user

        result = link_or_create_user_for_author(db=db, author=author)

        assert result == existing_user
        mock_get_user_by_id.assert_called_once_with(db=db, user_id=author.user_id)

    @patch('pecha_api.plans.authors.author_user_link_service.link_author_to_user')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_email_or_none')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_id')
    def test_stale_user_id_falls_through_to_email_match(
        self,
        mock_get_user_by_id: MagicMock,
        mock_get_user_by_email_or_none: MagicMock,
        mock_link_author_to_user: MagicMock,
    ) -> None:
        """If author.user_id points at a User row that no longer exists,
        recover via the email match instead of failing outright."""
        db = MagicMock()
        author = _make_author(email="a@example.com", user_id=uuid4())
        matched_user = _make_user(email="a@example.com")
        mock_get_user_by_id.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        mock_get_user_by_email_or_none.return_value = matched_user

        result = link_or_create_user_for_author(db=db, author=author)

        assert result == matched_user
        mock_link_author_to_user.assert_called_once_with(db=db, author=author, user_id=matched_user.id)

    @patch('pecha_api.plans.authors.author_user_link_service.link_author_to_user')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_email_or_none')
    def test_links_existing_user_by_email(
        self,
        mock_get_user_by_email_or_none: MagicMock,
        mock_link_author_to_user: MagicMock,
    ) -> None:
        db = MagicMock()
        author = _make_author(email="a@example.com", user_id=None)
        matched_user = _make_user(email="a@example.com")
        mock_get_user_by_email_or_none.return_value = matched_user

        result = link_or_create_user_for_author(db=db, author=author)

        assert result == matched_user
        mock_link_author_to_user.assert_called_once_with(db=db, author=author, user_id=matched_user.id)

    @patch('pecha_api.plans.authors.author_user_link_service.link_author_to_user')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_phone')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_email_or_none')
    def test_links_existing_user_by_phone_when_no_email_match(
        self,
        mock_get_user_by_email_or_none: MagicMock,
        mock_get_user_by_phone: MagicMock,
        mock_link_author_to_user: MagicMock,
    ) -> None:
        db = MagicMock()
        author = _make_author(email=None, phone_number="+15551234567", user_id=None)
        matched_user = _make_user(phone_number="+15551234567")
        mock_get_user_by_email_or_none.return_value = None
        mock_get_user_by_phone.return_value = matched_user

        result = link_or_create_user_for_author(db=db, author=author)

        assert result == matched_user
        mock_get_user_by_phone.assert_called_once_with(db=db, phone_number="+15551234567")
        mock_link_author_to_user.assert_called_once_with(db=db, author=author, user_id=matched_user.id)

    @patch('pecha_api.plans.authors.author_user_link_service.link_author_to_user')
    @patch('pecha_api.plans.authors.author_user_link_service.save_user')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_phone')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_email_or_none')
    def test_creates_new_user_when_no_match_exists(
        self,
        mock_get_user_by_email_or_none: MagicMock,
        mock_get_user_by_phone: MagicMock,
        mock_save_user: MagicMock,
        mock_link_author_to_user: MagicMock,
    ) -> None:
        db = MagicMock()
        author = _make_author(email="new-author@example.com", user_id=None)
        created_user = _make_user(email="new-author@example.com")
        mock_get_user_by_email_or_none.return_value = None
        mock_get_user_by_phone.return_value = None
        mock_save_user.return_value = created_user

        result = link_or_create_user_for_author(db=db, author=author)

        assert result == created_user
        saved_arg = mock_save_user.call_args.kwargs["user"]
        assert saved_arg.email == "new-author@example.com"
        assert saved_arg.registration_source == RegistrationSource.EMAIL.value
        assert saved_arg.is_active is True
        mock_link_author_to_user.assert_called_once_with(db=db, author=author, user_id=created_user.id)

    @patch('pecha_api.plans.authors.author_user_link_service.save_user')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_phone')
    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_email_or_none')
    def test_creates_new_user_with_phone_source_when_author_has_no_email(
        self,
        mock_get_user_by_email_or_none: MagicMock,
        mock_get_user_by_phone: MagicMock,
        mock_save_user: MagicMock,
    ) -> None:
        db = MagicMock()
        author = _make_author(email=None, phone_number="+15551234567", user_id=None)
        created_user = _make_user(phone_number="+15551234567")
        mock_get_user_by_phone.return_value = None
        mock_save_user.return_value = created_user

        result = link_or_create_user_for_author(db=db, author=author)

        assert result == created_user
        mock_get_user_by_email_or_none.assert_not_called()
        saved_arg = mock_save_user.call_args.kwargs["user"]
        assert saved_arg.registration_source == RegistrationSource.PHONE.value

    def test_returns_none_when_author_has_no_email_or_phone(self) -> None:
        db = MagicMock()
        author = _make_author(email=None, phone_number=None, user_id=None)

        result = link_or_create_user_for_author(db=db, author=author)

        assert result is None

    @patch('pecha_api.plans.authors.author_user_link_service.get_user_by_email_or_none')
    def test_swallows_exceptions_and_returns_none(
        self, mock_get_user_by_email_or_none: MagicMock
    ) -> None:
        db = MagicMock()
        author = _make_author(email="a@example.com", user_id=None)
        mock_get_user_by_email_or_none.side_effect = RuntimeError("db exploded")

        result = link_or_create_user_for_author(db=db, author=author)

        assert result is None
