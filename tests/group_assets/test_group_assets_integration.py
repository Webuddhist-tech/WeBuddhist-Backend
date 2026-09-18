"""Integration tests for group assets against a real database.

The rest of the group_assets suite mocks the session, which cannot exercise
the things that actually bite here: the (item_id, display_order) unique
constraint on a reorder, the FK delete rules, and the fact that items and
collections are soft-deleted so ON DELETE CASCADE never fires.

These skip automatically when no database is reachable.
"""
import re
import importlib
from uuid import uuid4

import pytest
from sqlalchemy import text


def _load_all_models() -> None:
    """Replay env.py's model imports so the mapper registry resolves."""
    with open("migrations/env.py") as handle:
        for line in handle:
            match = re.match(r"^from (pecha_api[\w.]*) import", line)
            if match:
                try:
                    importlib.import_module(match.group(1))
                except Exception:
                    pass


def _db_available() -> bool:
    try:
        _load_all_models()
        from pecha_api.db.database import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM group_assets LIMIT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="requires a migrated database",
)


@pytest.fixture
def db():
    from pecha_api.db.database import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def group_id(db):
    existing = db.execute(text("SELECT id FROM author_groups LIMIT 1")).scalar()
    if existing is None:
        pytest.skip("no author_groups row to attach fixtures to")
    return existing


