import pytest
from uuid import uuid4
from datetime import date
from unittest.mock import patch, MagicMock, Mock

from pecha_api.verse_of_day.verse_of_day_service import (
    get_verse_of_day,
    get_verse_of_day_by_id_service,
    get_verse_of_day_today_service,
    get_verses_of_day_list_service,
    create_verse_of_day_service,
    update_verse_of_day_service,
    delete_verse_of_day_service,
    cleanup_expired_verses_of_day,
    build_verses_dict,
    build_public_dto,
    _generate_verse_image_url,
)
from pecha_api.verse_of_day.verse_of_day_response_models import (
    VerseOfDayPublicResponse,
    VerseOfDayPublicDTO,
    VerseOfDayDTO,
    VerseOfDayListResponse,
    CreateVerseOfDayRequest,
    UpdateVerseOfDayRequest,
)
from pecha_api.verse_of_day.verse_of_day_enums import SortOrder
from fastapi import HTTPException


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
def sample_verse_metadata():
    """Sample verse metadata mocks for multilingual verses."""
    en_metadata = MagicMock()
    en_metadata.lang = "en"
    en_metadata.verse = "May all beings be happy and free from suffering."
    
    bo_metadata = MagicMock()
    bo_metadata.lang = "bo"
    bo_metadata.verse = '["སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་།", "སྡུག་བསྔལ་བྲལ་བར་གྱུར་ཅིག"]'
    
    zh_metadata = MagicMock()
    zh_metadata.lang = "zh"
    zh_metadata.verse = "愿一切众生快乐，远离痛苦。"
    
    return [en_metadata, bo_metadata, zh_metadata]


@pytest.fixture
def sample_verse_model(sample_verse_metadata):
    """Sample VerseOfDay model mock with verse_metadata relationship."""
    verse = MagicMock()
    verse.id = uuid4()
    verse.verse_id = "verse-456"
    verse.ref_id = "text-123"
    verse.source = "Dhp 1.5"
    verse.ref_type = "sutra"
    verse.image_urls = ["images/verse_images/uuid1/image1.jpg", "images/verse_images/uuid2/image2.jpg"]  # S3 keys
    verse.group_id = uuid4()
    verse.date = date(2025, 6, 5)
    verse.created_by = "test@example.com"
    verse.verse_metadata = sample_verse_metadata
    return verse


@pytest.fixture
def sample_create_request():
    """Sample create verse request with multilingual verses."""
    return CreateVerseOfDayRequest(
        verses={
            "en": "May all beings be happy and free from suffering.",
            "bo": '["སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་།", "སྡུག་བསྔལ་བྲལ་བར་གྱུར་ཅིག"]',
            "zh": "愿一切众生快乐，远离痛苦。"
        },
        image_urls=["https://example.com/image1.jpg"],
        verse_id="verse-456",
        ref_id="text-123",
        source="Dhp 1.5",
        ref_type="sutra",
        group_id=uuid4(),
        date=date(2025, 6, 5)
    )


@pytest.fixture
def sample_group_metadata():
    """Sample AuthorGroupMetadata objects for multiple languages."""
    en_metadata = MagicMock()
    en_metadata.id = uuid4()
    en_metadata.group_id = uuid4()
    en_metadata.language = "EN"
    en_metadata.title = "English Title"
    en_metadata.sub_title = "English Subtitle"
    en_metadata.description = "English description"
    
    bo_metadata = MagicMock()
    bo_metadata.id = uuid4()
    bo_metadata.group_id = en_metadata.group_id
    bo_metadata.language = "BO"
    bo_metadata.title = "བོད་ཡིག་མིང་།"
    bo_metadata.sub_title = "བོད་ཡིག་ཡན་ལག་མིང་།"
    bo_metadata.description = "བོད་ཡིག་གསལ་བཤད།"
    
    zh_metadata = MagicMock()
    zh_metadata.id = uuid4()
    zh_metadata.group_id = en_metadata.group_id
    zh_metadata.language = "zh"
    zh_metadata.title = "中文标题"
    zh_metadata.sub_title = "中文副标题"
    zh_metadata.description = "中文描述"
    
    return [en_metadata, bo_metadata, zh_metadata]


@pytest.fixture
def sample_verse_with_group_id(sample_verse_metadata):
    """Sample VerseOfDay model with group_id set."""
    verse = MagicMock()
    verse.id = uuid4()
    verse.verse_id = "verse-456"
    verse.ref_id = "text-123"
    verse.source = "Dhp 1.5"
    verse.ref_type = "sutra"
    verse.image_urls = ["images/verse_images/uuid1/image1.jpg"]  # S3 key
    verse.group_id = uuid4()
    verse.date = date(2025, 6, 5)
    verse.verse_metadata = sample_verse_metadata
    return verse


@pytest.fixture
def sample_verse_without_group_id(sample_verse_metadata):
    """Sample VerseOfDay model without group_id."""
    verse = MagicMock()
    verse.id = uuid4()
    verse.verse_id = "verse-789"
    verse.ref_id = "text-456"
    verse.source = None
    verse.ref_type = "commentary"
    verse.image_urls = None
    verse.group_id = None
    verse.date = date(2025, 6, 6)
    verse.verse_metadata = sample_verse_metadata
    return verse


@pytest.fixture
def sample_update_request():
    """Sample update verse request."""
    return UpdateVerseOfDayRequest(
        verses={
            "en": "Updated verse text.",
            "bo": '["བོད་ཡིག་གསར་པ།"]'
        },
        image_urls=["https://example.com/updated-image.jpg"],
        ref_id="text-updated",
        source="Lamrim Chenmo",
        ref_type="commentary"
    )


@pytest.fixture
def sample_verse_list(sample_verse_metadata):
    """Sample list of VerseOfDay models."""
    verse1 = MagicMock()
    verse1.id = uuid4()
    verse1.verse_id = "verse-1"
    verse1.ref_id = "text-1"
    verse1.source = "Dhp 1.5"
    verse1.ref_type = "sutra"
    verse1.image_urls = ["images/verse1.jpg"]
    verse1.group_id = uuid4()
    verse1.date = date(2025, 6, 5)
    verse1.verse_metadata = sample_verse_metadata
    
    verse2 = MagicMock()
    verse2.id = uuid4()
    verse2.verse_id = "verse-2"
    verse2.ref_id = "text-2"
    verse2.source = None
    verse2.ref_type = "tantra"
    verse2.image_urls = ["images/verse2.jpg"]
    verse2.group_id = None
    verse2.date = date(2025, 6, 6)
    verse2.verse_metadata = sample_verse_metadata
    
    return [verse1, verse2]


