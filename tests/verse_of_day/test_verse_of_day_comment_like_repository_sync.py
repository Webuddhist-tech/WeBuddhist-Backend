"""Tests for verse of the day comment like sync repository helpers."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pecha_api.verse_of_day.comment_like_models import VerseOfDayCommentLike
from pecha_api.verse_of_day.comment_like_repository_sync import (
    _batch_count_comment_likes,
    _batch_check_comments_liked_by_user,
    _count_comment_likes,
    _create_like,
    _delete_like,
    _get_comment_likers,
    batch_count_comment_likes_in_session,
    create_like_in_session,
    get_comment_likers_in_session,
)


def _like_query(db: MagicMock) -> MagicMock:
    return db.query.return_value


def test_create_like_success() -> None:
    db: MagicMock = MagicMock(spec=Session)
    like = VerseOfDayCommentLike(comment_id=uuid4(), user_id=uuid4())

    result, is_new = _create_like(db=db, like=like)

    assert result is like
    assert is_new is True
    db.commit.assert_called_once()


def test_create_like_returns_existing_on_duplicate() -> None:
    db: MagicMock = MagicMock(spec=Session)
    like = VerseOfDayCommentLike(comment_id=uuid4(), user_id=uuid4())
    existing = MagicMock()
    db.commit.side_effect = IntegrityError("stmt", "params", "orig")
    _like_query(db).filter.return_value.first.return_value = existing

    result, is_new = _create_like(db=db, like=like)

    assert result is existing
    assert is_new is False


def test_delete_like() -> None:
    db: MagicMock = MagicMock(spec=Session)
    _like_query(db).filter.return_value.delete.return_value = 1

    assert _delete_like(db=db, comment_id=uuid4(), user_id=uuid4()) is True


def test_count_comment_likes() -> None:
    db: MagicMock = MagicMock(spec=Session)
    _like_query(db).filter.return_value.count.return_value = 4

    assert _count_comment_likes(db=db, comment_id=uuid4()) == 4


@patch("pecha_api.verse_of_day.comment_like_repository_sync.selectinload")
def test_get_comment_likers_returns_page_and_total(mock_selectinload: MagicMock) -> None:
    mock_selectinload.return_value = MagicMock()
    db: MagicMock = MagicMock(spec=Session)
    comment_id = uuid4()
    like_row = MagicMock()
    query = db.query.return_value
    query.filter.return_value = query
    query.order_by.return_value = query
    query.count.return_value = 2
    query.options.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.all.return_value = [like_row]

    likes, total = _get_comment_likers(db=db, comment_id=comment_id, skip=0, limit=10)

    assert likes == [like_row]
    assert total == 2


def test_batch_count_and_liked_by_user() -> None:
    db: MagicMock = MagicMock(spec=Session)
    comment_id = uuid4()
    user_id = uuid4()

    count_query = MagicMock()
    count_query.filter.return_value.group_by.return_value.all.return_value = [
        (comment_id, 2)
    ]
    db.query.return_value = count_query

    assert _batch_count_comment_likes(db=db, comment_ids=[comment_id]) == {
        comment_id: 2
    }

    liked_query = MagicMock()
    liked_query.filter.return_value.all.return_value = [(comment_id,)]
    db.query.return_value = liked_query

    assert _batch_check_comments_liked_by_user(
        db=db, comment_ids=[comment_id], user_id=user_id
    ) == {comment_id}


@patch("pecha_api.verse_of_day.comment_like_repository_sync._create_like")
@patch("pecha_api.verse_of_day.comment_like_repository_sync.SessionLocal")
def test_create_like_in_session(mock_session_local: MagicMock, mock_create: MagicMock) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    expected = (MagicMock(), True)
    mock_create.return_value = expected

    result = create_like_in_session(comment_id=uuid4(), user_id=uuid4())

    assert result == expected


@patch("pecha_api.verse_of_day.comment_like_repository_sync._get_comment_likers")
@patch("pecha_api.verse_of_day.comment_like_repository_sync.SessionLocal")
def test_get_comment_likers_in_session(
    mock_session_local: MagicMock, mock_get_likers: MagicMock
) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    expected = ([MagicMock()], 1)
    mock_get_likers.return_value = expected

    result = get_comment_likers_in_session(comment_id=uuid4(), skip=0, limit=20)

    assert result == expected


@patch(
    "pecha_api.verse_of_day.comment_like_repository_sync._batch_count_comment_likes",
    return_value={},
)
@patch("pecha_api.verse_of_day.comment_like_repository_sync.SessionLocal")
def test_batch_count_in_session(
    mock_session_local: MagicMock, mock_batch: MagicMock
) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db

    assert batch_count_comment_likes_in_session(comment_ids=[]) == {}
    mock_batch.assert_called_once_with(db=db, comment_ids=[])
