"""Tests for verse of the day like repository integrity handling."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from pecha_api.verse_of_day.like_repository import create_like


def test_create_like_reraises_non_duplicate_integrity_error():
    db = MagicMock()
    like = MagicMock()
    like.verse_id = uuid4()
    like.user_id = uuid4()
    db.commit.side_effect = IntegrityError("stmt", "params", "orig")

    query = MagicMock()
    query.filter.return_value.first.return_value = None
    db.query.return_value = query

    with pytest.raises(IntegrityError):
        create_like(db=db, like=like)

    db.rollback.assert_called_once()