# =============================================================================
# get_verse_of_day() TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_get_verse_of_day_service_success(sample_verse_model, mock_db_session):
    """Test successful retrieval of verse with all languages and presigned URL."""
    presigned_url = "https://bucket.s3.amazonaws.com/image1.jpg?X-Amz-Signature=..."
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_model) as mock_repo, \
         patch("pecha_api.verse_of_day.verse_of_day_service._generate_verse_image_url", return_value=presigned_url) as mock_presigned:
        
        result = get_verse_of_day()
        
        assert isinstance(result, VerseOfDayPublicResponse)
        assert result.verse_of_day is not None
        assert isinstance(result.verse_of_day, VerseOfDayPublicDTO)
        assert result.verse_of_day.verses is not None
        assert "en" in result.verse_of_day.verses
        assert "bo" in result.verse_of_day.verses
        assert "zh" in result.verse_of_day.verses
        assert result.verse_of_day.ref_id == sample_verse_model.ref_id
        assert result.verse_of_day.ref_type == sample_verse_model.ref_type
        assert result.verse_of_day.image_url == presigned_url  # Single presigned URL string
        assert result.verse_of_day.date == sample_verse_model.date
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            group_id=None,
            filter_date=None
        )
        mock_presigned.assert_called_once_with(sample_verse_model.image_urls)


@pytest.mark.asyncio
async def test_get_verse_of_day_service_with_lang_filter(sample_verse_model, mock_db_session):
    """Test retrieval with language filter returns single verse."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_model):
        
        result = get_verse_of_day(lang="en")
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.verse == "May all beings be happy and free from suffering."
        assert result.verse_of_day.verses is None


@pytest.mark.asyncio
async def test_get_verse_of_day_service_with_lang_filter_array(sample_verse_model, mock_db_session):
    """Test retrieval with language filter for array verse (stored as JSON string)."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_model):
        
        result = get_verse_of_day(lang="bo")
        
        assert result.verse_of_day is not None
        # Verse is stored as JSON string in database
        assert isinstance(result.verse_of_day.verse, str)
        assert result.verse_of_day.verse.startswith('[')
        assert result.verse_of_day.verses is None


@pytest.mark.asyncio
async def test_get_verse_of_day_service_with_group_id(sample_verse_model, mock_db_session):
    """Test retrieval with group_id filter."""
    group_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_model) as mock_repo:
        
        result = get_verse_of_day(group_id=group_id)
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.verses is not None
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            group_id=group_id,
            filter_date=None
        )


@pytest.mark.asyncio
async def test_get_verse_of_day_service_with_date(sample_verse_model, mock_db_session):
    """Test retrieval with date filter."""
    filter_date = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_model) as mock_repo:
        
        result = get_verse_of_day(filter_date=filter_date)
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.date == sample_verse_model.date
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            group_id=None,
            filter_date=filter_date
        )


@pytest.mark.asyncio
async def test_get_verse_of_day_service_not_found(mock_db_session):
    """Test retrieval when no verse is found."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=None) as mock_repo:
        
        result = get_verse_of_day()
        
        assert isinstance(result, VerseOfDayPublicResponse)
        assert result.verse_of_day is None
        
        mock_repo.assert_called_once()


@pytest.mark.asyncio
async def test_get_verse_of_day_service_database_error(mock_db_session):
    """Test handling of database error."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", side_effect=Exception("Database connection error")):
        
        with pytest.raises(Exception, match="Database connection error"):
            get_verse_of_day()


@pytest.mark.asyncio
async def test_get_verse_of_day_with_group_info_all_languages(sample_verse_with_group_id, sample_group_metadata, mock_db_session):
    """Test returns all group_info when no lang filter."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_with_group_id), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=sample_group_metadata):
        
        result = get_verse_of_day()
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is not None
        assert len(result.verse_of_day.group_info) == 3
        languages = [info.language for info in result.verse_of_day.group_info]
        assert "EN" in languages
        assert "BO" in languages
        assert "zh" in languages


@pytest.mark.asyncio
async def test_get_verse_of_day_with_group_info_filtered_by_lang(sample_verse_with_group_id, sample_group_metadata, mock_db_session):
    """Test returns only ZH group_info when lang=zh."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_with_group_id), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=sample_group_metadata):
        
        result = get_verse_of_day(lang="zh")
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is not None
        assert len(result.verse_of_day.group_info) == 1
        assert result.verse_of_day.group_info[0].language == "zh"
        assert result.verse_of_day.group_info[0].title == "中文标题"


@pytest.mark.asyncio
async def test_get_verse_of_day_with_group_info_case_insensitive(sample_verse_with_group_id, sample_group_metadata, mock_db_session):
    """Test language filter works with different cases (zh, ZH, Zh)."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_with_group_id), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=sample_group_metadata):
        
        result = get_verse_of_day(lang="ZH")
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is not None
        assert len(result.verse_of_day.group_info) == 1
        assert result.verse_of_day.group_info[0].language == "zh"


@pytest.mark.asyncio
async def test_get_verse_of_day_without_group_id(sample_verse_without_group_id, mock_db_session):
    """Test returns None group_info when verse has no group_id."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_without_group_id):
        
        result = get_verse_of_day()
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is None


