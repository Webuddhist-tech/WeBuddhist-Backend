"""Tests for verse of the day like sync repository helpers."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pecha_api.verse_of_day.like_models import VerseOfDayLike
from pecha_api.verse_of_day.like_repository_sync import (
    _count_verse_likes,
    _create_like,
    _delete_like,
    _like_exists,
    count_verse_likes_in_session,
    create_like_in_session,
    delete_like_in_session,
    like_exists_in_session,
)


def _like_query(db: MagicMock) -> MagicMock:
    return db.query.return_value


def test_create_like_success() -> None:
    db: MagicMock = MagicMock(spec=Session)
    like = VerseOfDayLike(verse_id=uuid4(), user_id=uuid4())

    result, is_new = _create_like(db=db, like=like)

    assert result is like
    assert is_new is True
    db.add.assert_called_once_with(like)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(like)


def test_create_like_returns_existing_on_duplicate() -> None:
    db: MagicMock = MagicMock(spec=Session)
    like = VerseOfDayLike(verse_id=uuid4(), user_id=uuid4())
    existing = MagicMock()
    db.commit.side_effect = IntegrityError("stmt", "params", "orig")
    _like_query(db).filter.return_value.first.return_value = existing

    result, is_new = _create_like(db=db, like=like)

    assert result is existing
    assert is_new is False
    db.rollback.assert_called_once()


def test_delete_like_returns_true_when_row_deleted() -> None:
    db: MagicMock = MagicMock(spec=Session)
    verse_id = uuid4()
    user_id = uuid4()
    _like_query(db).filter.return_value.delete.return_value = 1

    assert _delete_like(db=db, verse_id=verse_id, user_id=user_id) is True
    db.commit.assert_called_once()


def test_delete_like_returns_false_when_no_row() -> None:
    db: MagicMock = MagicMock(spec=Session)
    _like_query(db).filter.return_value.delete.return_value = 0

    assert _delete_like(db=db, verse_id=uuid4(), user_id=uuid4()) is False


def test_count_verse_likes() -> None:
    db: MagicMock = MagicMock(spec=Session)
    verse_id = uuid4()
    _like_query(db).filter.return_value.count.return_value = 7

    assert _count_verse_likes(db=db, verse_id=verse_id) == 7


def test_like_exists_true_and_false() -> None:
    db: MagicMock = MagicMock(spec=Session)
    _like_query(db).filter.return_value.count.return_value = 1
    assert _like_exists(db=db, verse_id=uuid4(), user_id=uuid4()) is True

    _like_query(db).filter.return_value.count.return_value = 0
    assert _like_exists(db=db, verse_id=uuid4(), user_id=uuid4()) is False


@patch("pecha_api.verse_of_day.like_repository_sync._create_like")
@patch("pecha_api.verse_of_day.like_repository_sync.SessionLocal")
def test_create_like_in_session(mock_session_local: MagicMock, mock_create: MagicMock) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    verse_id = uuid4()
    user_id = uuid4()
    expected = (MagicMock(), True)
    mock_create.return_value = expected

    result = create_like_in_session(verse_id=verse_id, user_id=user_id)

    assert result == expected
    mock_create.assert_called_once()
    created_like = mock_create.call_args.kwargs["like"]
    assert created_like.verse_id == verse_id
    assert created_like.user_id == user_id


@patch("pecha_api.verse_of_day.like_repository_sync._delete_like", return_value=True)
@patch("pecha_api.verse_of_day.like_repository_sync.SessionLocal")
def test_delete_like_in_session(mock_session_local: MagicMock, mock_delete: MagicMock) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    verse_id = uuid4()
    user_id = uuid4()

    assert delete_like_in_session(verse_id=verse_id, user_id=user_id) is True
    mock_delete.assert_called_once_with(db=db, verse_id=verse_id, user_id=user_id)


@patch("pecha_api.verse_of_day.like_repository_sync._count_verse_likes", return_value=3)
@patch("pecha_api.verse_of_day.like_repository_sync.SessionLocal")
def test_count_verse_likes_in_session(mock_session_local: MagicMock, mock_count: MagicMock) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    verse_id = uuid4()

    assert count_verse_likes_in_session(verse_id=verse_id) == 3
    mock_count.assert_called_once_with(db=db, verse_id=verse_id)


@patch("pecha_api.verse_of_day.like_repository_sync._like_exists", return_value=False)
@patch("pecha_api.verse_of_day.like_repository_sync.SessionLocal")
def test_like_exists_in_session(mock_session_local: MagicMock, mock_exists: MagicMock) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    verse_id = uuid4()
    user_id = uuid4()

    assert like_exists_in_session(verse_id=verse_id, user_id=user_id) is False
    mock_exists.assert_called_once_with(db=db, verse_id=verse_id, user_id=user_id)
