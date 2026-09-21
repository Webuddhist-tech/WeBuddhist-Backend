from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pecha_api.accumulator.accumulator_models import Accumulator
from pecha_api.accumulator.group_accumulator_link_model import GroupAccumulatorLink
from pecha_api.accumulator.group_accumulator_metadata_model import GroupAccumulatorMetadata
from pecha_api.accumulator.group_accumulator_models import GroupAccumulator
from pecha_api.db.database import Base
# The mappers below are unrelated to this module, but SQLAlchemy configures
# the whole registry the first time any mapped attribute is touched, and
# these two carry string-named relationships that cannot resolve unless
# their classes are imported. Without them the registry fails to configure
# and every test here errors out.
from pecha_api.plans.tasks.plan_tasks_models import PlanTask  # noqa: F401
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask  # noqa: F401
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.group_accumulator.group_accumulator_repository import (
    get_group_accumulators,
    get_group_accumulators_for_group_ids,
    get_joined_group_accumulator_ids_by_user,
    is_user_joined_group_accumulator,
    remove_group_accumulator_joins_for_group,
)


def test_is_user_joined_group_accumulator_checks_join_table():
    db = MagicMock()
    group_accumulator_id = uuid4()
    user_id = uuid4()
    db.execute.return_value.first.return_value = (group_accumulator_id,)

    assert is_user_joined_group_accumulator(
        db=db,
        group_accumulator_id=group_accumulator_id,
        user_id=user_id,
    )


def test_is_user_joined_group_accumulator_false_when_no_join_row():
    db = MagicMock()
    db.execute.return_value.first.return_value = None

    assert not is_user_joined_group_accumulator(
        db=db,
        group_accumulator_id=uuid4(),
        user_id=uuid4(),
    )


def test_get_joined_group_accumulator_ids_by_user_reads_join_table():
    db = MagicMock()
    joined_id = uuid4()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = [MagicMock(group_accumulator_id=joined_id)]

    result = get_joined_group_accumulator_ids_by_user(
        db=db,
        user_id=uuid4(),
        group_accumulator_ids=[joined_id],
    )

    assert result == [joined_id]
    db.query.assert_called_once()


def test_remove_group_accumulator_joins_for_group_deletes_join_rows_only():
    db = MagicMock()
    user_id = uuid4()
    group_id = uuid4()

    remove_group_accumulator_joins_for_group(
        db=db,
        user_id=user_id,
        group_id=group_id,
    )

    db.execute.assert_called_once()
    db.commit.assert_not_called()


def test_get_group_accumulators_for_group_ids_empty_group_ids_returns_early():
    db = MagicMock()

    result = get_group_accumulators_for_group_ids(db=db, group_ids=[], limit=20)

    assert result == ([], 0)
    db.query.assert_not_called()


def test_get_group_accumulators_for_group_ids_without_exclude_ids():
    db = MagicMock()
    group_id = uuid4()
    accumulator = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.options.return_value = query
    query.filter.return_value = query
    query.count.return_value = 1
    query.order_by.return_value = query
    query.limit.return_value = query
    query.limit.return_value.all.return_value = [accumulator]

    accumulators, total = get_group_accumulators_for_group_ids(
        db=db, group_ids=[group_id], limit=20
    )

    assert accumulators == [accumulator]
    assert total == 1
    query.filter.assert_called_once()


def test_get_group_accumulators_for_group_ids_with_exclude_ids_applies_extra_filter():
    db = MagicMock()
    group_id = uuid4()
    excluded_id = uuid4()
    query = MagicMock()
    db.query.return_value = query
    query.options.return_value = query
    query.filter.return_value = query
    query.count.return_value = 0
    query.order_by.return_value = query
    query.limit.return_value = query
    query.limit.return_value.all.return_value = []

    get_group_accumulators_for_group_ids(
        db=db, group_ids=[group_id], limit=20, exclude_ids=[excluded_id]
    )

    assert query.filter.call_count == 2


# --- get_group_accumulators search, against a real database ----------------
# The search filter is an OR over the default title and a correlated EXISTS
# into group_accumulator_metadata. Mocks only record that `.filter()` was
# called, so they cannot tell a working query from one that matches the wrong
# rows, duplicates them in the count, or breaks pagination. These run the SQL.


def _search_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Accumulator.__table__,
            GroupAccumulator.__table__,
            GroupAccumulatorMetadata.__table__,
            GroupAccumulatorLink.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _add_accumulator(
    db,
    group_id: UUID,
    title: Optional[str],
    metadata: Optional[List[Tuple[LanguageCode, Optional[str], Optional[str]]]] = None,
    created_at: Optional[datetime] = None,
    deleted_at: Optional[datetime] = None,
) -> GroupAccumulator:
    accumulator = GroupAccumulator(
        id=uuid4(),
        group_id=group_id,
        title=title,
        created_at=created_at or datetime.now(timezone.utc),
        deleted_at=deleted_at,
    )
    for language, entry_title, description in metadata or []:
        accumulator.metadata_entries.append(
            GroupAccumulatorMetadata(
                id=uuid4(),
                language=language,
                title=entry_title,
                description=description,
            )
        )
    db.add(accumulator)
    db.commit()
    return accumulator