@pytest.mark.asyncio
async def test_get_verse_of_day_with_empty_group_metadata(sample_verse_with_group_id, mock_db_session):
    """Test returns None group_info when group has no metadata."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_with_group_id), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=[]):
        
        result = get_verse_of_day()
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is None


# =============================================================================
# get_verse_of_day_by_id_service() TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_service_success(sample_verse_model, mock_db_session):
    """Test successful retrieval of verse by ID with all languages."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model) as mock_repo:
        
        result = get_verse_of_day_by_id_service(verse_id=verse_id)
        
        assert isinstance(result, VerseOfDayPublicResponse)
        assert result.verse_of_day is not None
        assert result.verse_of_day.verses is not None
        assert "en" in result.verse_of_day.verses
        assert result.verse_of_day.ref_id == sample_verse_model.ref_id
        assert result.verse_of_day.ref_type == sample_verse_model.ref_type
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            verse_id=verse_id
        )


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_service_with_lang(sample_verse_model, mock_db_session):
    """Test retrieval by ID with language filter."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model):
        
        result = get_verse_of_day_by_id_service(verse_id=verse_id, lang="zh")
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.verse == "愿一切众生快乐，远离痛苦。"
        assert result.verse_of_day.verses is None


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_service_not_found(mock_db_session):
    """Test retrieval when verse ID doesn't exist."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=None) as mock_repo:
        
        result = get_verse_of_day_by_id_service(verse_id=verse_id)
        
        assert isinstance(result, VerseOfDayPublicResponse)
        assert result.verse_of_day is None
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            verse_id=verse_id
        )


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_service_database_error(mock_db_session):
    """Test handling of database error."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", side_effect=Exception("Database error")):
        
        with pytest.raises(Exception, match="Database error"):
            get_verse_of_day_by_id_service(verse_id=verse_id)


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_with_group_info_all_languages(sample_verse_with_group_id, sample_group_metadata, mock_db_session):
    """Test returns all group_info."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_with_group_id), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=sample_group_metadata):
        
        result = get_verse_of_day_by_id_service(verse_id=verse_id)
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is not None
        assert len(result.verse_of_day.group_info) == 3


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_with_group_info_filtered(sample_verse_with_group_id, sample_group_metadata, mock_db_session):
    """Test returns filtered group_info by lang."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_with_group_id), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=sample_group_metadata):
        
        result = get_verse_of_day_by_id_service(verse_id=verse_id, lang="EN")
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is not None
        assert len(result.verse_of_day.group_info) == 1
        assert result.verse_of_day.group_info[0].language == "EN"


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_without_group_id(sample_verse_without_group_id, mock_db_session):
    """Test returns None group_info."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_without_group_id):
        
        result = get_verse_of_day_by_id_service(verse_id=verse_id)
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is None


# =============================================================================
# get_verse_of_day_today_service() TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_get_verse_of_day_today_service_success(sample_verse_model, mock_db_session):
    """Test successful retrieval of today's verse with all languages."""
    today = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_date_in_timezone", return_value=today) as mock_today, \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_today", return_value=sample_verse_model) as mock_repo:
        
        result = get_verse_of_day_today_service()
        
        assert isinstance(result, VerseOfDayPublicResponse)
        assert result.verse_of_day is not None
        assert result.verse_of_day.verses is not None
        assert "en" in result.verse_of_day.verses
        assert result.verse_of_day.ref_id == sample_verse_model.ref_id
        
        mock_today.assert_called_once_with(None)
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            today=today
        )


@pytest.mark.asyncio
async def test_get_verse_of_day_today_service_with_lang(sample_verse_model, mock_db_session):
    """Test retrieval of today's verse with language filter."""
    today = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_date_in_timezone", return_value=today), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_today", return_value=sample_verse_model):
        
        result = get_verse_of_day_today_service(lang="en")
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.verse == "May all beings be happy and free from suffering."
        assert result.verse_of_day.verses is None


@pytest.mark.asyncio
async def test_get_verse_of_day_today_service_not_found(mock_db_session):
    """Test retrieval when no verse exists for today."""
    today = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_date_in_timezone", return_value=today), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_today", return_value=None) as mock_repo:
        
        result = get_verse_of_day_today_service()
        
        assert isinstance(result, VerseOfDayPublicResponse)
        assert result.verse_of_day is None
        
        mock_repo.assert_called_once()


@pytest.mark.asyncio
async def test_get_verse_of_day_today_service_database_error(mock_db_session):
    """Test handling of database error."""
    today = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_date_in_timezone", return_value=today), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_today", side_effect=Exception("Database error")):
        
        with pytest.raises(Exception, match="Database error"):
            get_verse_of_day_today_service()


@pytest.mark.asyncio
async def test_get_verse_of_day_today_with_group_info_all_languages(sample_verse_with_group_id, sample_group_metadata, mock_db_session):
    """Test returns all group_info."""
    today = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_date_in_timezone", return_value=today), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_today", return_value=sample_verse_with_group_id), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=sample_group_metadata):
        
        result = get_verse_of_day_today_service()
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is not None
        assert len(result.verse_of_day.group_info) == 3


@pytest.mark.asyncio
async def test_get_verse_of_day_today_with_group_info_filtered(sample_verse_with_group_id, sample_group_metadata, mock_db_session):
    """Test returns filtered group_info by lang."""
    today = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_date_in_timezone", return_value=today), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_today", return_value=sample_verse_with_group_id), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=sample_group_metadata):
        
        result = get_verse_of_day_today_service(lang="BO")
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is not None
        assert len(result.verse_of_day.group_info) == 1
        assert result.verse_of_day.group_info[0].language == "BO"


@pytest.mark.asyncio
async def test_get_verse_of_day_today_without_group_id(sample_verse_without_group_id, mock_db_session):
    """Test returns None group_info."""
    today = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_date_in_timezone", return_value=today), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_today", return_value=sample_verse_without_group_id):
        
        result = get_verse_of_day_today_service()
        
        assert result.verse_of_day is not None
        assert result.verse_of_day.group_info is None


@pytest.mark.asyncio
async def test_get_verse_of_day_today_service_with_timezone(sample_verse_model, mock_db_session):
    """Test today's verse uses the provided timezone."""
    today = date(2025, 6, 4)

    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_date_in_timezone", return_value=today) as mock_today, \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_today", return_value=sample_verse_model) as mock_repo:

        result = get_verse_of_day_today_service(timezone="America/Los_Angeles")

        assert result.verse_of_day is not None
        mock_today.assert_called_once_with("America/Los_Angeles")
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            today=today,
        )


