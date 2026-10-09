from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from pecha_api.bookmarks.bookmark_enums import BookmarkFilterType, BookmarkType
from pecha_api.bookmarks.bookmark_repository import get_bookmarks_by_user_id


def _mock_db() -> tuple[MagicMock, MagicMock]:
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.count.return_value = 0
    query_chain.order_by.return_value = query_chain
    query_chain.offset.return_value = query_chain
    query_chain.limit.return_value = query_chain
    query_chain.all.return_value = []
    db.query.return_value = query_chain
    return db, query_chain


def _last_filter_values(query_chain: MagicMock):
    """The IN-clause values of the type filter applied last."""
    clause = query_chain.filter.call_args_list[-1].args[0]
    return list(clause.right.value)


def test_accumulator_filter_includes_group_accumulations():
    """Group accumulations list alongside personal ones under one filter; each
    bookmark's own `type` tells them apart."""
    db, query_chain = _mock_db()

    get_bookmarks_by_user_id(
        db=db, user_id=uuid4(), type=BookmarkFilterType.ACCUMULATOR
    )

    assert _last_filter_values(query_chain) == [
        BookmarkType.ACCUMULATOR,
        BookmarkType.GROUP_ACCUMULATOR,
    ]


def test_text_filter_still_includes_verses():
    db, query_chain = _mock_db()

    get_bookmarks_by_user_id(db=db, user_id=uuid4(), type=BookmarkFilterType.TEXT)

    assert _last_filter_values(query_chain) == [
        BookmarkType.TEXT,
        BookmarkType.VERSE,
    ]


@pytest.mark.parametrize(
    "filter_type,expected",
    [
        (BookmarkFilterType.PLAN, BookmarkType.PLAN),
        (BookmarkFilterType.SERIES, BookmarkType.SERIES),
        (BookmarkFilterType.TIMER, BookmarkType.TIMER),
        (
            BookmarkFilterType.GROUP_RECITATION_COLLECTION,
            BookmarkType.GROUP_RECITATION_COLLECTION,
        ),
    ],
)
def test_other_filters_match_a_single_type(filter_type, expected):
    db, query_chain = _mock_db()

    get_bookmarks_by_user_id(db=db, user_id=uuid4(), type=filter_type)

    clause = query_chain.filter.call_args_list[-1].args[0]
    assert clause.right.value == expected


def test_no_filter_applies_only_the_user_filter():
    db, query_chain = _mock_db()

    get_bookmarks_by_user_id(db=db, user_id=uuid4(), type=None)

    # Only the user_id filter; no type filter is layered on top.
    assert query_chain.filter.call_count == 1


def test_group_accumulator_is_not_a_filter_value():
    """Group accumulations are reached through the ACCUMULATOR filter, so they
    are deliberately absent from BookmarkFilterType (as VERSE is)."""
    assert not hasattr(BookmarkFilterType, "GROUP_ACCUMULATOR")
    assert hasattr(BookmarkType, "GROUP_ACCUMULATOR")
