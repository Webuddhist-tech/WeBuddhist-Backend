import pytest
from uuid import uuid4
from datetime import date, datetime, timezone
from unittest.mock import patch, MagicMock, Mock

from fastapi import HTTPException

from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.poems.enums import PoemStatus
from pecha_api.poems.service import (
    list_poems_service,
    get_poem_detail_service,
    _build_poem_dto,
)
from pecha_api.poems.response_models import PoemDTO, PoemsResponse


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_db_session():
    """Mock database session with context manager support."""
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    return session


@pytest.fixture
def sample_poem_model():
    """Sample Poem model mock."""
    poem = MagicMock()
    poem.id = uuid4()
    poem.title = "The Jewel Ornament of Liberation"
    poem.content = "# Chapter 1\n\nAll beings have Buddha nature..."
    poem.author_name = "Gampopa"
    poem.chapter_name = "Buddha Nature"
    poem.language = LanguageCode.EN
    poem.image_key = "images/poem_images/uuid1/cover.jpg"
    poem.status = PoemStatus.PUBLISHED
    poem.published_at = datetime(2025, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    poem.created_at = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    poem.updated_at = datetime(2025, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    poem.deleted_at = None
    poem.created_by = "admin@example.com"
    poem.updated_by = None
    return poem


@pytest.fixture
def sample_poem_without_image():
    """Sample Poem model without image."""
    poem = MagicMock()
    poem.id = uuid4()
    poem.title = "Simple Verse"
    poem.content = "A simple verse without an image."
    poem.author_name = "Unknown"
    poem.chapter_name = None
    poem.language = LanguageCode.BO
    poem.image_key = None
    poem.status = PoemStatus.PUBLISHED
    poem.published_at = datetime(2025, 6, 6, 10, 0, 0, tzinfo=timezone.utc)
    poem.created_at = datetime(2025, 6, 6, 10, 0, 0, tzinfo=timezone.utc)
    poem.updated_at = datetime(2025, 6, 6, 10, 0, 0, tzinfo=timezone.utc)
    poem.deleted_at = None
    poem.created_by = "admin@example.com"
    poem.updated_by = None
    return poem


@pytest.fixture
def sample_draft_poem():
    """Sample draft Poem model."""
    poem = MagicMock()
    poem.id = uuid4()
    poem.title = "Draft Poem"
    poem.content = "This is a draft."
    poem.author_name = "Author"
    poem.chapter_name = None
    poem.language = LanguageCode.EN
    poem.image_key = None
    poem.status = PoemStatus.DRAFT
    poem.published_at = None
    poem.created_at = datetime(2025, 6, 7, 10, 0, 0, tzinfo=timezone.utc)
    poem.updated_at = datetime(2025, 6, 7, 10, 0, 0, tzinfo=timezone.utc)
    poem.deleted_at = None
    poem.created_by = "admin@example.com"
    poem.updated_by = None
    return poem


@pytest.fixture
def sample_poem_list(sample_poem_model, sample_poem_without_image):
    """Sample list of Poem models."""
    return [sample_poem_model, sample_poem_without_image]


# =============================================================================
# _build_poem_dto() TESTS
# =============================================================================

def test_build_poem_dto_with_image(sample_poem_model):
    """Test building DTO with presigned image URL."""
    presigned_url = "https://bucket.s3.amazonaws.com/image.jpg?X-Amz-Signature=..."
    
    with patch("pecha_api.poems.service.get", return_value="test-bucket"), \
         patch("pecha_api.poems.service.generate_presigned_access_url", return_value=presigned_url):
        
        result = _build_poem_dto(sample_poem_model)
        
        assert isinstance(result, PoemDTO)
        assert result.id == sample_poem_model.id
        assert result.title == sample_poem_model.title
        assert result.content == sample_poem_model.content
        assert result.author_name == sample_poem_model.author_name
        assert result.chapter_name == sample_poem_model.chapter_name
        assert result.image_url == presigned_url
        assert result.status == "PUBLISHED"
        assert result.published_at is not None


def test_build_poem_dto_without_image(sample_poem_without_image):
    """Test building DTO without image."""
    result = _build_poem_dto(sample_poem_without_image)
    
    assert isinstance(result, PoemDTO)
    assert result.id == sample_poem_without_image.id
    assert result.image_url is None
    assert result.chapter_name is None


def test_build_poem_dto_presigned_url_error(sample_poem_model):
    """Test building DTO when presigned URL generation fails."""
    with patch("pecha_api.poems.service.get", return_value="test-bucket"), \
         patch("pecha_api.poems.service.generate_presigned_access_url", side_effect=Exception("S3 error")):
        
        result = _build_poem_dto(sample_poem_model)
        
        assert isinstance(result, PoemDTO)
        assert result.image_url is None


# =============================================================================
# list_poems_service() TESTS
# =============================================================================

def test_list_poems_service_success(sample_poem_list, mock_db_session):
    """Test successful listing of published poems."""
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poems_list", return_value=(sample_poem_list, 2)) as mock_repo, \
         patch("pecha_api.poems.service.get", return_value="test-bucket"), \
         patch("pecha_api.poems.service.generate_presigned_access_url", return_value="https://presigned.url"):
        
        result = list_poems_service(skip=0, limit=20)
        
        assert isinstance(result, PoemsResponse)
        assert len(result.poems) == 2
        assert result.skip == 0
        assert result.limit == 20
        assert result.total == 2
        
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            skip=0,
            limit=20,
            status=PoemStatus.PUBLISHED,
            chapter_name=None,
            author_name=None,
            language=None,
            shuffle_seed=result.seed,
        )


def test_list_poems_service_with_filters(sample_poem_list, mock_db_session):
    """Test listing poems with chapter and author filters."""
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poems_list", return_value=(sample_poem_list[:1], 1)) as mock_repo, \
         patch("pecha_api.poems.service.get", return_value="test-bucket"), \
         patch("pecha_api.poems.service.generate_presigned_access_url", return_value="https://presigned.url"):
        
        result = list_poems_service(
            skip=0,
            limit=10,
            chapter_name="Buddha Nature",
            author_name="Gampopa",
        )
        
        assert isinstance(result, PoemsResponse)
        assert len(result.poems) == 1
        assert result.total == 1
        
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            skip=0,
            limit=10,
            status=PoemStatus.PUBLISHED,
            chapter_name="Buddha Nature",
            author_name="Gampopa",
            language=None,
            shuffle_seed=result.seed,
        )


