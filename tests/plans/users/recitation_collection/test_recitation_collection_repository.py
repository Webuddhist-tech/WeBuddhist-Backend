"""Soft-delete on RecitationCollectionItem must keep the row alive so that
RecitationCollectionChantCompletion rows referencing it via chant_id are
never removed - a hard delete would cascade and quietly reduce a user's
persisted completion-day total. These tests exercise the real repository
functions against an in-memory SQLite database (rather than mocks) so the
query filters and the row's actual survival are genuinely verified."""
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pecha_api.plans.users.recitation_collection.recitation_collection_models import (
    RecitationCollection,
    RecitationCollectionItem,
)
from pecha_api.plans.users.recitation_collection.recitation_collection_completion_models import (
    RecitationCollectionChantCompletion,
)
from pecha_api.plans.users.recitation_collection.recitation_collection_repository import (
    collection_item_display_order_taken,
    delete_collection,
    get_collection_item_by_id,
    get_collection_item_counts,
    get_collection_items,
    get_max_display_order_for_collection,
    soft_delete_collection_item,
    update_collection_item,
)
from pecha_api.plans.users.recitation_collection.recitation_collection_completion_repository import (
    count_unique_completion_days,
)
from pecha_api.users.users_models import Users


def _make_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    RecitationCollection.metadata.create_all(
        bind=engine,
        tables=[
            RecitationCollection.__table__,
            RecitationCollectionItem.__table__,
            RecitationCollectionChantCompletion.__table__,
        ],
    )
    return sessionmaker(bind=engine)()


