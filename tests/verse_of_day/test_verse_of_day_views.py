import pytest
from uuid import uuid4
from datetime import date
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.verse_of_day.verse_of_day_response_models import (
    VerseOfDayPublicResponse,
    VerseOfDayPublicDTO,
    VerseOfDayDTO,
    CreateVerseOfDayRequest,
    UpdateVerseOfDayRequest,
    VerseOfDayListResponse,
    GroupInfoDTO,
)
from pecha_api.verse_of_day.verse_of_day_enums import SortOrder


client = TestClient(api)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_verse_public_dto():
    """Sample public verse DTO for testing (all languages)."""
    return VerseOfDayPublicDTO(
        id=uuid4(),
        verses={
            "en": "May all beings be happy and free from suffering.",
            "bo": "སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་། སྡུག་བསྔལ་བྲལ་བར་གྱུར་ཅིག",
            "zh": "愿一切众生快乐，远离痛苦。"
        },
        image_url="https://example.com/image1.jpg",
        ref_id="text-123",
        source="Dhp 1.5",
        ref_type="sutra",
        date=date(2025, 6, 5)
    )


@pytest.fixture
def sample_verse_public_response(sample_verse_public_dto):
    """Sample public response with verse."""
    return VerseOfDayPublicResponse(verse_of_day=sample_verse_public_dto)


@pytest.fixture
def sample_empty_response():
    """Sample response with no verse found."""
    return VerseOfDayPublicResponse(verse_of_day=None)


@pytest.fixture
def sample_verse_dto():
    """Sample full verse DTO for creation response."""
    return VerseOfDayDTO(
        id=uuid4(),
        verses={
            "en": "May all beings be happy and free from suffering.",
            "bo": "སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་། སྡུག་བསྔལ་བྲལ་བར་གྱུར་ཅིག",
            "zh": "愿一切众生快乐，远离痛苦。"
        },
        image_url="https://example.com/image1.jpg",
        verse_id="verse-456",
        ref_id="text-123",
        source="Dhp 1.5",
        ref_type="sutra",
        group_id=uuid4(),
        date=date(2025, 6, 5)
    )


@pytest.fixture
def sample_create_request():
    """Sample create verse request with multilingual verses."""
    return CreateVerseOfDayRequest(
        verses={
            "en": "May all beings be happy and free from suffering.",
            "bo": "སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་། སྡུག་བསྔལ་བྲལ་བར་གྱུར་ཅིག",
            "zh": "愿一切众生快乐，远离痛苦。"
        },
        image_url="https://example.com/image1.jpg",
        verse_id="verse-456",
        ref_id="text-123",
        source="Dhp 1.5",
        ref_type="sutra",
        group_id=uuid4(),
        date=date(2025, 6, 5)
    )


@pytest.fixture
def sample_group_info():
    """Sample GroupInfoDTO list for all languages."""
    return [
        GroupInfoDTO(
            id=uuid4(),
            title="English Title",
            sub_title="English Subtitle",
            description="English description",
            language="EN"
        ),
        GroupInfoDTO(
            id=uuid4(),
            title="བོད་ཡིག་མིང་།",
            sub_title="བོད་ཡིག་ཡན་ལག་མིང་།",
            description="བོད་ཡིག་གསལ་བཤད།",
            language="BO"
        ),
        GroupInfoDTO(
            id=uuid4(),
            title="中文标题",
            sub_title="中文副标题",
            description="中文描述",
            language="zh"
        )
    ]


@pytest.fixture
def sample_verse_public_dto_with_group_info(sample_group_info):
    """VerseOfDayPublicDTO with group_info included."""
    return VerseOfDayPublicDTO(
        id=uuid4(),
        verses={
            "en": "May all beings be happy and free from suffering.",
            "bo": "སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་། སྡུག་བསྔལ་བྲལ་བར་གྱུར་ཅིག",
            "zh": "愿一切众生快乐，远离痛苦。"
        },
        image_url="https://example.com/image1.jpg",
        ref_id="text-123",
        source="Dhp 1.5",
        ref_type="sutra",
        date=date(2025, 6, 5),
        group_info=sample_group_info
    )