def test_list_poems_service_defaults_seed_to_today(mock_db_session):
    """Test the shuffle seed defaults to today's UTC date (one order per day)."""
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poems_list", return_value=([], 0)) as mock_repo:

        result = list_poems_service()

        today = datetime.now(timezone.utc).date().isoformat()
        assert result.seed == today
        assert mock_repo.call_args.kwargs["shuffle_seed"] == today


def test_list_poems_service_uses_timezone_for_today(mock_db_session):
    """Test 'today' is resolved in the caller's timezone, like verse of the day."""
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poems_list", return_value=([], 0)), \
         patch("pecha_api.poems.service.get_date_in_timezone", return_value=date(2026, 9, 30)) as mock_tz:

        result = list_poems_service(timezone="Asia/Kathmandu")

        mock_tz.assert_called_once_with("Asia/Kathmandu")
        assert result.seed == "2026-09-30"


def test_list_poems_service_reuses_given_seed(mock_db_session):
    """Test a client-provided seed is passed through to keep order across pages."""
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poems_list", return_value=([], 0)) as mock_repo:

        result = list_poems_service(skip=20, limit=20, seed="abc123")

        assert result.seed == "abc123"
        assert mock_repo.call_args.kwargs["shuffle_seed"] == "abc123"


def test_list_poems_service_empty(mock_db_session):
    """Test listing poems when none exist."""
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poems_list", return_value=([], 0)):
        
        result = list_poems_service()
        
        assert isinstance(result, PoemsResponse)
        assert len(result.poems) == 0
        assert result.total == 0


def test_list_poems_service_pagination(sample_poem_list, mock_db_session):
    """Test pagination parameters are passed correctly."""
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poems_list", return_value=(sample_poem_list[:1], 10)) as mock_repo, \
         patch("pecha_api.poems.service.get", return_value="test-bucket"), \
         patch("pecha_api.poems.service.generate_presigned_access_url", return_value="https://presigned.url"):
        
        result = list_poems_service(skip=5, limit=1)
        
        assert result.skip == 5
        assert result.limit == 1
        assert result.total == 10
        
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            skip=5,
            limit=1,
            status=PoemStatus.PUBLISHED,
            chapter_name=None,
            author_name=None,
            language=None,
            shuffle_seed=result.seed,
        )


def test_list_poems_service_database_error(mock_db_session):
    """Test handling of database error."""
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poems_list", side_effect=Exception("Database error")):
        
        with pytest.raises(Exception, match="Database error"):
            list_poems_service()


# =============================================================================
# get_poem_detail_service() TESTS
# =============================================================================

def test_get_poem_detail_service_success(sample_poem_model, mock_db_session):
    """Test successful retrieval of poem by ID."""
    poem_id = sample_poem_model.id
    
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poem_by_id", return_value=sample_poem_model) as mock_repo, \
         patch("pecha_api.poems.service.get", return_value="test-bucket"), \
         patch("pecha_api.poems.service.generate_presigned_access_url", return_value="https://presigned.url"):
        
        result = get_poem_detail_service(poem_id=poem_id)
        
        assert isinstance(result, PoemDTO)
        assert result.id == poem_id
        assert result.title == sample_poem_model.title
        assert result.content == sample_poem_model.content
        
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            poem_id=poem_id,
            status=PoemStatus.PUBLISHED,
        )


def test_get_poem_detail_service_not_found(mock_db_session):
    """Test retrieval when poem doesn't exist."""
    poem_id = uuid4()
    
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poem_by_id", return_value=None):
        
        with pytest.raises(HTTPException) as exc_info:
            get_poem_detail_service(poem_id=poem_id)
        
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Poem not found"


def test_get_poem_detail_service_draft_not_found(sample_draft_poem, mock_db_session):
    """Test that draft poems are not returned by public endpoint."""
    poem_id = sample_draft_poem.id
    
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poem_by_id", return_value=None):
        
        with pytest.raises(HTTPException) as exc_info:
            get_poem_detail_service(poem_id=poem_id)
        
        assert exc_info.value.status_code == 404


def test_get_poem_detail_service_database_error(mock_db_session):
    """Test handling of database error."""
    poem_id = uuid4()
    
    with patch("pecha_api.poems.service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.poems.service.get_poem_by_id", side_effect=Exception("Database error")):
        
        with pytest.raises(Exception, match="Database error"):
            get_poem_detail_service(poem_id=poem_id)
