"""Tests for verse of the day comment sync repository helpers."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.orm import Session

from pecha_api.verse_of_day.comment_models import VerseOfDayComment
from pecha_api.verse_of_day.comment_repository_sync import (
    _create_comment,
    _delete_comment,
    _get_comment_by_id,
    _get_verse_comments,
    create_comment_in_session,
    delete_comment_in_session,
    get_comment_by_id_in_session,
    get_verse_comments_in_session,
)


def _comment_query(db: MagicMock) -> MagicMock:
    return db.query.return_value


def test_get_verse_comments_pagination() -> None:
    db: MagicMock = MagicMock(spec=Session)
    verse_id = uuid4()
    comments = [MagicMock(), MagicMock()]
    base_query = _comment_query(db)
    ordered = base_query.filter.return_value.order_by.return_value
    ordered.count.return_value = 5
    ordered.options.return_value.offset.return_value.limit.return_value.all.return_value = (
        comments
    )

    result, total = _get_verse_comments(db=db, verse_id=verse_id, skip=2, limit=10)

    assert result == comments
    assert total == 5
    ordered.options.return_value.offset.assert_called_once_with(2)
    ordered.options.return_value.offset.return_value.limit.assert_called_once_with(10)


def test_create_comment_refreshes_with_user() -> None:
    db: MagicMock = MagicMock(spec=Session)
    comment = VerseOfDayComment(verse_id=uuid4(), user_id=uuid4(), text="hello")
    loaded = MagicMock()
    _comment_query(db).options.return_value.filter.return_value.one.return_value = loaded

    result = _create_comment(db=db, comment=comment)

    assert result is loaded
    db.add.assert_called_once_with(comment)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(comment)


def test_get_comment_by_id() -> None:
    db: MagicMock = MagicMock(spec=Session)
    comment_id = uuid4()
    expected = MagicMock()
    _comment_query(db).filter.return_value.first.return_value = expected

    assert _get_comment_by_id(db=db, comment_id=comment_id) is expected


def test_delete_comment() -> None:
    db: MagicMock = MagicMock(spec=Session)
    comment = MagicMock()

    _delete_comment(db=db, comment=comment)

    db.delete.assert_called_once_with(comment)
    db.commit.assert_called_once()


@patch("pecha_api.verse_of_day.comment_repository_sync._get_verse_comments")
@patch("pecha_api.verse_of_day.comment_repository_sync.SessionLocal")
def test_get_verse_comments_in_session(
    mock_session_local: MagicMock, mock_get: MagicMock
) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    verse_id = uuid4()
    mock_get.return_value = ([], 0)

    assert get_verse_comments_in_session(verse_id=verse_id, skip=0, limit=20) == ([], 0)
    mock_get.assert_called_once_with(db=db, verse_id=verse_id, skip=0, limit=20)


@patch("pecha_api.verse_of_day.comment_repository_sync._create_comment")
@patch("pecha_api.verse_of_day.comment_repository_sync.SessionLocal")
def test_create_comment_in_session(
    mock_session_local: MagicMock, mock_create: MagicMock
) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    verse_id = uuid4()
    user_id = uuid4()
    created = MagicMock()
    mock_create.return_value = created

    result = create_comment_in_session(verse_id=verse_id, user_id=user_id, text="Nice")

    assert result is created
    comment = mock_create.call_args.kwargs["comment"]
    assert comment.verse_id == verse_id
    assert comment.user_id == user_id
    assert comment.text == "Nice"


@patch("pecha_api.verse_of_day.comment_repository_sync._get_comment_by_id")
@patch("pecha_api.verse_of_day.comment_repository_sync.SessionLocal")
def test_get_comment_by_id_in_session(
    mock_session_local: MagicMock, mock_get: MagicMock
) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    comment_id = uuid4()
    mock_get.return_value = None

    assert get_comment_by_id_in_session(comment_id=comment_id) is None
    mock_get.assert_called_once_with(db=db, comment_id=comment_id)


@patch("pecha_api.verse_of_day.comment_repository_sync._delete_comment")
@patch("pecha_api.verse_of_day.comment_repository_sync._get_comment_by_id")
@patch("pecha_api.verse_of_day.comment_repository_sync.SessionLocal")
def test_delete_comment_in_session_no_comment(
    mock_session_local: MagicMock,
    mock_get: MagicMock,
    mock_delete: MagicMock,
) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    mock_get.return_value = None

    delete_comment_in_session(comment_id=uuid4())

    mock_delete.assert_not_called()


@patch("pecha_api.verse_of_day.comment_repository_sync._delete_comment")
@patch("pecha_api.verse_of_day.comment_repository_sync._get_comment_by_id")
@patch("pecha_api.verse_of_day.comment_repository_sync.SessionLocal")
def test_delete_comment_in_session_deletes_when_found(
    mock_session_local: MagicMock,
    mock_get: MagicMock,
    mock_delete: MagicMock,
) -> None:
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    comment = MagicMock()
    mock_get.return_value = comment

    delete_comment_in_session(comment_id=uuid4())

    mock_delete.assert_called_once_with(db=db, comment=comment)
