"""Repository unit tests.

Integration tests cover these against real Postgres, but these pin the query
construction itself — most importantly that the row lock is applied when, and
only when, it is asked for.
"""
from unittest.mock import MagicMock
from uuid import uuid4

from pecha_api.group_assets.enums import GroupAssetType
from pecha_api.group_assets.repository import (
    create_asset,
    get_asset_by_id,
    get_assets_by_ids,
    get_assets_for_items,
    soft_delete_asset,
    update_asset,
)


def _query_chain(db, result=None, first=None):
    """Wire a MagicMock session so .query(...).filter(...) chains resolve."""
    query = MagicMock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.join.return_value = query
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.all.return_value = result or []
    query.first.return_value = first
    db.query.return_value = query
    return query


class TestCreateAsset:
    def test_refreshes_before_commit(self):
        """The refresh must precede the commit, so a failure there cannot make
        the caller think the row never landed."""
        order = []
        db = MagicMock()
        db.flush.side_effect = lambda: order.append("flush")
        db.refresh.side_effect = lambda _: order.append("refresh")
        db.commit.side_effect = lambda: order.append("commit")

        asset = MagicMock()
        result = create_asset(db=db, asset=asset)

        assert order == ["flush", "refresh", "commit"]
        assert result is asset


class TestRowLocking:
    def test_get_asset_by_id_locks_only_when_asked(self):
        db = MagicMock()
        query = _query_chain(db, first=MagicMock())

        get_asset_by_id(db=db, group_id=uuid4(), asset_id=uuid4())
        query.with_for_update.assert_not_called()

        get_asset_by_id(
            db=db, group_id=uuid4(), asset_id=uuid4(), for_update=True
        )
        query.with_for_update.assert_called_once()

    def test_get_assets_by_ids_locks_only_when_asked(self):
        db = MagicMock()
        query = _query_chain(db, result=[])
        ids = [uuid4()]

        get_assets_by_ids(db=db, group_id=uuid4(), asset_ids=ids)
        query.with_for_update.assert_not_called()

        get_assets_by_ids(
            db=db, group_id=uuid4(), asset_ids=ids, for_update=True
        )
        query.with_for_update.assert_called_once()

    def test_empty_id_list_short_circuits(self):
        db = MagicMock()
        assert get_assets_by_ids(db=db, group_id=uuid4(), asset_ids=[]) == []
        db.query.assert_not_called()


class TestTransactionBoundaries:
    def test_soft_delete_flushes_but_does_not_commit(self):
        """The caller owns the transaction, so cleanup and the soft delete can
        land atomically."""
        db = MagicMock()
        asset = MagicMock()

        soft_delete_asset(db=db, asset=asset, deleted_by="author@example.com")

        db.flush.assert_called_once()
        db.commit.assert_not_called()
        assert asset.deleted_at is not None
        assert asset.updated_by == "author@example.com"

    def test_update_asset_commits(self):
        """A rename is a single write and owns its own transaction."""
        db = MagicMock()
        asset = MagicMock()

        update_asset(db=db, asset=asset)

        db.commit.assert_called_once()


class TestBatchFetch:
    def test_no_items_means_no_query(self):
        db = MagicMock()
        assert get_assets_for_items(db=db, item_ids=[]) == {}
        db.query.assert_not_called()

    def test_groups_assets_by_item_in_order(self):
        db = MagicMock()
        item_a, item_b = uuid4(), uuid4()

        link_a1 = MagicMock(item_id=item_a, display_order=1)
        link_a2 = MagicMock(item_id=item_a, display_order=2)
        link_b1 = MagicMock(item_id=item_b, display_order=1)
        slow, fast, other = MagicMock(), MagicMock(), MagicMock()

        _query_chain(
            db,
            result=[(link_a1, slow), (link_a2, fast), (link_b1, other)],
        )

        got = get_assets_for_items(db=db, item_ids=[item_a, item_b])

        assert got[item_a] == [slow, fast]
        assert got[item_b] == [other]
