"""Tests for verse of the day comment like sync repository."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.verse_of_day.comment_like_repository_sync import (
    batch_comment_like_state_in_session,
    create_like_in_session,
)


@patch("pecha_api.verse_of_day.comment_like_repository_sync.VerseOfDayCommentLike")
@patch("pecha_api.verse_of_day.comment_like_repository_sync.SessionLocal")
@patch("pecha_api.verse_of_day.comment_like_repository_sync._create_like")
def test_create_like_in_session(
    mock_create: MagicMock,
    mock_session_local: MagicMock,
    mock_like_model: MagicMock,
) -> None:
    comment_id = uuid4()
    user_id = uuid4()
    db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = db
    like = MagicMock()
    mock_like_model.return_value = like
    mock_create.return_value = (like, True)

    result, is_new = create_like_in_session(comment_id=comment_id, user_id=user_id)

    assert result is like
    assert is_new is True
    mock_create.assert_called_once()


@patch("pecha_api.verse_of_day.comment_like_repository_sync.SessionLocal")
@patch("pecha_api.verse_of_day.comment_like_repository_sync._batch_count_comment_likes")
@patch(
    "pecha_api.verse_of_day.comment_like_repository_sync._batch_check_comments_liked_by_user"
)
def test_batch_comment_like_state_without_user(
    mock_liked: MagicMock,
    mock_counts: MagicMock,
    mock_session_local: MagicMock,
) -> None:
    comment_id = uuid4()
    mock_session_local.return_value.__enter__.return_value = MagicMock()
    mock_counts.return_value = {comment_id: 3}

    counts, liked_ids = batch_comment_like_state_in_session(
        comment_ids=[comment_id],
        user_id=None,
    )

    assert counts[comment_id] == 3
    assert liked_ids == set()
    mock_liked.assert_not_called()