# =============================================================================
# create_verse_of_day_service() TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_create_verse_of_day_service_success(sample_verse_model, sample_create_request, mock_db_session):
    """Test successful creation of verse of day with multilingual verses."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=None), \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_of_day", return_value=sample_verse_model) as mock_create, \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_metadata_bulk") as mock_metadata:
        
        result = create_verse_of_day_service(
            request=sample_create_request,
            created_by="test@example.com"
        )
        
        assert isinstance(result, VerseOfDayDTO)
        assert result.id == sample_verse_model.id
        assert result.verses == sample_create_request.verses
        assert result.verse_id == sample_verse_model.verse_id
        assert result.ref_id == sample_verse_model.ref_id
        assert result.source == sample_verse_model.source
        assert result.ref_type == sample_verse_model.ref_type
        assert result.image_urls == sample_verse_model.image_urls
        assert result.group_id == sample_verse_model.group_id
        assert result.date == sample_verse_model.date
        
        mock_create.assert_called_once()
        mock_metadata.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            sample_verse_model.id,
            sample_create_request.verses
        )


@pytest.mark.asyncio
async def test_create_verse_of_day_service_with_optional_fields(mock_db_session):
    """Test creation with optional fields (image_urls and group_id)."""
    request = CreateVerseOfDayRequest(
        verses={"en": "Simple verse without extras."},
        verse_id="verse-simple",
        ref_id="text-simple",
        ref_type="commentary",
        date=date(2025, 6, 6)
    )
    
    created_verse = MagicMock()
    created_verse.id = uuid4()
    created_verse.verse_id = request.verse_id
    created_verse.ref_id = request.ref_id
    created_verse.source = None
    created_verse.ref_type = request.ref_type
    created_verse.image_urls = None
    created_verse.group_id = None
    created_verse.date = request.date
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=None), \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_of_day", return_value=created_verse), \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_metadata_bulk"):
        
        result = create_verse_of_day_service(
            request=request,
            created_by="test@example.com"
        )
        
        assert isinstance(result, VerseOfDayDTO)
        assert result.verses == {"en": "Simple verse without extras."}
        assert result.image_urls is None
        assert result.group_id is None
        assert result.source is None


@pytest.mark.asyncio
async def test_create_verse_of_day_service_database_error(sample_create_request, mock_db_session):
    """Test handling of database error during creation."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=None), \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_of_day", side_effect=Exception("Database error")):
        
        with pytest.raises(Exception, match="Database error"):
            create_verse_of_day_service(
                request=sample_create_request,
                created_by="test@example.com"
            )


@pytest.mark.asyncio
async def test_create_verse_of_day_service_model_creation(sample_create_request, mock_db_session):
    """Test that VerseOfDay model is created with correct fields."""
    created_verse = MagicMock()
    created_verse.id = uuid4()
    created_verse.verse_id = sample_create_request.verse_id
    created_verse.ref_id = sample_create_request.ref_id
    created_verse.source = sample_create_request.source
    created_verse.ref_type = sample_create_request.ref_type
    created_verse.image_urls = sample_create_request.image_urls
    created_verse.group_id = sample_create_request.group_id
    created_verse.date = sample_create_request.date
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=None), \
         patch("pecha_api.verse_of_day.verse_of_day_service.VerseOfDay") as mock_model, \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_of_day", return_value=created_verse), \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_metadata_bulk"):
        
        result = create_verse_of_day_service(
            request=sample_create_request,
            created_by="test@example.com"
        )
        
        mock_model.assert_called_once_with(
            verse_id=sample_create_request.verse_id,
            ref_id=sample_create_request.ref_id,
            source=sample_create_request.source,
            ref_type=sample_create_request.ref_type,
            image_urls=sample_create_request.image_urls,
            group_id=sample_create_request.group_id,
            date=sample_create_request.date,
            created_by="test@example.com"
        )
        
        assert result.verses == sample_create_request.verses


@pytest.mark.asyncio
async def test_create_verse_of_day_service_conflict_existing_date(sample_create_request, sample_verse_model, mock_db_session):
    """Test creation fails with 409 when verse already exists for the date."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=sample_verse_model):
        
        with pytest.raises(HTTPException) as exc_info:
            create_verse_of_day_service(
                request=sample_create_request,
                created_by="test@example.com"
            )
        
        assert exc_info.value.status_code == 409
        assert "already exists for date" in exc_info.value.detail


# =============================================================================
# get_verses_of_day_list_service() TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_success(sample_verse_list, mock_db_session):
    """Test successful retrieval of verse list with pagination."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", return_value=(sample_verse_list, 2)) as mock_repo:
        
        result = get_verses_of_day_list_service()
        
        assert isinstance(result, VerseOfDayListResponse)
        assert len(result.verses) == 2
        assert result.total == 2
        assert all(isinstance(v, VerseOfDayPublicDTO) for v in result.verses)
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            group_id=None,
            filter_date=None,
            search=None,
            sort_order=SortOrder.DESC,
            skip=0,
            limit=100
        )


@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_with_pagination(sample_verse_list, mock_db_session):
    """Test retrieval with custom skip and limit."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", return_value=(sample_verse_list, 10)) as mock_repo:
        
        result = get_verses_of_day_list_service(skip=5, limit=20)
        
        assert isinstance(result, VerseOfDayListResponse)
        assert result.total == 10
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            group_id=None,
            filter_date=None,
            search=None,
            sort_order=SortOrder.DESC,
            skip=5,
            limit=20
        )


@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_with_group_id_filter(sample_verse_list, mock_db_session):
    """Test retrieval with group_id filter."""
    group_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", return_value=(sample_verse_list, 2)) as mock_repo:
        
        result = get_verses_of_day_list_service(group_id=group_id)
        
        assert isinstance(result, VerseOfDayListResponse)
        assert len(result.verses) == 2
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            group_id=group_id,
            filter_date=None,
            search=None,
            sort_order=SortOrder.DESC,
            skip=0,
            limit=100
        )


@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_with_date_filter(sample_verse_list, mock_db_session):
    """Test retrieval with date filter."""
    filter_date = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", return_value=(sample_verse_list, 2)) as mock_repo:
        
        result = get_verses_of_day_list_service(filter_date=filter_date)
        
        assert isinstance(result, VerseOfDayListResponse)
        
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            group_id=None,
            filter_date=filter_date,
            search=None,
            sort_order=SortOrder.DESC,
            skip=0,
            limit=100
        )


@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_with_search_and_sort_order(sample_verse_list, mock_db_session):
    """Test that search and sort_order are forwarded to the repository."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", return_value=(sample_verse_list, 2)) as mock_repo:

        result = get_verses_of_day_list_service(search="compassion", sort_order=SortOrder.ASC)

        assert isinstance(result, VerseOfDayListResponse)
        mock_repo.assert_called_once_with(
            mock_db_session.__enter__.return_value,
            group_id=None,
            filter_date=None,
            search="compassion",
            sort_order=SortOrder.ASC,
            skip=0,
            limit=100
        )


