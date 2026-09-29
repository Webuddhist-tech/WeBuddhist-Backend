import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

from pecha_api.poems.enums import PoemStatus
from pecha_api.poems.models import Poem
from pecha_api.poems.repository import (
    get_poems_list,
    get_poem_by_id,
    create_poem,
    update_poem,
    soft_delete_poem,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_db_session():
    """Mock database session."""
    return MagicMock()


@pytest.fixture
def sample_poem():
    """Sample Poem model mock."""
    poem = MagicMock()
    poem.id = uuid4()
    poem.title = "Test Poem"
    poem.content = "Test content"
    poem.author_name = "Test Author"
    poem.chapter_name = "Chapter 1"
    poem.image_key = None
    poem.status = PoemStatus.PUBLISHED
    poem.published_at = datetime.now(timezone.utc)
    poem.created_at = datetime.now(timezone.utc)
    poem.updated_at = datetime.now(timezone.utc)
    poem.deleted_at = None
    poem.created_by = "test@example.com"
    poem.updated_by = None
    return poem


# =============================================================================
# get_poems_list() TESTS
# =============================================================================

def test_get_poems_list_basic(mock_db_session, sample_poem):
    """Test basic listing of poems."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 1
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = [sample_poem]
    
    poems, total = get_poems_list(mock_db_session)
    
    assert len(poems) == 1
    assert total == 1
    mock_db_session.query.assert_called_once_with(Poem)


def test_get_poems_list_with_status_filter(mock_db_session, sample_poem):
    """Test listing with status filter."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 1
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = [sample_poem]
    
    poems, total = get_poems_list(mock_db_session, status=PoemStatus.PUBLISHED)
    
    assert len(poems) == 1
    assert mock_query.filter.call_count >= 2


def test_get_poems_list_with_chapter_filter(mock_db_session, sample_poem):
    """Test listing with chapter_name filter."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 1
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = [sample_poem]
    
    poems, total = get_poems_list(mock_db_session, chapter_name="Chapter 1")
    
    assert len(poems) == 1
    assert mock_query.filter.call_count >= 2


def test_get_poems_list_with_author_filter(mock_db_session, sample_poem):
    """Test listing with author_name filter."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 1
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = [sample_poem]
    
    poems, total = get_poems_list(mock_db_session, author_name="Test Author")
    
    assert len(poems) == 1


def test_get_poems_list_pagination(mock_db_session):
    """Test pagination parameters."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 100
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []
    
    poems, total = get_poems_list(mock_db_session, skip=10, limit=5)
    
    assert total == 100
    mock_query.offset.assert_called_once_with(10)
    mock_query.limit.assert_called_once_with(5)


def test_get_poems_list_with_shuffle_seed(mock_db_session):
    """Test shuffle seed orders by a seeded hash instead of newest first."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 0
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []

    get_poems_list(mock_db_session, shuffle_seed="abc123")

    # Compiled for PostgreSQL rather than executed, as the listing-gate tests
    # in tests/plans/test_event_linked_listing_visibility.py do: this repo has
    # no database-backed test setup. Asserting the exact expression is what
    # guarantees stable pagination: md5(id + seed) is deterministic per seed,
    # so pages fetched with the same seed neither repeat nor skip poems, and
    # id breaks any tie.
    order_clauses = mock_query.order_by.call_args.args
    compiled = [
        str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for clause in order_clauses
    ]
    assert compiled == [
        "md5(concat(CAST(poems.id AS VARCHAR), 'abc123'))",
        "poems.id",
    ]


def test_get_poems_list_empty(mock_db_session):
    """Test listing when no poems exist."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.count.return_value = 0
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []
    
    poems, total = get_poems_list(mock_db_session)
    
    assert len(poems) == 0
    assert total == 0


# =============================================================================
# get_poem_by_id() TESTS
# =============================================================================

def test_get_poem_by_id_found(mock_db_session, sample_poem):
    """Test retrieving existing poem by ID."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = sample_poem
    
    result = get_poem_by_id(mock_db_session, sample_poem.id)
    
    assert result == sample_poem
    mock_db_session.query.assert_called_once_with(Poem)


def test_get_poem_by_id_not_found(mock_db_session):
    """Test retrieving non-existent poem."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = None
    
    result = get_poem_by_id(mock_db_session, uuid4())
    
    assert result is None


def test_get_poem_by_id_with_status_filter(mock_db_session, sample_poem):
    """Test retrieving poem with status filter."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = sample_poem
    
    result = get_poem_by_id(mock_db_session, sample_poem.id, status=PoemStatus.PUBLISHED)
    
    assert result == sample_poem
    assert mock_query.filter.call_count == 2


# =============================================================================
# create_poem() TESTS
# =============================================================================

def test_create_poem_success(mock_db_session, sample_poem):
    """Test creating a new poem."""
    result = create_poem(mock_db_session, sample_poem)
    
    mock_db_session.add.assert_called_once_with(sample_poem)
    mock_db_session.commit.assert_called_once()
    mock_db_session.refresh.assert_called_once_with(sample_poem)
    assert result == sample_poem


# =============================================================================
# update_poem() TESTS
# =============================================================================

def test_update_poem_success(mock_db_session, sample_poem):
    """Test updating an existing poem."""
    original_updated_at = sample_poem.updated_at
    
    result = update_poem(mock_db_session, sample_poem)
    
    mock_db_session.commit.assert_called_once()
    mock_db_session.refresh.assert_called_once_with(sample_poem)
    assert result == sample_poem
    assert sample_poem.updated_at != original_updated_at


# =============================================================================
# soft_delete_poem() TESTS
# =============================================================================

def test_soft_delete_poem_success(mock_db_session, sample_poem):
    """Test soft deleting a poem."""
    assert sample_poem.deleted_at is None
    
    soft_delete_poem(mock_db_session, sample_poem, "deleter@example.com")
    
    mock_db_session.commit.assert_called_once()
    assert sample_poem.deleted_at is not None
    assert sample_poem.updated_by == "deleter@example.com"