@pytest.fixture
def search_db():
    db = _search_sessionmaker()()
    yield db
    db.close()


def test_search_matches_a_translated_title_only(search_db):
    """The term appears in no default title, only in a BO metadata row."""
    group_id = uuid4()
    translated = _add_accumulator(
        search_db,
        group_id,
        title="Mani Retreat",
        metadata=[
            (LanguageCode.EN, "Mani Retreat", "English about"),
            (LanguageCode.BO, "རྡོ་རྗེ་སེམས་དཔའ།", "Tibetan about"),
        ],
    )
    _add_accumulator(
        search_db,
        group_id,
        title="Tara Practice",
        metadata=[(LanguageCode.EN, "Tara Practice", None)],
    )

    results, total = get_group_accumulators(
        db=search_db, group_id=group_id, search="རྡོ་རྗེ"
    )

    assert [row.id for row in results] == [translated.id]
    assert total == 1


def test_search_still_matches_the_default_title(search_db):
    """The OR's first branch: a row whose translations do not match at all."""
    group_id = uuid4()
    accumulator = _add_accumulator(
        search_db,
        group_id,
        title="Mani Retreat",
        metadata=[(LanguageCode.BO, "རྡོ་རྗེ་སེམས་དཔའ།", None)],
    )

    results, total = get_group_accumulators(
        db=search_db, group_id=group_id, search="mani"
    )

    assert [row.id for row in results] == [accumulator.id]
    assert total == 1


def test_search_does_not_match_metadata_descriptions(search_db):
    """Only titles are searched; About text must not pull a row in."""
    group_id = uuid4()
    _add_accumulator(
        search_db,
        group_id,
        title="Tara Practice",
        metadata=[(LanguageCode.EN, "Tara Practice", "a retreat for beginners")],
    )

    results, total = get_group_accumulators(
        db=search_db, group_id=group_id, search="retreat"
    )

    assert results == []
    assert total == 0


def test_search_with_no_match_returns_nothing(search_db):
    group_id = uuid4()
    _add_accumulator(
        search_db,
        group_id,
        title="Mani Retreat",
        metadata=[(LanguageCode.EN, "Mani Retreat", None)],
    )

    results, total = get_group_accumulators(
        db=search_db, group_id=group_id, search="vajrayogini"
    )

    assert results == []
    assert total == 0


def test_search_counts_a_row_once_when_several_translations_match(search_db):
    """EXISTS, not a join: three matching metadata rows are still one result.

    A join would return the accumulator once per matching metadata row and
    inflate `total`, which is what drives the pager in the CMS list view."""
    group_id = uuid4()
    accumulator = _add_accumulator(
        search_db,
        group_id,
        title="Mani Retreat",
        metadata=[
            (LanguageCode.EN, "Mani Retreat", None),
            (LanguageCode.BO, "Mani in Tibetan", None),
            (LanguageCode.NE, "Mani in Nepali", None),
        ],
    )

    results, total = get_group_accumulators(
        db=search_db, group_id=group_id, search="mani"
    )

    assert [row.id for row in results] == [accumulator.id]
    assert total == 1


def test_search_excludes_other_groups_and_deleted_rows(search_db):
    """The search filter is ANDed with the group and soft-delete filters."""
    group_id = uuid4()
    other_group_id = uuid4()
    kept = _add_accumulator(
        search_db,
        group_id,
        title="Placeholder",
        metadata=[(LanguageCode.BO, "Mani in Tibetan", None)],
    )
    _add_accumulator(
        search_db,
        other_group_id,
        title="Placeholder",
        metadata=[(LanguageCode.BO, "Mani in Tibetan", None)],
    )
    _add_accumulator(
        search_db,
        group_id,
        title="Placeholder",
        metadata=[(LanguageCode.BO, "Mani in Tibetan", None)],
        deleted_at=datetime.now(timezone.utc),
    )

    results, total = get_group_accumulators(
        db=search_db, group_id=group_id, search="mani"
    )

    assert [row.id for row in results] == [kept.id]
    assert total == 1


def test_search_paginates_while_total_reports_every_match(search_db):
    """`total` is the full match count, not the size of the returned page."""
    group_id = uuid4()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Created oldest-first; the query orders newest-first.
    created = [
        _add_accumulator(
            search_db,
            group_id,
            title="Placeholder",
            metadata=[(LanguageCode.BO, f"Mani {index} in Tibetan", None)],
            created_at=base + timedelta(days=index),
        )
        for index in range(3)
    ]
    newest_first = [row.id for row in reversed(created)]

    first_page, total = get_group_accumulators(
        db=search_db, group_id=group_id, search="mani", skip=0, limit=2
    )
    second_page, second_total = get_group_accumulators(
        db=search_db, group_id=group_id, search="mani", skip=2, limit=2
    )

    assert [row.id for row in first_page] == newest_first[:2]
    assert [row.id for row in second_page] == newest_first[2:]
    assert total == 3
    assert second_total == 3
