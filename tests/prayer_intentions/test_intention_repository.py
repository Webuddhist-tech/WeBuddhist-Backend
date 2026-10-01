from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.prayer_intentions.prayer_intention_repository import (
    get_event_allowed_slugs,
    get_prayer_intention_by_slug,
    get_prayer_intentions_by_slugs,
    list_prayer_intentions,
    replace_event_prayer_intentions,
)


def _row(slug: str):
    row = MagicMock()
    row.slug = slug
    return row


def test_list_prayer_intentions_orders_query():
    db = MagicMock()
    query = db.query.return_value
    ordered = query.order_by.return_value
    ordered.all.return_value = [_row("healing")]

    rows = list_prayer_intentions(db)

    assert rows == ordered.all.return_value
    db.query.assert_called_once()
    query.order_by.assert_called_once()


def test_get_prayer_intention_by_slug():
    db = MagicMock()
    expected = _row("healing")
    db.query.return_value.filter.return_value.first.return_value = expected

    row = get_prayer_intention_by_slug(db=db, slug="healing")

    assert row is expected


def test_get_prayer_intentions_by_slugs_empty():
    assert get_prayer_intentions_by_slugs(db=MagicMock(), slugs=[]) == {}


def test_get_prayer_intentions_by_slugs_deduplicates():
    db = MagicMock()
    healing = _row("healing")
    db.query.return_value.filter.return_value.all.return_value = [healing]

    result = get_prayer_intentions_by_slugs(
        db=db, slugs=["healing", "healing", "protection"]
    )

    assert result == {"healing": healing}


def test_get_event_allowed_slugs_unrestricted():
    db = MagicMock()
    db.query.return_value.select_from.return_value.filter.return_value.scalar.return_value = 0

    assert get_event_allowed_slugs(db=db, event_id=uuid4()) is None


def test_replace_event_prayer_intentions_validates_ids():
    db = MagicMock()
    intention_id = uuid4()
    db.query.return_value.filter.return_value.all.return_value = []

    with pytest.raises(HTTPException):
        replace_event_prayer_intentions(
            db=db, event_id=uuid4(), intention_ids=[intention_id]
        )