@pytest.fixture
def sample_verse_list_response(sample_verse_public_dto):
    """Sample list response with verses."""
    return VerseOfDayListResponse(
        verses=[sample_verse_public_dto],
        total=1
    )


@pytest.fixture
def sample_update_request():
    """Sample update verse request."""
    return UpdateVerseOfDayRequest(
        verses={"en": "Updated verse text."},
        image_urls=["https://example.com/updated-image.jpg"],
        ref_id="text-updated",
        source="Lamrim Chenmo",
        ref_type="commentary"
    )


# =============================================================================
# GET /verse-of-day TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_get_verse_of_day_success(sample_verse_public_response):
    """Test successful retrieval of verse of day with no filters."""
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=sample_verse_public_response) as mock_service:
        response = client.get("/verse-of-day")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "verse_of_day" in data
        assert data["verse_of_day"] is not None
        assert "verses" in data["verse_of_day"]
        assert "en" in data["verse_of_day"]["verses"]
        assert data["verse_of_day"]["ref_id"] == "text-123"
        assert data["verse_of_day"]["source"] == "Dhp 1.5"
        assert data["verse_of_day"]["ref_type"] == "sutra"
        assert "image_url" in data["verse_of_day"]
        assert "date" in data["verse_of_day"]
        
        mock_service.assert_called_once_with(group_id=None, filter_date=None, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_with_group_id_filter(sample_verse_public_response):
    """Test retrieval of verse filtered by group_id."""
    group_id = uuid4()
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=sample_verse_public_response) as mock_service:
        response = client.get(f"/verse-of-day?group_id={group_id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"] is not None
        mock_service.assert_called_once_with(group_id=group_id, filter_date=None, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_with_date_filter(sample_verse_public_response):
    """Test retrieval of verse filtered by date."""
    filter_date = date(2025, 6, 5)
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=sample_verse_public_response) as mock_service:
        response = client.get(f"/verse-of-day?date=2025-06-05")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"] is not None
        mock_service.assert_called_once_with(group_id=None, filter_date=filter_date, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_with_both_filters(sample_verse_public_response):
    """Test retrieval of verse with both group_id and date filters."""
    group_id = uuid4()
    filter_date = date(2025, 6, 5)
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=sample_verse_public_response) as mock_service:
        response = client.get(f"/verse-of-day?group_id={group_id}&date=2025-06-05")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"] is not None
        mock_service.assert_called_once_with(group_id=group_id, filter_date=filter_date, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_not_found(sample_empty_response):
    """Test retrieval when no verse is found."""
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=sample_empty_response) as mock_service:
        response = client.get("/verse-of-day")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"] is None
        mock_service.assert_called_once_with(group_id=None, filter_date=None, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_invalid_uuid():
    """Test retrieval with invalid group_id UUID format."""
    response = client.get("/verse-of-day?group_id=invalid-uuid")
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_verse_of_day_invalid_date():
    """Test retrieval with invalid date format."""
    response = client.get("/verse-of-day?date=invalid-date")
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_verse_of_day_database_error():
    """Test handling of database error."""
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", side_effect=HTTPException(status_code=500, detail="Database connection error")) as mock_service:
        response = client.get("/verse-of-day")
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Database connection error"
        mock_service.assert_called_once_with(group_id=None, filter_date=None, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_with_group_info_in_response(sample_verse_public_dto_with_group_info):
    """Test response includes group_info array."""
    response_with_group_info = VerseOfDayPublicResponse(verse_of_day=sample_verse_public_dto_with_group_info)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=response_with_group_info) as mock_service:
        response = client.get("/verse-of-day")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "group_info" in data["verse_of_day"]
        assert data["verse_of_day"]["group_info"] is not None
        assert len(data["verse_of_day"]["group_info"]) == 3
        assert data["verse_of_day"]["group_info"][0]["language"] == "EN"
        assert data["verse_of_day"]["group_info"][1]["language"] == "BO"
        assert data["verse_of_day"]["group_info"][2]["language"] == "zh"


@pytest.mark.asyncio
async def test_get_verse_of_day_with_lang_filter_filters_group_info(sample_group_info):
    """Test group_info filtered when lang=zh."""
    filtered_dto = VerseOfDayPublicDTO(
        id=uuid4(),
        verse="愿一切众生快乐，远离痛苦。",
        verses=None,
        image_url="https://example.com/image1.jpg",
        ref_id="text-123",
        ref_type="sutra",
        date=date(2025, 6, 5),
        group_info=[sample_group_info[2]]  # Only zh
    )
    response_filtered = VerseOfDayPublicResponse(verse_of_day=filtered_dto)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=response_filtered) as mock_service:
        response = client.get("/verse-of-day?lang=zh")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "group_info" in data["verse_of_day"]
        assert len(data["verse_of_day"]["group_info"]) == 1
        assert data["verse_of_day"]["group_info"][0]["language"] == "zh"
        assert data["verse_of_day"]["group_info"][0]["title"] == "中文标题"


