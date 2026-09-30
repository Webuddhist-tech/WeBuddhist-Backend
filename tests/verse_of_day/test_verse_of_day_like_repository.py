"""Tests for verse of the day like repository integrity handling."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pecha_api.verse_of_day.like_models import VerseOfDayLike
from pecha_api.verse_of_day.like_repository_sync import _create_like


def test_create_like_reraises_non_duplicate_integrity_error() -> None:
    db: MagicMock = MagicMock(spec=Session)
    like = VerseOfDayLike(verse_id=uuid4(), user_id=uuid4())
    db.commit.side_effect = IntegrityError("stmt", "params", "orig")

    query = MagicMock()
    query.filter.return_value.first.return_value = None
    db.query.return_value = query

    with pytest.raises(IntegrityError):
        _create_like(db=db, like=like)

    db.rollback.assert_called_once()