def _make_collection(db, user_id) -> RecitationCollection:
    now = datetime.now(timezone.utc).isoformat()
    collection = RecitationCollection(
        id=uuid4(),
        user_id=user_id,
        name="Daily Chants",
        img_url="images/test.jpg",
        created_at=now,
        updated_at=now,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def _make_item(db, collection_id, text_id="text-1", display_order=1) -> RecitationCollectionItem:
    item = RecitationCollectionItem(
        id=uuid4(),
        recitation_collection_id=collection_id,
        text_id=text_id,
        display_order=display_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_soft_delete_collection_item_marks_deleted_at_without_removing_the_row():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    item = _make_item(db, collection.id)

    result = soft_delete_collection_item(db=db, item=item)

    assert result.deleted_at is not None
    # The row must still physically exist - a plain lookup bypassing the
    # deleted_at filter proves it was not hard-deleted.
    raw = db.get(RecitationCollectionItem, item.id)
    assert raw is not None
    assert raw.deleted_at is not None


def test_get_collection_items_excludes_soft_deleted_items():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    kept = _make_item(db, collection.id, text_id="kept", display_order=1)
    removed = _make_item(db, collection.id, text_id="removed", display_order=2)

    soft_delete_collection_item(db=db, item=removed)

    items = get_collection_items(db=db, collection_id=collection.id)

    assert [i.id for i in items] == [kept.id]


def test_get_collection_item_by_id_returns_none_for_soft_deleted_item():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    item = _make_item(db, collection.id)

    soft_delete_collection_item(db=db, item=item)

    assert get_collection_item_by_id(
        db=db, item_id=item.id, collection_id=collection.id
    ) is None


def test_get_collection_item_by_id_returns_active_item():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    item = _make_item(db, collection.id)

    found = get_collection_item_by_id(db=db, item_id=item.id, collection_id=collection.id)

    assert found is not None
    assert found.id == item.id


def test_get_collection_item_counts_excludes_soft_deleted_items():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    _make_item(db, collection.id, text_id="kept", display_order=1)
    removed = _make_item(db, collection.id, text_id="removed", display_order=2)
    soft_delete_collection_item(db=db, item=removed)

    counts = get_collection_item_counts(db=db, collection_ids=[collection.id])

    assert counts.get(collection.id, 0) == 1


def test_get_max_display_order_ignores_soft_deleted_items():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    _make_item(db, collection.id, text_id="first", display_order=1)
    highest = _make_item(db, collection.id, text_id="second", display_order=5)
    soft_delete_collection_item(db=db, item=highest)

    assert get_max_display_order_for_collection(db=db, collection_id=collection.id) == 1


def test_soft_deleting_an_item_preserves_its_completion_history_and_day_count():
    """Regression test for the reported defect: removing an item from a
    collection must not erase completion history or reduce the day-count
    total the user already earned."""
    db = _make_session()
    user_id = uuid4()
    collection = _make_collection(db, user_id)
    item = _make_item(db, collection.id)

    completion = RecitationCollectionChantCompletion(
        id=uuid4(),
        user_id=user_id,
        chant_id=item.id,
        collection_id=collection.id,
        completion_date=date(2026, 9, 1),
        created_at=datetime.now(timezone.utc),
    )
    db.add(completion)
    db.commit()

    assert count_unique_completion_days(db=db, user_id=user_id, collection_id=collection.id) == 1

    soft_delete_collection_item(db=db, item=item)

    # The completion row is untouched by the item's (soft) deletion, so the
    # day count the user already earned is not reduced.
    assert count_unique_completion_days(db=db, user_id=user_id, collection_id=collection.id) == 1


def _make_session_with_fk_enforcement():
    """Real foreign-key enforcement (off by default in SQLite) so this proves
    the chant_id -> items.id FK still cascades, rather than merely failing to
    raise an error that SQLite wouldn't check anyway."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
    )
    RecitationCollection.metadata.create_all(
        bind=engine,
        tables=[
            Users.__table__,
            RecitationCollection.__table__,
            RecitationCollectionItem.__table__,
            RecitationCollectionChantCompletion.__table__,
        ],
    )
    return sessionmaker(bind=engine)()


def test_deleting_a_collection_with_completion_history_still_succeeds():
    """Regression test: deleting a whole collection still hard-deletes its
    items (RecitationCollection.items uses cascade="all, delete-orphan"), so
    the chant_id -> items.id foreign key must keep its own ON DELETE CASCADE.
    Dropping that cascade (to protect single-item soft delete) would instead
    make this raise an IntegrityError - i.e. the collection DELETE endpoint
    would 400 instead of succeeding - for any collection with completions."""
    db = _make_session_with_fk_enforcement()
    user_id = uuid4()
    db.add(Users(
        id=user_id,
        firstname="Test",
        registration_source="EMAIL",
    ))
    db.commit()

    collection = _make_collection(db, user_id)
    item = _make_item(db, collection.id)
    db.add(RecitationCollectionChantCompletion(
        id=uuid4(),
        user_id=user_id,
        chant_id=item.id,
        collection_id=collection.id,
        completion_date=date(2026, 9, 1),
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()

    deleted = delete_collection(db=db, collection_id=collection.id, user_id=user_id)

    assert deleted is not None
    assert db.get(RecitationCollection, collection.id) is None
    assert db.get(RecitationCollectionItem, item.id) is None


def test_update_collection_item_sets_fractional_display_order():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    item = _make_item(db, collection.id, display_order=2)

    item.display_order = 1.4
    updated = update_collection_item(db=db, item=item)

    assert updated.display_order == 1.4
    assert db.get(RecitationCollectionItem, item.id).display_order == 1.4


def test_display_order_taken_is_true_for_another_active_item():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    first = _make_item(db, collection.id, text_id="first", display_order=1.4)
    second = _make_item(db, collection.id, text_id="second", display_order=2)

    assert collection_item_display_order_taken(
        db=db,
        collection_id=collection.id,
        display_order=1.4,
        exclude_item_id=second.id,
    ) is True
    assert collection_item_display_order_taken(
        db=db,
        collection_id=collection.id,
        display_order=1.4,
        exclude_item_id=first.id,
    ) is False


def test_display_order_taken_ignores_soft_deleted_items():
    db = _make_session()
    collection = _make_collection(db, uuid4())
    removed = _make_item(db, collection.id, text_id="removed", display_order=1.4)
    kept = _make_item(db, collection.id, text_id="kept", display_order=2)
    soft_delete_collection_item(db=db, item=removed)

    assert collection_item_display_order_taken(
        db=db,
        collection_id=collection.id,
        display_order=1.4,
        exclude_item_id=kept.id,
    ) is False