@pytest.mark.asyncio
async def test_get_verse_of_day_group_info_structure(sample_verse_public_dto_with_group_info):
    """Test validates group_info DTO structure."""
    response_with_group_info = VerseOfDayPublicResponse(verse_of_day=sample_verse_public_dto_with_group_info)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=response_with_group_info) as mock_service:
        response = client.get("/verse-of-day")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        group_info = data["verse_of_day"]["group_info"][0]
        assert "id" in group_info
        assert "title" in group_info
        assert "sub_title" in group_info
        assert "description" in group_info
        assert "language" in group_info


# =============================================================================
# GET /verse-of-day/today TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_get_verse_of_day_today_success(sample_verse_public_response):
    """Test successful retrieval of today's verse."""
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service", return_value=sample_verse_public_response) as mock_service:
        response = client.get("/verse-of-day/today")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "verse_of_day" in data
        assert data["verse_of_day"] is not None
        assert "verses" in data["verse_of_day"]
        assert data["verse_of_day"]["ref_id"] == "text-123"
        assert data["verse_of_day"]["source"] == "Dhp 1.5"
        
        mock_service.assert_called_once_with(lang=None, timezone=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_today_not_found(sample_empty_response):
    """Test retrieval when no verse exists for today."""
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service", return_value=sample_empty_response) as mock_service:
        response = client.get("/verse-of-day/today")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"] is None
        mock_service.assert_called_once_with(lang=None, timezone=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_today_database_error():
    """Test handling of database error for today's verse."""
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service", side_effect=HTTPException(status_code=500, detail="Database connection error")) as mock_service:
        response = client.get("/verse-of-day/today")
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Database connection error"
        mock_service.assert_called_once_with(lang=None, timezone=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_today_with_timezone_header_america(sample_verse_public_response):
    """Test today's verse uses X-Timezone header with an American timezone."""
    with patch(
        "pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service",
        return_value=sample_verse_public_response,
    ) as mock_service:
        response = client.get(
            "/verse-of-day/today",
            headers={"X-Timezone": "America/New_York"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(lang=None, timezone="America/New_York")


@pytest.mark.asyncio
async def test_get_verse_of_day_today_with_timezone_header(sample_verse_public_response):
    """Test today's verse uses X-Timezone header."""
    with patch(
        "pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service",
        return_value=sample_verse_public_response,
    ) as mock_service:
        response = client.get(
            "/verse-of-day/today",
            headers={"X-Timezone": "Asia/Kathmandu"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(lang=None, timezone="Asia/Kathmandu")


@pytest.mark.asyncio
async def test_get_verse_of_day_today_ignores_timezone_query_param(sample_verse_public_response):
    """Test X-Timezone header is used when a timezone query param is also sent."""
    with patch(
        "pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service",
        return_value=sample_verse_public_response,
    ) as mock_service:
        response = client.get(
            "/verse-of-day/today?timezone=America/New_York",
            headers={"X-Timezone": "Asia/Kathmandu"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(lang=None, timezone="Asia/Kathmandu")


@pytest.mark.asyncio
async def test_get_verse_of_day_today_invalid_timezone():
    """Test invalid timezone returns 422."""
    response = client.get(
        "/verse-of-day/today",
        headers={"X-Timezone": "Not/A_Timezone"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Invalid timezone" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_verse_of_day_today_with_group_info(sample_verse_public_dto_with_group_info):
    """Test response includes group_info."""
    response_with_group_info = VerseOfDayPublicResponse(verse_of_day=sample_verse_public_dto_with_group_info)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service", return_value=response_with_group_info) as mock_service:
        response = client.get("/verse-of-day/today")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "group_info" in data["verse_of_day"]
        assert len(data["verse_of_day"]["group_info"]) == 3


@pytest.mark.asyncio
async def test_get_verse_of_day_today_with_lang_filter_filters_group_info(sample_group_info):
    """Test group_info filtered by lang."""
    filtered_dto = VerseOfDayPublicDTO(
        id=uuid4(),
        verse="སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་། སྡུག་བསྔལ་བྲལ་བར་གྱུར་ཅིག",
        verses=None,
        image_url="https://example.com/image1.jpg",
        ref_id="text-123",
        ref_type="sutra",
        date=date(2025, 6, 5),
        group_info=[sample_group_info[1]]  # Only BO
    )
    response_filtered = VerseOfDayPublicResponse(verse_of_day=filtered_dto)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service", return_value=response_filtered) as mock_service:
        response = client.get("/verse-of-day/today?lang=bo")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "group_info" in data["verse_of_day"]
        assert len(data["verse_of_day"]["group_info"]) == 1
        assert data["verse_of_day"]["group_info"][0]["language"] == "BO"


# =============================================================================
# GET /verse-of-day/{id} TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_success(sample_verse_public_response):
    """Test successful retrieval of verse by ID."""
    verse_id = uuid4()
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_by_id_service", return_value=sample_verse_public_response) as mock_service:
        response = client.get(f"/verse-of-day/{verse_id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "verse_of_day" in data
        assert data["verse_of_day"] is not None
        assert "verses" in data["verse_of_day"]
        
        mock_service.assert_called_once_with(verse_id=verse_id, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_not_found(sample_empty_response):
    """Test retrieval when verse ID doesn't exist."""
    verse_id = uuid4()
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_by_id_service", return_value=sample_empty_response) as mock_service:
        response = client.get(f"/verse-of-day/{verse_id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"] is None
        mock_service.assert_called_once_with(verse_id=verse_id, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_invalid_uuid():
    """Test retrieval with invalid UUID format."""
    response = client.get("/verse-of-day/invalid-uuid")
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_database_error():
    """Test handling of database error when fetching by ID."""
    verse_id = uuid4()
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_by_id_service", side_effect=HTTPException(status_code=500, detail="Database connection error")) as mock_service:
        response = client.get(f"/verse-of-day/{verse_id}")
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Database connection error"
        mock_service.assert_called_once_with(verse_id=verse_id, lang=None)


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_with_group_info(sample_verse_public_dto_with_group_info):
    """Test response includes group_info."""
    verse_id = uuid4()
    response_with_group_info = VerseOfDayPublicResponse(verse_of_day=sample_verse_public_dto_with_group_info)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_by_id_service", return_value=response_with_group_info) as mock_service:
        response = client.get(f"/verse-of-day/{verse_id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "group_info" in data["verse_of_day"]
        assert len(data["verse_of_day"]["group_info"]) == 3


@pytest.mark.asyncio
async def test_get_verse_of_day_by_id_with_lang_filter_filters_group_info(sample_group_info):
    """Test group_info filtered by lang."""
    verse_id = uuid4()
    filtered_dto = VerseOfDayPublicDTO(
        id=uuid4(),
        verse="May all beings be happy and free from suffering.",
        verses=None,
        image_url="https://example.com/image1.jpg",
        ref_id="text-123",
        ref_type="sutra",
        date=date(2025, 6, 5),
        group_info=[sample_group_info[0]]  # Only EN
    )
    response_filtered = VerseOfDayPublicResponse(verse_of_day=filtered_dto)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_by_id_service", return_value=response_filtered) as mock_service:
        response = client.get(f"/verse-of-day/{verse_id}?lang=en")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "group_info" in data["verse_of_day"]
        assert len(data["verse_of_day"]["group_info"]) == 1
        assert data["verse_of_day"]["group_info"][0]["language"] == "EN"


# =============================================================================
# POST /cms/verse-of-day TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_create_verse_of_day_success(sample_verse_dto):
    """Test successful creation of verse of day with authentication."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.create_verse_of_day_service", return_value=sample_verse_dto) as mock_create:
        
        request_data = {
            "verses": {
                "en": "May all beings be happy and free from suffering.",
                "bo": "སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་། སྡུག་བསྔལ་བྲལ་བར་གྱུར་ཅིག",
                "zh": "愿一切众生快乐，远离痛苦。"
            },
            "image_urls": ["https://example.com/image1.jpg"],
            "verse_id": "verse-456",
            "ref_id": "text-123",
            "source": "Dhp 1.5",
            "ref_type": "sutra",
            "group_id": str(uuid4()),
            "date": "2025-06-05"
        }
        
        response = client.post(
            "/cms/verse-of-day",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        
        assert "id" in data
        assert "verses" in data
        assert data["verse_id"] == sample_verse_dto.verse_id
        assert data["ref_id"] == sample_verse_dto.ref_id
        assert data["source"] == sample_verse_dto.source
        assert data["ref_type"] == sample_verse_dto.ref_type
        
        mock_validate.assert_called_once_with("valid-token")
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_create_verse_of_day_with_optional_fields(sample_verse_dto):
    """Test creation with optional fields (image_urls and group_id)."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.create_verse_of_day_service", return_value=sample_verse_dto) as mock_create:
        
        request_data = {
            "verses": {"en": "May all beings be happy."},
            "verse_id": "verse-789",
            "ref_id": "text-456",
            "ref_type": "tantra",
            "date": "2025-06-06"
        }
        
        response = client.post(
            "/cms/verse-of-day",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        mock_validate.assert_called_once_with("valid-token")
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_create_verse_of_day_missing_required_fields():
    """Test creation with missing required fields."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author):
        request_data = {
            "verses": {"en": "May all beings be happy."}
        }
        
        response = client.post(
            "/cms/verse-of-day",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_create_verse_of_day_source_exceeds_max_length():
    """Test creation rejects source values longer than the 255-character column."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"

    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author):
        request_data = {
            "verses": {"en": "May all beings be happy."},
            "source": "a" * 256,
            "date": "2025-06-06"
        }

        response = client.post(
            "/cms/verse-of-day",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_create_verse_of_day_invalid_token():
    """Test creation with invalid authentication token."""
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", side_effect=HTTPException(status_code=401, detail="Invalid token")) as mock_validate:
        
        request_data = {
            "verses": {"en": "May all beings be happy."},
            "verse_id": "verse-789",
            "ref_id": "text-456",
            "ref_type": "tantra",
            "date": "2025-06-06"
        }
        
        response = client.post(
            "/cms/verse-of-day",
            json=request_data,
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "Invalid token"
        mock_validate.assert_called_once_with("invalid-token")


@pytest.mark.asyncio
async def test_create_verse_of_day_missing_auth():
    """Test creation without authentication header."""
    request_data = {
        "verses": {"en": "May all beings be happy."},
        "verse_id": "verse-789",
        "ref_id": "text-456",
        "ref_type": "tantra",
        "date": "2025-06-06"
    }
    
    response = client.post(
        "/cms/verse-of-day",
        json=request_data
    )
    
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_create_verse_of_day_database_error():
    """Test handling of database error during creation."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.create_verse_of_day_service", side_effect=HTTPException(status_code=500, detail="Database error")) as mock_create:
        
        request_data = {
            "verses": {"en": "May all beings be happy."},
            "verse_id": "verse-789",
            "ref_id": "text-456",
            "ref_type": "tantra",
            "date": "2025-06-06"
        }
        
        response = client.post(
            "/cms/verse-of-day",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Database error"
        mock_validate.assert_called_once_with("valid-token")
        mock_create.assert_called_once()


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

@pytest.mark.asyncio

async def test_get_verse_of_day_with_empty_image_url():

    verse_dto = VerseOfDayPublicDTO(
        id=uuid4(),
        verses={"en": "Simple verse without images."},
        image_url=None,
        ref_id="text-empty",
        ref_type="commentary",
        date=date(2025, 6, 5)
    )
    response_dto = VerseOfDayPublicResponse(verse_of_day=verse_dto)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=response_dto) as mock_service:
        response = client.get("/verse-of-day")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"]["image_url"] is None
        mock_service.assert_called_once_with(group_id=None, filter_date=None, lang=None)


@pytest.mark.asyncio

async def test_get_verse_of_day_with_none_image_url():

    verse_dto = VerseOfDayPublicDTO(
        id=uuid4(),
        verses={"en": "Simple verse without images."},
        image_url=None,
        ref_id="text-none",
        ref_type="commentary",
        date=date(2025, 6, 5)
    )
    response_dto = VerseOfDayPublicResponse(verse_of_day=verse_dto)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day", return_value=response_dto) as mock_service:
        response = client.get("/verse-of-day")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"]["image_url"] is None
        mock_service.assert_called_once_with(group_id=None, filter_date=None, lang=None)


# =============================================================================
# GET /cms/verse-of-day TESTS (List with pagination)
# =============================================================================

@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_success(sample_verse_list_response):
    """Test successful retrieval of verse list with authentication."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verses_of_day_list_service", return_value=sample_verse_list_response) as mock_service:
        
        response = client.get(
            "/cms/verse-of-day",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "verses" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["verses"]) == 1
        
        mock_validate.assert_called_once_with("valid-token")
        mock_service.assert_called_once_with(group_id=None, filter_date=None, lang=None, search=None, sort_order=SortOrder.DESC, skip=0, limit=100)


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_with_pagination(sample_verse_list_response):
    """Test retrieval with custom pagination parameters."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verses_of_day_list_service", return_value=sample_verse_list_response) as mock_service:
        
        response = client.get(
            "/cms/verse-of-day?skip=10&limit=20",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_validate.assert_called_once_with("valid-token")
        mock_service.assert_called_once_with(group_id=None, filter_date=None, lang=None, search=None, sort_order=SortOrder.DESC, skip=10, limit=20)


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_with_filters(sample_verse_list_response):
    """Test retrieval with group_id, date, and lang filters."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    group_id = uuid4()
    filter_date = date(2025, 6, 5)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verses_of_day_list_service", return_value=sample_verse_list_response) as mock_service:
        
        response = client.get(
            f"/cms/verse-of-day?group_id={group_id}&date=2025-06-05&lang=en",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_validate.assert_called_once_with("valid-token")
        mock_service.assert_called_once_with(group_id=group_id, filter_date=filter_date, lang="en", search=None, sort_order=SortOrder.DESC, skip=0, limit=100)


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_with_search_and_sort_order(sample_verse_list_response):
    """Test retrieval with search and ascending sort order."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"

    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verses_of_day_list_service", return_value=sample_verse_list_response) as mock_service:

        response = client.get(
            "/cms/verse-of-day?search=compassion&sort_order=asc",
            headers={"Authorization": "Bearer valid-token"}
        )

        assert response.status_code == status.HTTP_200_OK
        mock_validate.assert_called_once_with("valid-token")
        mock_service.assert_called_once_with(group_id=None, filter_date=None, lang=None, search="compassion", sort_order=SortOrder.ASC, skip=0, limit=100)


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_invalid_sort_order():
    """Test that an invalid sort_order value is rejected."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"

    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author):
        response = client.get(
            "/cms/verse-of-day?sort_order=sideways",
            headers={"Authorization": "Bearer valid-token"}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_empty():
    """Test retrieval when no verses exist."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    empty_response = VerseOfDayListResponse(verses=[], total=0)
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verses_of_day_list_service", return_value=empty_response) as mock_service:
        
        response = client.get(
            "/cms/verse-of-day",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verses"] == []
        assert data["total"] == 0
        mock_validate.assert_called_once_with("valid-token")


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_invalid_auth():
    """Test retrieval with invalid authentication token."""
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", side_effect=HTTPException(status_code=401, detail="Invalid token")) as mock_validate:
        
        response = client.get(
            "/cms/verse-of-day",
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "Invalid token"
        mock_validate.assert_called_once_with("invalid-token")


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_missing_auth():
    """Test retrieval without authentication header."""
    response = client.get("/cms/verse-of-day")
    
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_list_database_error():
    """Test handling of database error."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verses_of_day_list_service", side_effect=HTTPException(status_code=500, detail="Database error")) as mock_service:
        
        response = client.get(
            "/cms/verse-of-day",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Database error"
        mock_validate.assert_called_once_with("valid-token")


# =============================================================================
# GET /cms/verse-of-day/{id} TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_cms_get_verse_of_day_by_id_success(sample_verse_public_response):
    """Test successful retrieval of verse by ID with authentication."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_by_id_service", return_value=sample_verse_public_response) as mock_service:
        
        response = client.get(
            f"/cms/verse-of-day/{verse_id}",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "verse_of_day" in data
        assert data["verse_of_day"] is not None
        
        mock_validate.assert_called_once_with("valid-token")
        mock_service.assert_called_once_with(verse_id=verse_id, lang=None)


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_by_id_not_found(sample_empty_response):
    """Test retrieval when verse ID doesn't exist."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_by_id_service", return_value=sample_empty_response) as mock_service:
        
        response = client.get(
            f"/cms/verse-of-day/{verse_id}",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["verse_of_day"] is None
        mock_validate.assert_called_once_with("valid-token")
        mock_service.assert_called_once_with(verse_id=verse_id, lang=None)


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_by_id_invalid_uuid():
    """Test retrieval with invalid UUID format."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author):
        response = client.get(
            "/cms/verse-of-day/invalid-uuid",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_by_id_invalid_auth():
    """Test retrieval with invalid authentication token."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", side_effect=HTTPException(status_code=401, detail="Invalid token")) as mock_validate:
        
        response = client.get(
            f"/cms/verse-of-day/{verse_id}",
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "Invalid token"
        mock_validate.assert_called_once_with("invalid-token")


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_by_id_missing_auth():
    """Test retrieval without authentication header."""
    verse_id = uuid4()
    response = client.get(f"/cms/verse-of-day/{verse_id}")
    
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_cms_get_verse_of_day_by_id_database_error():
    """Test handling of database error when fetching by ID."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_by_id_service", side_effect=HTTPException(status_code=500, detail="Database error")) as mock_service:
        
        response = client.get(
            f"/cms/verse-of-day/{verse_id}",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Database error"
        mock_validate.assert_called_once_with("valid-token")


# =============================================================================
# PUT /cms/verse-of-day/{id} TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_cms_update_verse_of_day_success(sample_verse_dto):
    """Test successful update of verse with authentication."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.update_verse_of_day_service", return_value=sample_verse_dto) as mock_update:
        
        request_data = {
            "verses": {"en": "Updated verse text."},
            "image_urls": ["https://example.com/updated-image.jpg"],
            "ref_id": "text-updated",
            "ref_type": "commentary"
        }
        
        response = client.put(
            f"/cms/verse-of-day/{verse_id}",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "id" in data
        assert "verses" in data
        
        mock_validate.assert_called_once_with("valid-token")
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_cms_update_verse_of_day_partial(sample_verse_dto):
    """Test partial update with only some fields."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.update_verse_of_day_service", return_value=sample_verse_dto) as mock_update:
        
        request_data = {
            "ref_id": "text-partial-update"
        }
        
        response = client.put(
            f"/cms/verse-of-day/{verse_id}",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        mock_validate.assert_called_once_with("valid-token")
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_cms_update_verse_of_day_source_exceeds_max_length():
    """Test update rejects source values longer than the 255-character column."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()

    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author):
        response = client.put(
            f"/cms/verse-of-day/{verse_id}",
            json={"source": "a" * 256},
            headers={"Authorization": "Bearer valid-token"}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_cms_update_verse_of_day_not_found():
    """Test update when verse doesn't exist."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.update_verse_of_day_service", side_effect=HTTPException(status_code=404, detail=f"Verse of day with ID {verse_id} not found")) as mock_update:
        
        request_data = {"ref_id": "text-updated"}
        
        response = client.put(
            f"/cms/verse-of-day/{verse_id}",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"]
        mock_validate.assert_called_once_with("valid-token")


@pytest.mark.asyncio
async def test_cms_update_verse_of_day_invalid_uuid():
    """Test update with invalid UUID format."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author):
        request_data = {"ref_id": "text-updated"}
        
        response = client.put(
            "/cms/verse-of-day/invalid-uuid",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_cms_update_verse_of_day_invalid_auth():
    """Test update with invalid authentication token."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", side_effect=HTTPException(status_code=401, detail="Invalid token")) as mock_validate:
        
        request_data = {"ref_id": "text-updated"}
        
        response = client.put(
            f"/cms/verse-of-day/{verse_id}",
            json=request_data,
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "Invalid token"
        mock_validate.assert_called_once_with("invalid-token")


@pytest.mark.asyncio
async def test_cms_update_verse_of_day_missing_auth():
    """Test update without authentication header."""
    verse_id = uuid4()
    request_data = {"ref_id": "text-updated"}
    
    response = client.put(
        f"/cms/verse-of-day/{verse_id}",
        json=request_data
    )
    
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_cms_update_verse_of_day_database_error():
    """Test handling of database error during update."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.update_verse_of_day_service", side_effect=HTTPException(status_code=500, detail="Database error")) as mock_update:
        
        request_data = {"ref_id": "text-updated"}
        
        response = client.put(
            f"/cms/verse-of-day/{verse_id}",
            json=request_data,
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Database error"
        mock_validate.assert_called_once_with("valid-token")


# =============================================================================
# DELETE /cms/verse-of-day/{id} TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_cms_delete_verse_of_day_success():
    """Test successful deletion of verse with authentication."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.delete_verse_of_day_service", return_value=None) as mock_delete:
        
        response = client.delete(
            f"/cms/verse-of-day/{verse_id}",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_204_NO_CONTENT
        
        mock_validate.assert_called_once_with("valid-token")
        mock_delete.assert_called_once_with(verse_id=verse_id)


@pytest.mark.asyncio
async def test_cms_delete_verse_of_day_not_found():
    """Test deletion when verse doesn't exist."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.delete_verse_of_day_service", side_effect=HTTPException(status_code=404, detail=f"Verse of day with ID {verse_id} not found")) as mock_delete:
        
        response = client.delete(
            f"/cms/verse-of-day/{verse_id}",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"]
        mock_validate.assert_called_once_with("valid-token")


@pytest.mark.asyncio
async def test_cms_delete_verse_of_day_invalid_uuid():
    """Test deletion with invalid UUID format."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author):
        response = client.delete(
            "/cms/verse-of-day/invalid-uuid",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_cms_delete_verse_of_day_invalid_auth():
    """Test deletion with invalid authentication token."""
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", side_effect=HTTPException(status_code=401, detail="Invalid token")) as mock_validate:
        
        response = client.delete(
            f"/cms/verse-of-day/{verse_id}",
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == "Invalid token"
        mock_validate.assert_called_once_with("invalid-token")


@pytest.mark.asyncio
async def test_cms_delete_verse_of_day_missing_auth():
    """Test deletion without authentication header."""
    verse_id = uuid4()
    response = client.delete(f"/cms/verse-of-day/{verse_id}")
    
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_cms_delete_verse_of_day_database_error():
    """Test handling of database error during deletion."""
    mock_author = MagicMock()
    mock_author.email = "test@example.com"
    verse_id = uuid4()
    
    with patch("pecha_api.verse_of_day.verse_of_day_views.validate_cms_author_details", return_value=mock_author) as mock_validate, \
         patch("pecha_api.verse_of_day.verse_of_day_views.delete_verse_of_day_service", side_effect=HTTPException(status_code=500, detail="Database error")) as mock_delete:
        
        response = client.delete(
            f"/cms/verse-of-day/{verse_id}",
            headers={"Authorization": "Bearer valid-token"}
        )
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json()["detail"] == "Database error"
        mock_validate.assert_called_once_with("valid-token")