@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_with_lang_filter(sample_verse_list, mock_db_session):
    """Test retrieval with language filter."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", return_value=(sample_verse_list, 2)):
        
        result = get_verses_of_day_list_service(lang="en")
        
        assert isinstance(result, VerseOfDayListResponse)
        # Each verse should have single verse (not verses dict) when lang filter applied
        for verse_dto in result.verses:
            assert verse_dto.verse is not None
            assert verse_dto.verses is None


@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_empty(mock_db_session):
    """Test retrieval when no verses exist."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", return_value=([], 0)) as mock_repo:
        
        result = get_verses_of_day_list_service()
        
        assert isinstance(result, VerseOfDayListResponse)
        assert len(result.verses) == 0
        assert result.total == 0
        
        mock_repo.assert_called_once()


@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_with_group_info(sample_verse_list, sample_group_metadata, mock_db_session):
    """Test includes group metadata for verses with group_id."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", return_value=(sample_verse_list, 2)), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_group_metadata_by_group_id", return_value=sample_group_metadata):
        
        result = get_verses_of_day_list_service()
        
        assert isinstance(result, VerseOfDayListResponse)
        # First verse has group_id, should have group_info
        assert result.verses[0].group_info is not None
        assert len(result.verses[0].group_info) == 3
        # Second verse has no group_id, should have None group_info
        assert result.verses[1].group_info is None


@pytest.mark.asyncio
async def test_get_verses_of_day_list_service_database_error(mock_db_session):
    """Test handling of database error."""
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verses_of_day_list", side_effect=Exception("Database error")):
        
        with pytest.raises(Exception, match="Database error"):
            get_verses_of_day_list_service()


# =============================================================================
# update_verse_of_day_service() TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_update_verse_of_day_service_success_full(sample_verse_model, sample_update_request, mock_db_session):
    """Test successful full update with all fields."""
    verse_id = uuid4()
    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = "verse-updated"
    updated_verse.ref_id = sample_update_request.ref_id
    updated_verse.source = sample_update_request.source
    updated_verse.ref_type = sample_update_request.ref_type
    updated_verse.image_urls = sample_update_request.image_urls
    updated_verse.group_id = None
    updated_verse.date = date(2025, 6, 10)
    updated_verse.verse_metadata = sample_verse_model.verse_metadata
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model) as mock_get, \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse) as mock_update, \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_metadata_by_verse_id") as mock_delete, \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_metadata_bulk") as mock_create:
        
        result = update_verse_of_day_service(
            verse_id=verse_id,
            request=sample_update_request,
            updated_by="test@example.com"
        )
        
        assert isinstance(result, VerseOfDayDTO)
        assert result.id == verse_id
        assert result.ref_id == sample_update_request.ref_id
        assert result.source == sample_update_request.source
        assert result.ref_type == sample_update_request.ref_type
        
        mock_get.assert_called_once_with(mock_db_session.__enter__.return_value, verse_id)
        mock_update.assert_called_once()
        mock_delete.assert_called_once_with(mock_db_session.__enter__.return_value, verse_id)
        mock_create.assert_called_once_with(mock_db_session.__enter__.return_value, verse_id, sample_update_request.verses)


@pytest.mark.asyncio
async def test_update_verse_of_day_service_success_partial(sample_verse_model, mock_db_session):
    """Test successful partial update with only some fields."""
    verse_id = uuid4()
    partial_request = UpdateVerseOfDayRequest(ref_id="text-partial-update")
    
    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = sample_verse_model.verse_id
    updated_verse.ref_id = "text-partial-update"
    updated_verse.source = sample_verse_model.source
    updated_verse.ref_type = sample_verse_model.ref_type
    updated_verse.image_urls = sample_verse_model.image_urls
    updated_verse.group_id = sample_verse_model.group_id
    updated_verse.date = sample_verse_model.date
    updated_verse.verse_metadata = sample_verse_model.verse_metadata
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse) as mock_update:
        
        result = update_verse_of_day_service(
            verse_id=verse_id,
            request=partial_request,
            updated_by="test@example.com"
        )
        
        assert isinstance(result, VerseOfDayDTO)
        assert result.ref_id == "text-partial-update"
        
        # Verify only ref_id was in updates dict
        call_args = mock_update.call_args
        updates_dict = call_args[0][2]
        assert "ref_id" in updates_dict
        assert updates_dict["ref_id"] == "text-partial-update"


@pytest.mark.asyncio
async def test_update_verse_of_day_service_update_verses_only(sample_verse_model, mock_db_session):
    """Test updating only verses metadata."""
    verse_id = uuid4()
    verses_request = UpdateVerseOfDayRequest(
        verses={"en": "Only verse update"}
    )
    
    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = sample_verse_model.verse_id
    updated_verse.ref_id = sample_verse_model.ref_id
    updated_verse.source = sample_verse_model.source
    updated_verse.ref_type = sample_verse_model.ref_type
    updated_verse.image_urls = sample_verse_model.image_urls
    updated_verse.group_id = sample_verse_model.group_id
    updated_verse.date = sample_verse_model.date
    updated_verse.verse_metadata = sample_verse_model.verse_metadata
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_metadata_by_verse_id") as mock_delete, \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_metadata_bulk") as mock_create:
        
        result = update_verse_of_day_service(
            verse_id=verse_id,
            request=verses_request,
            updated_by="test@example.com"
        )
        
        assert isinstance(result, VerseOfDayDTO)
        mock_delete.assert_called_once()
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_update_verse_of_day_service_not_found(sample_update_request, mock_db_session):
    """Test update fails with 404 when verse doesn't exist."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=None):
        
        with pytest.raises(HTTPException) as exc_info:
            update_verse_of_day_service(
                verse_id=verse_id,
                request=sample_update_request,
                updated_by="test@example.com"
            )
        
        assert exc_info.value.status_code == 404
        assert str(verse_id) in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_verse_of_day_service_updates_correct_fields(sample_verse_model, mock_db_session):
    """Test that only provided fields are updated."""
    verse_id = uuid4()
    request = UpdateVerseOfDayRequest(
        ref_id="new-ref",
        ref_type="new-type",
        date=date(2025, 7, 1)
    )
    
    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = sample_verse_model.verse_id
    updated_verse.ref_id = "new-ref"
    updated_verse.source = sample_verse_model.source
    updated_verse.ref_type = "new-type"
    updated_verse.image_urls = sample_verse_model.image_urls
    updated_verse.group_id = sample_verse_model.group_id
    updated_verse.date = date(2025, 7, 1)
    updated_verse.verse_metadata = sample_verse_model.verse_metadata
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse) as mock_update:
        
        result = update_verse_of_day_service(
            verse_id=verse_id,
            request=request,
            updated_by="test@example.com"
        )
        
        call_args = mock_update.call_args
        updates_dict = call_args[0][2]
        assert "ref_id" in updates_dict
        assert "ref_type" in updates_dict
        assert "date" in updates_dict
        assert "verses" not in updates_dict
        assert "image_urls" not in updates_dict