@pytest.fixture
def factory(db, group_id):
    """Builds collections, items and assets, and tears them all down after."""
    from pecha_api.group_assets.enums import GroupAssetType
    from pecha_api.group_assets.models import (
        GroupAsset,
        GroupRecitationCollectionItemAsset,
    )
    from pecha_api.group_recitation_collection.models import (
        GroupRecitationCollection,
        GroupRecitationCollectionItem,
    )

    created = {"collections": [], "items": [], "assets": []}

    class Factory:
        def collection(self, name="TMP collection"):
            row = GroupRecitationCollection(
                group_id=group_id, name=name, created_by=uuid4()
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            created["collections"].append(row)
            return row

        def item(self, collection, text_id=None, order=1):
            row = GroupRecitationCollectionItem(
                group_recitation_collection_id=collection.id,
                text_id=text_id or f"t-{uuid4()}",
                display_order=order,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            created["items"].append(row)
            return row

        def asset(self, title="slow", asset_type=GroupAssetType.AUDIO):
            row = GroupAsset(
                group_id=group_id,
                asset_type=asset_type,
                title=title,
                s3_key=f"groups/{group_id}/assets/audio/{uuid4()}.mp3",
                file_name=f"{title}.mp3",
                created_by="author@example.com",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            created["assets"].append(row)
            return row

        def links(self, item, assets):
            return [
                GroupRecitationCollectionItemAsset(
                    item_id=item.id,
                    asset_id=asset.id,
                    display_order=index,
                    created_by="author@example.com",
                )
                for index, asset in enumerate(assets, start=1)
            ]

    yield Factory()

    # Links first, then items, then assets: the link FK is RESTRICT.
    for item in created["items"]:
        db.query(GroupRecitationCollectionItemAsset).filter_by(
            item_id=item.id
        ).delete(synchronize_session=False)
    db.commit()
    for item in created["items"]:
        db.query(GroupRecitationCollectionItem).filter_by(id=item.id).delete()
    for asset in created["assets"]:
        db.query(GroupAsset).filter_by(id=asset.id).delete()
    for collection in created["collections"]:
        db.query(GroupRecitationCollection).filter_by(id=collection.id).delete()
    db.commit()


class TestReplaceItemAssets:
    def test_links_in_sent_order(self, db, factory):
        from pecha_api.group_assets.repository import (
            get_assets_for_items,
            replace_item_assets,
        )

        collection = factory.collection()
        item = factory.item(collection)
        slow, fast = factory.asset("slow"), factory.asset("fast")

        replace_item_assets(
            db=db, item_id=item.id, links=factory.links(item, [slow, fast])
        )

        got = get_assets_for_items(db=db, item_ids=[item.id])[item.id]
        assert [a.title for a in got] == ["slow", "fast"]

    def test_reverse_replace_reorders_without_constraint_collision(
        self, db, factory
    ):
        """The case a mock cannot catch: (item_id, display_order) is UNIQUE, so
        the delete must be flushed before the re-inserts."""
        from pecha_api.group_assets.models import (
            GroupRecitationCollectionItemAsset,
        )
        from pecha_api.group_assets.repository import (
            get_assets_for_items,
            replace_item_assets,
        )

        collection = factory.collection()
        item = factory.item(collection)
        slow, fast = factory.asset("slow"), factory.asset("fast")

        replace_item_assets(
            db=db, item_id=item.id, links=factory.links(item, [slow, fast])
        )
        replace_item_assets(
            db=db, item_id=item.id, links=factory.links(item, [fast, slow])
        )

        got = get_assets_for_items(db=db, item_ids=[item.id])[item.id]
        assert [a.title for a in got] == ["fast", "slow"]
        # Reorder replaces rather than accumulating.
        assert (
            db.query(GroupRecitationCollectionItemAsset)
            .filter_by(item_id=item.id)
            .count()
            == 2
        )

    def test_empty_array_clears_links_but_keeps_assets(self, db, factory):
        from pecha_api.group_assets.models import GroupAsset
        from pecha_api.group_assets.repository import (
            get_assets_for_items,
            replace_item_assets,
        )

        collection = factory.collection()
        item = factory.item(collection)
        slow, fast = factory.asset("slow"), factory.asset("fast")
        replace_item_assets(
            db=db, item_id=item.id, links=factory.links(item, [slow, fast])
        )

        replace_item_assets(db=db, item_id=item.id, links=[])

        assert get_assets_for_items(db=db, item_ids=[item.id]).get(item.id, []) == []
        assert db.query(GroupAsset).filter_by(id=slow.id).first() is not None
        assert db.query(GroupAsset).filter_by(id=fast.id).first() is not None

    def test_one_asset_linked_from_two_different_collections(self, db, factory):
        from pecha_api.group_assets.repository import (
            count_links_for_asset,
            get_asset_usages,
            replace_item_assets,
        )

        first = factory.collection("TMP Beginners")
        second = factory.collection("TMP Advanced")
        item_a = factory.item(first)
        item_b = factory.item(second)
        shared = factory.asset("shared chant")

        replace_item_assets(
            db=db, item_id=item_a.id, links=factory.links(item_a, [shared])
        )
        replace_item_assets(
            db=db, item_id=item_b.id, links=factory.links(item_b, [shared])
        )

        assert count_links_for_asset(db=db, asset_id=shared.id) == 2
        names = {u[1] for u in get_asset_usages(db=db, asset_id=shared.id)}
        assert names == {"TMP Beginners", "TMP Advanced"}

    def test_duplicate_asset_on_one_item_violates_constraint(self, db, factory):
        """UNIQUE (item_id, asset_id) — the same recording twice is a mistake."""
        from sqlalchemy.exc import IntegrityError
        from pecha_api.group_assets.repository import replace_item_assets

        collection = factory.collection()
        item = factory.item(collection)
        slow = factory.asset("slow")

        with pytest.raises(IntegrityError):
            replace_item_assets(
                db=db, item_id=item.id, links=factory.links(item, [slow, slow])
            )
        db.rollback()


class TestSoftDeleteLeavesLibraryCorrect:
    """Items and collections are soft-deleted, so ON DELETE CASCADE never
    fires and the links must be dropped explicitly."""

    def test_item_delete_drops_links_and_keeps_asset(self, db, factory):
        from pecha_api.group_assets.models import GroupAsset
        from pecha_api.group_assets.repository import (
            count_links_for_asset,
            delete_links_for_item,
            get_asset_usages,
            replace_item_assets,
        )
        from pecha_api.group_recitation_collection.repository import (
            soft_delete_collection_item,
        )

        collection = factory.collection()
        item = factory.item(collection)
        slow = factory.asset("slow")
        replace_item_assets(
            db=db, item_id=item.id, links=factory.links(item, [slow])
        )

        delete_links_for_item(db=db, item_id=item.id)
        soft_delete_collection_item(db=db, item=item)

        assert count_links_for_asset(db=db, asset_id=slow.id) == 0
        assert db.query(GroupAsset).filter_by(id=slow.id).first() is not None
        assert get_asset_usages(db=db, asset_id=slow.id) == []

    def test_collection_delete_drops_links_and_keeps_assets(self, db, factory):
        from pecha_api.group_assets.models import GroupAsset
        from pecha_api.group_assets.repository import (
            count_links_for_asset,
            delete_links_for_collection,
            get_asset_usages,
            replace_item_assets,
        )
        from pecha_api.group_recitation_collection.repository import (
            soft_delete_collection,
        )

        collection = factory.collection()
        item_a = factory.item(collection, order=1)
        item_b = factory.item(collection, order=2)
        slow, fast = factory.asset("slow"), factory.asset("fast")
        replace_item_assets(
            db=db, item_id=item_a.id, links=factory.links(item_a, [slow])
        )
        replace_item_assets(
            db=db, item_id=item_b.id, links=factory.links(item_b, [fast])
        )

        delete_links_for_collection(db=db, collection_id=collection.id)
        soft_delete_collection(db=db, collection=collection)

        assert count_links_for_asset(db=db, asset_id=slow.id) == 0
        assert count_links_for_asset(db=db, asset_id=fast.id) == 0
        assert db.query(GroupAsset).filter_by(id=slow.id).first() is not None
        assert db.query(GroupAsset).filter_by(id=fast.id).first() is not None
        assert get_asset_usages(db=db, asset_id=slow.id) == []

    def test_usages_ignore_soft_deleted_item(self, db, factory):
        """Backstop: even if a link survives, a removed item is not a usage."""
        from pecha_api.group_assets.repository import (
            get_asset_usages,
            replace_item_assets,
        )
        from pecha_api.group_recitation_collection.repository import (
            soft_delete_collection_item,
        )

        collection = factory.collection()
        item = factory.item(collection)
        slow = factory.asset("slow")
        replace_item_assets(
            db=db, item_id=item.id, links=factory.links(item, [slow])
        )

        # Soft delete WITHOUT dropping links, to prove the query filters.
        soft_delete_collection_item(db=db, item=item)

        assert get_asset_usages(db=db, asset_id=slow.id) == []


class TestAssetDeleteRules:
    def test_asset_with_links_cannot_be_hard_deleted(self, db, factory):
        """ON DELETE RESTRICT is the backstop behind the 409."""
        from sqlalchemy.exc import IntegrityError
        from pecha_api.group_assets.models import GroupAsset
        from pecha_api.group_assets.repository import replace_item_assets

        collection = factory.collection()
        item = factory.item(collection)
        slow = factory.asset("slow")
        replace_item_assets(
            db=db, item_id=item.id, links=factory.links(item, [slow])
        )

        with pytest.raises(IntegrityError):
            db.query(GroupAsset).filter_by(id=slow.id).delete()
            db.commit()
        db.rollback()

    def test_force_delete_path_drops_links_then_soft_deletes(self, db, factory):
        from pecha_api.group_assets.repository import (
            count_links_for_asset,
            delete_links_for_asset,
            replace_item_assets,
            soft_delete_asset,
        )

        collection = factory.collection()
        item = factory.item(collection)
        slow = factory.asset("slow")
        replace_item_assets(
            db=db, item_id=item.id, links=factory.links(item, [slow])
        )

        delete_links_for_asset(db=db, asset_id=slow.id)
        soft_delete_asset(db=db, asset=slow, deleted_by="author@example.com")

        assert count_links_for_asset(db=db, asset_id=slow.id) == 0
        assert slow.deleted_at is not None


class TestLibraryListing:
    def test_soft_deleted_asset_leaves_the_picker(self, db, factory, group_id):
        from pecha_api.group_assets.enums import GroupAssetType
        from pecha_api.group_assets.repository import (
            get_group_assets,
            soft_delete_asset,
        )

        asset = factory.asset("temporarily here")

        before, _ = get_group_assets(
            db=db, group_id=group_id, asset_type=GroupAssetType.AUDIO, limit=100
        )
        assert asset.id in {a.id for a in before}

        soft_delete_asset(db=db, asset=asset, deleted_by="author@example.com")

        after, _ = get_group_assets(
            db=db, group_id=group_id, asset_type=GroupAssetType.AUDIO, limit=100
        )
        assert asset.id not in {a.id for a in after}

    def test_assets_never_cross_groups(self, db, factory):
        from pecha_api.group_assets.repository import get_assets_by_ids

        asset = factory.asset("ours")
        other_group = uuid4()

        assert get_assets_by_ids(
            db=db, group_id=other_group, asset_ids=[asset.id]
        ) == []

    def test_search_matches_title_and_file_name(self, db, factory, group_id):
        from pecha_api.group_assets.repository import get_group_assets

        asset = factory.asset("Heart Sutra slow tempo")

        found, _ = get_group_assets(
            db=db, group_id=group_id, search="Sutra slow", limit=100
        )
        assert asset.id in {a.id for a in found}