@pytest.mark.asyncio
async def test_update_verse_of_day_service_source(sample_verse_model, mock_db_session):
    """Test updating only the source field."""
    verse_id = uuid4()
    source_request = UpdateVerseOfDayRequest(source="Lamrim Chenmo")

    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = sample_verse_model.verse_id
    updated_verse.ref_id = sample_verse_model.ref_id
    updated_verse.source = "Lamrim Chenmo"
    updated_verse.ref_type = sample_verse_model.ref_type
    updated_verse.image_urls = sample_verse_model.image_urls
    updated_verse.group_id = sample_verse_model.group_id
    updated_verse.date = sample_verse_model.date
    updated_verse.verse_metadata = sample_verse_model.verse_metadata

    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse) as mock_update:

        result = update_verse_of_day_service(
            verse_id=verse_id,
            request=source_request,
            updated_by="test@example.com"
        )

        assert result.source == "Lamrim Chenmo"
        updates_dict = mock_update.call_args[0][2]
        assert updates_dict == {"source": "Lamrim Chenmo"}


@pytest.mark.asyncio
async def test_update_verse_of_day_service_clears_source(sample_verse_model, mock_db_session):
    """Test that an explicit null source clears the stored abbreviation."""
    verse_id = uuid4()
    clear_request = UpdateVerseOfDayRequest(source=None)

    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = sample_verse_model.verse_id
    updated_verse.ref_id = sample_verse_model.ref_id
    updated_verse.source = None
    updated_verse.ref_type = sample_verse_model.ref_type
    updated_verse.image_urls = sample_verse_model.image_urls
    updated_verse.group_id = sample_verse_model.group_id
    updated_verse.date = sample_verse_model.date
    updated_verse.verse_metadata = sample_verse_model.verse_metadata

    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse) as mock_update:

        result = update_verse_of_day_service(
            verse_id=verse_id,
            request=clear_request,
            updated_by="test@example.com"
        )

        assert result.source is None
        updates_dict = mock_update.call_args[0][2]
        assert updates_dict == {"source": None}


@pytest.mark.asyncio
async def test_update_verse_of_day_service_refreshes_verse(sample_verse_model, sample_update_request, mock_db_session):
    """Test that db.refresh is called on updated verse."""
    verse_id = uuid4()
    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = "verse-updated"
    updated_verse.ref_id = sample_update_request.ref_id
    updated_verse.source = sample_update_request.source
    updated_verse.ref_type = sample_update_request.ref_type
    updated_verse.image_urls = sample_update_request.image_urls
    updated_verse.group_id = None
    updated_verse.date = date(2025, 6, 10)
    updated_verse.verse_metadata = sample_verse_model.verse_metadata
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_metadata_by_verse_id"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_metadata_bulk"):
        
        result = update_verse_of_day_service(
            verse_id=verse_id,
            request=sample_update_request,
            updated_by="test@example.com"
        )
        
        # Verify refresh was called
        mock_db_session.__enter__.return_value.refresh.assert_called_once_with(updated_verse)


@pytest.mark.asyncio
async def test_update_verse_of_day_service_deletes_old_metadata(sample_verse_model, sample_update_request, mock_db_session):
    """Test that old verse metadata is deleted when verses are updated."""
    verse_id = uuid4()
    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = "verse-updated"
    updated_verse.ref_id = sample_update_request.ref_id
    updated_verse.source = sample_update_request.source
    updated_verse.ref_type = sample_update_request.ref_type
    updated_verse.image_urls = sample_update_request.image_urls
    updated_verse.group_id = None
    updated_verse.date = date(2025, 6, 10)
    updated_verse.verse_metadata = sample_verse_model.verse_metadata
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_metadata_by_verse_id") as mock_delete, \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_metadata_bulk"):
        
        update_verse_of_day_service(
            verse_id=verse_id,
            request=sample_update_request,
            updated_by="test@example.com"
        )
        
        mock_delete.assert_called_once_with(mock_db_session.__enter__.return_value, verse_id)


@pytest.mark.asyncio
async def test_update_verse_of_day_service_database_error(sample_update_request, mock_db_session):
    """Test handling of database error during update."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", side_effect=Exception("Database error")):
        
        with pytest.raises(Exception, match="Database error"):
            update_verse_of_day_service(
                verse_id=verse_id,
                request=sample_update_request,
                updated_by="test@example.com"
            )


@pytest.mark.asyncio
async def test_update_verse_of_day_service_returns_dto(sample_verse_model, sample_update_request, mock_db_session):
    """Test that service returns correct DTO structure."""
    verse_id = uuid4()
    updated_verse = MagicMock()
    updated_verse.id = verse_id
    updated_verse.verse_id = "verse-updated"
    updated_verse.ref_id = sample_update_request.ref_id
    updated_verse.source = sample_update_request.source
    updated_verse.ref_type = sample_update_request.ref_type
    updated_verse.image_urls = sample_update_request.image_urls
    updated_verse.group_id = None
    updated_verse.date = date(2025, 6, 10)
    updated_verse.verse_metadata = sample_verse_model.verse_metadata
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.update_verse_of_day", return_value=updated_verse), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_metadata_by_verse_id"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.create_verse_metadata_bulk"):
        
        result = update_verse_of_day_service(
            verse_id=verse_id,
            request=sample_update_request,
            updated_by="test@example.com"
        )
        
        assert isinstance(result, VerseOfDayDTO)
        assert hasattr(result, 'id')
        assert hasattr(result, 'verses')
        assert hasattr(result, 'verse_id')
        assert hasattr(result, 'ref_id')
        assert hasattr(result, 'ref_type')
        assert hasattr(result, 'image_urls')
        assert hasattr(result, 'group_id')
        assert hasattr(result, 'date')


# =============================================================================
# delete_verse_of_day_service() TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_delete_verse_of_day_service_success(sample_verse_model, mock_db_session):
    """Test successful deletion of verse."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model) as mock_get, \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_of_day") as mock_delete:
        
        result = delete_verse_of_day_service(verse_id=verse_id)
        
        assert result is None
        mock_get.assert_called_once_with(mock_db_session.__enter__.return_value, verse_id)
        mock_delete.assert_called_once_with(mock_db_session.__enter__.return_value, verse_id)


@pytest.mark.asyncio
async def test_delete_verse_of_day_service_not_found(mock_db_session):
    """Test deletion fails with 404 when verse doesn't exist."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=None):
        
        with pytest.raises(HTTPException) as exc_info:
            delete_verse_of_day_service(verse_id=verse_id)
        
        assert exc_info.value.status_code == 404
        assert str(verse_id) in exc_info.value.detail


@pytest.mark.asyncio
async def test_delete_verse_of_day_service_calls_repository(sample_verse_model, mock_db_session):
    """Test that repository delete function is called correctly."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_of_day") as mock_delete:
        
        delete_verse_of_day_service(verse_id=verse_id)
        
        mock_delete.assert_called_once_with(mock_db_session.__enter__.return_value, verse_id)


@pytest.mark.asyncio
async def test_delete_verse_of_day_service_database_error(sample_verse_model, mock_db_session):
    """Test handling of database error during deletion."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_of_day", side_effect=Exception("Database error")):
        
        with pytest.raises(Exception, match="Database error"):
            delete_verse_of_day_service(verse_id=verse_id)


@pytest.mark.asyncio
async def test_delete_verse_of_day_service_returns_none(sample_verse_model, mock_db_session):
    """Test that service returns None on successful deletion."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_id", return_value=sample_verse_model), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verse_of_day"):
        
        result = delete_verse_of_day_service(verse_id=verse_id)
        
        assert result is None


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_get_verse_of_day_service_empty_image_urls(mock_db_session):
    """Test verse with empty image_urls array returns None."""
    verse = MagicMock()
    verse.id = uuid4()
    verse.ref_id = "text-empty"
    verse.source = None
    verse.ref_type = "commentary"
    verse.image_urls = []
    verse.group_id = None
    verse.date = date(2025, 6, 5)
    verse.verse_metadata = []
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=verse):
        
        result = get_verse_of_day()
        
        # Empty list returns None
        assert result.verse_of_day.image_url is None


@pytest.mark.asyncio
async def test_get_verse_of_day_service_none_image_urls(mock_db_session):
    """Test verse with None image_url."""
    verse = MagicMock()
    verse.id = uuid4()
    verse.ref_id = "text-none"
    verse.source = None
    verse.ref_type = "commentary"
    verse.image_urls = None
    verse.group_id = None
    verse.date = date(2025, 6, 5)
    verse.verse_metadata = []
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=verse):
        
        result = get_verse_of_day()
        
        assert result.verse_of_day.image_url is None


@pytest.mark.asyncio
async def test_get_verse_of_day_service_empty_verse_metadata(mock_db_session):
    """Test verse with no verse_metadata entries."""
    verse = MagicMock()
    verse.id = uuid4()
    verse.ref_id = "text-no-metadata"
    verse.source = None
    verse.ref_type = "commentary"
    verse.image_urls = None
    verse.group_id = None
    verse.date = date(2025, 6, 5)
    verse.verse_metadata = []
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.get_verse_of_day_by_filters", return_value=verse):
        
        result = get_verse_of_day()
        
        assert result.verse_of_day.verses is None


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================

def test_build_verses_dict(sample_verse_metadata):
    """Test build_verses_dict helper function."""
    result = build_verses_dict(sample_verse_metadata)
    
    assert "en" in result
    assert "bo" in result
    assert "zh" in result
    assert result["en"] == "May all beings be happy and free from suffering."
    # Tibetan verse is stored as JSON string
    assert isinstance(result["bo"], str)
    assert result["bo"].startswith('[')


def test_build_verses_dict_empty():
    """Test build_verses_dict with empty list."""
    result = build_verses_dict([])
    
    assert result == {}


def test_build_public_dto_all_languages(sample_verse_model):
    """Test build_public_dto returns all languages when no lang filter."""
    result = build_public_dto(sample_verse_model)
    
    assert result.verses is not None
    assert result.verse is None
    assert "en" in result.verses
    assert "bo" in result.verses
    assert "zh" in result.verses
    assert result.source == "Dhp 1.5"


def test_build_public_dto_single_language(sample_verse_model):
    """Test build_public_dto returns single verse when lang filter provided."""
    result = build_public_dto(sample_verse_model, lang="en")
    
    assert result.verse == "May all beings be happy and free from suffering."
    assert result.verses is None
    assert result.source == "Dhp 1.5"


def test_build_public_dto_invalid_language(sample_verse_model):
    """Test build_public_dto returns all languages when invalid lang provided."""
    result = build_public_dto(sample_verse_model, lang="fr")
    
    assert result.verses is not None
    assert result.verse is None


# =============================================================================
# _generate_verse_image_url() TESTS
# =============================================================================

def test_generate_verse_image_url_success():
    """Test successful generation of presigned URL from first S3 key."""
    s3_keys = ["images/verse_images/uuid1/image1.jpg", "images/verse_images/uuid2/image2.jpg"]
    presigned_url1 = "https://bucket.s3.amazonaws.com/images/verse_images/uuid1/image1.jpg?X-Amz-Signature=..."
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.get", return_value="test-bucket"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.generate_presigned_access_url", return_value=presigned_url1) as mock_presigned:
        
        result = _generate_verse_image_url(s3_keys)
        
        assert result == presigned_url1  # Returns first URL as string
        mock_presigned.assert_called_once_with("test-bucket", s3_keys[0])


def test_generate_verse_image_url_none_input():
    """Test returns None when input is None."""
    result = _generate_verse_image_url(None)
    assert result is None


def test_generate_verse_image_url_empty_list():
    """Test returns None when input is empty list."""
    result = _generate_verse_image_url([])
    assert result is None


def test_generate_verse_image_url_single_key():
    """Test generation with single S3 key."""
    s3_keys = ["images/verse_images/uuid1/image1.jpg"]
    presigned_url = "https://bucket.s3.amazonaws.com/images/verse_images/uuid1/image1.jpg?X-Amz-Signature=..."
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.get", return_value="test-bucket"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.generate_presigned_access_url", return_value=presigned_url) as mock_presigned:
        
        result = _generate_verse_image_url(s3_keys)
        
        assert result == presigned_url
        mock_presigned.assert_called_once_with("test-bucket", s3_keys[0])


def test_generate_verse_image_url_skips_empty_strings():
    """Test skips empty or whitespace-only strings and returns first valid."""
    s3_keys = ["", "   ", "images/verse_images/uuid1/image1.jpg", "images/verse_images/uuid2/image2.jpg"]
    presigned_url1 = "https://bucket.s3.amazonaws.com/images/verse_images/uuid1/image1.jpg?X-Amz-Signature=..."
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.get", return_value="test-bucket"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.generate_presigned_access_url", return_value=presigned_url1) as mock_presigned:
        
        result = _generate_verse_image_url(s3_keys)
        
        assert result == presigned_url1  # Returns first valid URL
        mock_presigned.assert_called_once_with("test-bucket", s3_keys[2])


def test_generate_verse_image_url_skips_non_string():
    """Test skips non-string values and returns first valid string."""
    s3_keys = [None, 123, "images/verse_images/uuid1/image1.jpg", "images/verse_images/uuid2/image2.jpg"]
    presigned_url1 = "https://bucket.s3.amazonaws.com/images/verse_images/uuid1/image1.jpg?X-Amz-Signature=..."
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.get", return_value="test-bucket"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.generate_presigned_access_url", return_value=presigned_url1) as mock_presigned:
        
        result = _generate_verse_image_url(s3_keys)
        
        assert result == presigned_url1
        mock_presigned.assert_called_once_with("test-bucket", s3_keys[2])


def test_generate_verse_image_url_handles_exception():
    """Test gracefully handles exception and tries next key."""
    s3_keys = ["images/verse_images/uuid1/image1.jpg", "images/verse_images/uuid2/image2.jpg"]
    presigned_url2 = "https://bucket.s3.amazonaws.com/images/verse_images/uuid2/image2.jpg?X-Amz-Signature=..."
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.get", return_value="test-bucket"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.generate_presigned_access_url") as mock_presigned, \
         patch("pecha_api.verse_of_day.verse_of_day_service.logger") as mock_logger:
        
        # First call raises exception, second succeeds
        mock_presigned.side_effect = [Exception("S3 NoSuchKey error"), presigned_url2]
        
        result = _generate_verse_image_url(s3_keys)
        
        assert result == presigned_url2  # Returns second URL after first fails
        assert mock_presigned.call_count == 2
        mock_logger.error.assert_called_once()  # Error was logged


def test_generate_verse_image_url_returns_empty_string():
    """Test tries next key when presigned URL generation returns empty string."""
    s3_keys = ["images/verse_images/uuid1/image1.jpg", "images/verse_images/uuid2/image2.jpg"]
    presigned_url2 = "https://bucket.s3.amazonaws.com/images/verse_images/uuid2/image2.jpg?X-Amz-Signature=..."
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.get", return_value="test-bucket"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.generate_presigned_access_url") as mock_presigned:
        
        # First returns empty string, second succeeds
        mock_presigned.side_effect = ["", presigned_url2]
        
        result = _generate_verse_image_url(s3_keys)
        
        assert result == presigned_url2  # Returns second URL
        assert mock_presigned.call_count == 2


def test_generate_verse_image_url_all_fail_returns_none():
    """Test returns None when all URL generations fail."""
    s3_keys = ["images/verse_images/uuid1/image1.jpg", "images/verse_images/uuid2/image2.jpg"]
    
    with patch("pecha_api.verse_of_day.verse_of_day_service.get", return_value="test-bucket"), \
         patch("pecha_api.verse_of_day.verse_of_day_service.generate_presigned_access_url") as mock_presigned, \
         patch("pecha_api.verse_of_day.verse_of_day_service.logger"):
        
        # All calls raise exceptions
        mock_presigned.side_effect = [Exception("Error 1"), Exception("Error 2")]
        
        result = _generate_verse_image_url(s3_keys)
        
        assert result is None  # No valid URLs generated


def test_cleanup_expired_verses_of_day(mock_db_session):
    """Test cleanup deletes verses older than the expiry window."""
    from datetime import datetime, timedelta, timezone

    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verses_of_day_older_than", return_value=3) as mock_delete:

        result = cleanup_expired_verses_of_day(expiry_days=7)

        assert result == 3
        mock_delete.assert_called_once()
        cutoff_date = mock_delete.call_args[0][1]
        expected_cutoff = datetime.now(timezone.utc).date() - timedelta(days=7)
        assert cutoff_date == expected_cutoff


def test_cleanup_expired_verses_of_day_rejects_non_positive_expiry(mock_db_session):
    with patch("pecha_api.verse_of_day.verse_of_day_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.verse_of_day.verse_of_day_service.delete_verses_of_day_older_than") as mock_delete:

        with pytest.raises(ValueError, match="positive integer"):
            cleanup_expired_verses_of_day(expiry_days=0)

        with pytest.raises(ValueError, match="positive integer"):
            cleanup_expired_verses_of_day(expiry_days=-1)

        mock_delete.assert_not_called()
