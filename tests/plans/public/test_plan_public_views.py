import pytest
from uuid import uuid4
from datetime import date as DateType
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.plans.public.plan_response_models import (
    PublicPlansResponse,
    PublicPlanDTO,
    AuthorDTO,
    PlanDayBasic,
    PlanDayDTO,
    TaskDTO,
    SubTaskDTO,
    PlanDaysResponse,
    TagsResponse,
    DailyPlanResponse,
)
from tests.plans.tag_test_helpers import make_tag_summaries
from pecha_api.plans.plans_enums import PlanStatus, DifficultyLevel,ContentType
from pecha_api.error_contants import ErrorConstants
from pecha_api.plans.public.plan_views import get_plan_days_list, get_plan_day_content
from pecha_api.plans.public.plan_service import auto_enroll_plan
from pecha_api.plans.tags.tag_response_models import PublicTagsListResponse


client = TestClient(api)

class _Creds:
    def __init__(self, token: str):
        self.credentials = token

@pytest.fixture
def sample_author_dto():
    """Sample author DTO for testing."""
    return AuthorDTO(
        id=uuid4(),
        firstname="John",
        lastname="Doe",
        image=None
    )


@pytest.fixture
def sample_plan_dto(sample_author_dto):
    """Sample plan DTO for testing - matches actual PublicPlanDTO model structure."""
    return PublicPlanDTO(
        id=uuid4(),
        title="Introduction to Meditation",
        description="A comprehensive guide to meditation practices",
        language="en",
        difficulty_level=DifficultyLevel.BEGINNER,
        image=None,
        total_days=30,
        tags=make_tag_summaries(["meditation", "mindfulness", "beginner"]),
        author=sample_author_dto,
        start_date=None
    )


@pytest.fixture
def sample_plans_response(sample_plan_dto):
    """Sample plans response for testing."""
    return PublicPlansResponse(
        plans=[sample_plan_dto],
        skip=0,
        limit=20,
        total=1
    )

@pytest.mark.asyncio
async def test_get_plans_success(sample_plans_response):
    """Test successful retrieval of published plans with default language='en'."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=sample_plans_response) as mock_service:
        response = client.get("/api/v1/plans")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert "plans" in data
        assert "skip" in data
        assert "limit" in data
        assert "total" in data
        assert len(data["plans"]) == 1
        assert data["skip"] == 0
        assert data["limit"] == 20
        assert data["total"] == 1
        
        plan = data["plans"][0]
        assert "id" in plan
        assert plan["title"] == "Introduction to Meditation"
        assert plan["language"] == "en"
        assert plan["total_days"] == 30
        
        assert "author" in plan
        assert plan["author"] is not None
        assert "id" in plan["author"]
        assert plan["author"]["firstname"] == "John"
        assert plan["author"]["lastname"] == "Doe"
        assert "image" in plan["author"]
        
        mock_service.assert_called_once_with(
            tag=None,
            group_id=None,
            search=None,
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20,
            timezone_name=None,
        )


@pytest.mark.asyncio
async def test_get_plans_with_search_filter(sample_plans_response):
    """Test retrieval of plans with search filter and default language='en'."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=sample_plans_response) as mock_service:
        response = client.get("/api/v1/plans?search=meditation")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["plans"]) == 1
        
        mock_service.assert_called_once_with(
            tag=None,
            group_id=None,
            search="meditation",
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20,
            timezone_name=None,
        )


@pytest.mark.asyncio
async def test_get_plans_with_language_filter(sample_plans_response):
    """Test retrieval of plans with language filter."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=sample_plans_response) as mock_service:
        response = client.get("/api/v1/plans?language=en")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["plans"]) == 1
        
        mock_service.assert_called_once_with(
            tag=None,
            group_id=None,
            search=None,
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20,
            timezone_name=None,
        )


@pytest.mark.asyncio
async def test_get_plans_with_sorting(sample_plans_response):
    """Test retrieval of plans with custom sorting and default language='en'."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=sample_plans_response) as mock_service:
        response = client.get("/api/v1/plans?sort_by=subscription_count&sort_order=desc")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["plans"]) == 1
        
        mock_service.assert_called_once_with(
            tag=None,
            group_id=None,
            search=None,
            language="en",
            sort_by="subscription_count",
            sort_order="desc",
            skip=0,
            limit=20,
            timezone_name=None,
        )


@pytest.mark.asyncio
async def test_get_plans_with_pagination(sample_plans_response):
    """Test retrieval of plans with pagination parameters and default language='en'."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=sample_plans_response) as mock_service:
        response = client.get("/api/v1/plans?skip=10&limit=5")
        
        assert response.status_code == status.HTTP_200_OK
        
        mock_service.assert_called_once_with(
            tag=None,
            group_id=None,
            search=None,
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=10,
            limit=5,
            timezone_name=None,
        )


@pytest.mark.asyncio
async def test_get_plans_with_all_filters(sample_plans_response):
    """Test retrieval of plans with all filter parameters."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=sample_plans_response) as mock_service:
        response = client.get(
            "/api/v1/plans?search=meditation&language=en&sort_by=total_days&sort_order=desc&skip=5&limit=10"
        )
        
        assert response.status_code == status.HTTP_200_OK
        
        mock_service.assert_called_once_with(
            tag=None,
            group_id=None,
            search="meditation",
            language="en",
            sort_by="total_days",
            sort_order="desc",
            skip=5,
            limit=10,
            timezone_name=None,
        )


@pytest.mark.asyncio
async def test_get_plans_empty_result():
    """Test retrieval when no plans are found."""
    empty_response = PublicPlansResponse(plans=[], skip=0, limit=20, total=0)
    
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=empty_response):
        response = client.get("/api/v1/plans")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["plans"]) == 0
        assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_plans_invalid_sort_by(sample_plans_response):
    """Test retrieval with invalid sort_by parameter - endpoint accepts and uses default."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=sample_plans_response):
        response = client.get("/api/v1/plans?sort_by=invalid_field")
        
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_get_plans_invalid_sort_order(sample_plans_response):
    """Test retrieval with invalid sort_order parameter - endpoint accepts and uses default."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, return_value=sample_plans_response):
        response = client.get("/api/v1/plans?sort_order=invalid_order")
        
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_get_plans_negative_skip():
    """Test retrieval with negative skip parameter."""
    response = client.get("/api/v1/plans?skip=-1")
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_plans_invalid_limit():
    """Test retrieval with invalid limit parameter (exceeds max)."""
    response = client.get("/api/v1/plans?limit=100")
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_plans_service_error():
    """Test handling of service layer errors."""
    with patch("pecha_api.plans.public.plan_views.get_published_plans_cached", new_callable=AsyncMock, side_effect=HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Database connection error"
    )):
        response = client.get("/api/v1/plans")
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Database connection error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_plan_details_success(sample_plan_dto):
    """Test successful retrieval of plan details."""
    plan_id = sample_plan_dto.id
    
    with patch("pecha_api.plans.public.plan_views.get_published_plan_cached", new_callable=AsyncMock, return_value=sample_plan_dto) as mock_service:
        response = client.get(f"/api/v1/plans/{plan_id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["id"] == str(plan_id)
        assert data["title"] == "Introduction to Meditation"
        assert data["description"] == "A comprehensive guide to meditation practices"
        assert data["language"] == "en"
        assert data["difficulty_level"] == "BEGINNER"
        assert data["total_days"] == 30
        assert len(data["tags"]) == 3
        assert [t["name"] for t in data["tags"]] == ["meditation", "mindfulness", "beginner"]
        
        assert "author" in data
        assert data["author"]["firstname"] == "John"
        assert data["author"]["lastname"] == "Doe"
        
        assert "image" in data
        assert "image" in data["author"]
        
        mock_service.assert_called_once_with(plan_id=plan_id, timezone_name=None)


@pytest.mark.asyncio
async def test_get_plan_details_not_found():
    """Test retrieval of non-existent plan."""
    plan_id = uuid4()
    
    with patch("pecha_api.plans.public.plan_views.get_published_plan_cached", new_callable=AsyncMock, side_effect=HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=ErrorConstants.PLAN_NOT_FOUND
    )):
        response = client.get(f"/api/v1/plans/{plan_id}")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert ErrorConstants.PLAN_NOT_FOUND in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_plan_daily_success():
    plan_id = uuid4()
    daily_response = DailyPlanResponse(
        plan_id=plan_id,
        plan_title="Daily Plan",
        plan_description="Desc",
        date=DateType(2026, 5, 1),
        day_number=1,
        total_days=3,
        start_date=DateType(2026, 5, 1),
        end_date=DateType(2026, 5, 3),
        tasks=[],
    )

    with patch(
        "pecha_api.plans.public.plan_views.get_plan_daily_content_cached",
        new_callable=AsyncMock,
        return_value=daily_response,
    ) as mock_service:
        response = client.get(
            f"/api/v1/plans/{plan_id}/daily",
            params={"date": "2026-05-01", "language": "en"},
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["plan_id"] == str(plan_id)
    assert data["day_number"] == 1
    mock_service.assert_called_once_with(
        plan_id=plan_id,
        requested_date=DateType(2026, 5, 1),
        language="en",
    )


@pytest.mark.asyncio
async def test_get_plan_daily_not_found():
    plan_id = uuid4()

    with patch(
        "pecha_api.plans.public.plan_views.get_plan_daily_content_cached",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorConstants.PLAN_NOT_FOUND,
        ),
    ):
        response = client.get(f"/api/v1/plans/{plan_id}/daily")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_plan_details_invalid_uuid():
    """Test retrieval with invalid UUID format."""
    response = client.get("/api/v1/plans/invalid-uuid")
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_plan_details_without_author(sample_plan_dto):
    """Test retrieval of plan without author information."""
    plan_dto_no_author = PublicPlanDTO(
        id=uuid4(),
        title="Test Plan",
        description="Test Description",
        language="en",
        difficulty_level=DifficultyLevel.BEGINNER,
        image=None,
        total_days=10,
        tags=[],
        author=None
    )
    
    with patch("pecha_api.plans.public.plan_views.get_published_plan_cached", new_callable=AsyncMock, return_value=plan_dto_no_author):
        response = client.get(f"/api/v1/plans/{plan_dto_no_author.id}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["author"] is None


@pytest.mark.asyncio
async def test_get_plan_details_service_error():
    """Test handling of service layer errors."""
    plan_id = uuid4()
    
    with patch("pecha_api.plans.public.plan_views.get_published_plan_cached", new_callable=AsyncMock, side_effect=HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to fetch published plan details"
    )):
        response = client.get(f"/api/v1/plans/{plan_id}")
        
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to fetch published plan details" in response.json()["detail"]

@pytest.mark.asyncio
async def test_get_plan_days_list_success():
    """Test successful retrieval of plan days list without authentication"""
    plan_id = uuid4()
    
    expected_days = [
        PlanDayBasic(id=str(uuid4()), day_number=1),
        PlanDayBasic(id=str(uuid4()), day_number=2),
    ]
    expected_response = PlanDaysResponse(days=expected_days)

    with patch(
        "pecha_api.plans.public.plan_views.get_plan_days_cached",
        new_callable=AsyncMock,
        return_value=expected_response,
    ) as mock_service, \
    patch(
        "pecha_api.plans.public.plan_views.auto_enroll_plan"
    ) as mock_auto_enroll:
        response = await get_plan_days_list(
            plan_id=plan_id,
            credentials=None
        )

        mock_auto_enroll.assert_called_once_with(plan_id=plan_id, user_id=None)
        mock_service.assert_called_once_with(plan_id=plan_id)

        assert response == expected_response
        assert len(response.days) == 2
        assert response.days[0].day_number == 1
        assert response.days[1].day_number == 2


@pytest.mark.asyncio
async def test_get_plan_days_list_with_authenticated_user():
    """Test retrieval of plan days list with authenticated user triggers auto-enrollment"""
    plan_id = uuid4()
    user_id = uuid4()
    
    expected_days = [
        PlanDayBasic(id=str(uuid4()), day_number=1),
    ]
    expected_response = PlanDaysResponse(days=expected_days)
    
    mock_user = MagicMock()
    mock_user.id = user_id

    with patch(
        "pecha_api.plans.public.plan_views.get_plan_days_cached",
        new_callable=AsyncMock,
        return_value=expected_response,
    ) as mock_service, \
    patch(
        "pecha_api.plans.public.plan_views.auto_enroll_plan"
    ) as mock_auto_enroll, \
    patch(
        "pecha_api.plans.public.plan_views.validate_and_extract_user_details",
        return_value=mock_user
    ) as mock_validate:
        credentials = _Creds("valid_token")
        response = await get_plan_days_list(
            plan_id=plan_id,
            credentials=credentials
        )

        mock_validate.assert_called_once_with(token="valid_token")
        mock_auto_enroll.assert_called_once_with(plan_id=plan_id, user_id=user_id)
        mock_service.assert_called_once_with(plan_id=plan_id)

        assert response == expected_response


@pytest.mark.asyncio
async def test_get_plan_days_list_with_invalid_token():
    """Test retrieval of plan days list with invalid token still works but without auto-enrollment"""
    plan_id = uuid4()
    
    expected_days = [
        PlanDayBasic(id=str(uuid4()), day_number=1),
    ]
    expected_response = PlanDaysResponse(days=expected_days)

    with patch(
        "pecha_api.plans.public.plan_views.get_plan_days_cached",
        new_callable=AsyncMock,
        return_value=expected_response,
    ) as mock_service, \
    patch(
        "pecha_api.plans.public.plan_views.auto_enroll_plan"
    ) as mock_auto_enroll, \
    patch(
        "pecha_api.plans.public.plan_views.validate_and_extract_user_details",
        side_effect=Exception("Invalid token")
    ):
        credentials = _Creds("invalid_token")
        response = await get_plan_days_list(
            plan_id=plan_id,
            credentials=credentials
        )

        # auto_enroll should be called with user_id=None since token validation failed
        mock_auto_enroll.assert_called_once_with(plan_id=plan_id, user_id=None)
        mock_service.assert_called_once_with(plan_id=plan_id)

        assert response == expected_response


@pytest.mark.asyncio
async def test_get_plan_days_list_empty_days():
    """Test retrieval when plan has no days"""
    plan_id = uuid4()
    
    expected_response = PlanDaysResponse(days=[])

    with patch(
        "pecha_api.plans.public.plan_views.get_plan_days_cached",
        new_callable=AsyncMock,
        return_value=expected_response,
    ) as mock_service, \
    patch(
        "pecha_api.plans.public.plan_views.auto_enroll_plan"
    ) as mock_auto_enroll:
        response = await get_plan_days_list(
            plan_id=plan_id,
            credentials=None
        )

        mock_auto_enroll.assert_called_once_with(plan_id=plan_id, user_id=None)
        mock_service.assert_called_once_with(plan_id=plan_id)

        assert response == expected_response
        assert len(response.days) == 0

@pytest.mark.asyncio
async def test_get_plan_day_content_success():
    """Test successful retrieval of plan day content"""
    plan_id = uuid4()
    day_number = 1
    
    expected_subtask = SubTaskDTO(
        id= uuid4(),
        content_type=ContentType.TEXT,
        content="Test subtask content",
        display_order=1
    )
    
    expected_task = TaskDTO(
        id=uuid4(),
        title="Test Task",
        estimated_time=30,
        display_order=1,
        subtasks=[expected_subtask]
    )
    
    expected_response = PlanDayDTO(
        id=uuid4(),
        day_number=day_number,
        tasks=[expected_task]
    )

    with patch(
        "pecha_api.plans.public.plan_views.get_plan_day_details",
        return_value=expected_response,
    ) as mock_service:
        response = await get_plan_day_content(
            plan_id=plan_id,
            day_number=day_number
        )

        mock_service.assert_called_once_with(
            plan_id=plan_id,
            day_number=day_number
        )

        assert response == expected_response
        assert response.id == expected_response.id
        assert response.day_number == day_number
        assert len(response.tasks) == 1
        
        task = response.tasks[0]
        assert task.id == expected_task.id
        assert task.title == "Test Task"
        assert task.estimated_time == 30
        assert task.display_order == 1
        assert len(task.subtasks) == 1
        
        subtask = task.subtasks[0]
        assert subtask.id == expected_subtask.id
        assert subtask.content_type == ContentType.TEXT
        assert subtask.content == "Test subtask content"
        assert subtask.display_order == 1


@pytest.mark.asyncio
async def test_get_plan_day_content_no_tasks():
    """Test retrieval of plan day with no tasks"""
    plan_id = uuid4()
    day_number = 2
    
    expected_response = PlanDayDTO(
        id= uuid4(),
        day_number=day_number,
        tasks=[]
    )

    with patch(
        "pecha_api.plans.public.plan_views.get_plan_day_details",
        return_value=expected_response,
    ) as mock_service:
        response = await get_plan_day_content(
            plan_id=plan_id,
            day_number=day_number
        )

        mock_service.assert_called_once_with(
            plan_id=plan_id,
            day_number=day_number
        )

        assert response == expected_response
        assert response.id == expected_response.id
        assert response.day_number == day_number
        assert len(response.tasks) == 0

@pytest.mark.asyncio
async def test_get_plan_tags_success():
    """Test successful retrieval of plan tags with default language='en'."""
    mock_tags_response = TagsResponse(tags=make_tag_summaries(["meditation", "sleep", "daily"]))

    with patch(
        "pecha_api.plans.public.plan_views.get_tags_cached", new_callable=AsyncMock, return_value=mock_tags_response
    ) as mock_service:
        response = client.get("/api/v1/plans/tags")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "tags" in data
        assert isinstance(data["tags"], list)
        assert [t["name"] for t in data["tags"]] == ["meditation", "sleep", "daily"]

        mock_service.assert_called_once_with(language="en")


@pytest.mark.asyncio
async def test_get_plan_tags_with_language_param():
    """Test retrieval of plan tags with specific language."""
    mock_tags_response = TagsResponse(tags=make_tag_summaries(["煙供", "教學"]))

    with patch(
        "pecha_api.plans.public.plan_views.get_tags_cached", new_callable=AsyncMock, return_value=mock_tags_response
    ) as mock_service:
        response = client.get("/api/v1/plans/tags?language=zh")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert [t["name"] for t in data["tags"]] == ["煙供", "教學"]

        mock_service.assert_called_once_with(language="zh")


@pytest.mark.asyncio
async def test_get_public_tags_success():
    response_model = PublicTagsListResponse(
        tags=make_tag_summaries(["meditation", "sleep"]),
        skip=0,
        limit=20,
        total=2,
    )

    with patch(
        "pecha_api.plans.public.public_tags_views.get_public_tags_cached",
        new_callable=AsyncMock,
        return_value=response_model,
    ) as mock_service:
        response = client.get("/api/v1/public/tags")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 2
        assert response.json()["skip"] == 0
        assert response.json()["limit"] == 20
        assert [t["name"] for t in response.json()["tags"]] == ["meditation", "sleep"]
        mock_service.assert_called_once_with(
            featured=None,
            search=None,
            language='EN',
            skip=0,
            limit=20,
        )


@pytest.mark.asyncio
async def test_get_public_tags_with_filters():
    response_model = PublicTagsListResponse(
        tags=make_tag_summaries(["meditation"]),
        skip=5,
        limit=10,
        total=1,
    )

    with patch(
        "pecha_api.plans.public.public_tags_views.get_public_tags_cached",
        new_callable=AsyncMock,
        return_value=response_model,
    ) as mock_service:
        response = client.get(
            "/api/v1/public/tags",
            params={
                "featured": "true",
                "search": "med",
                "skip": 5,
                "limit": 10,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(
            featured=True,
            search="med",
            language='EN',
            skip=5,
            limit=10,
        )

@pytest.mark.asyncio
async def test_get_plans_with_tag_filter(sample_plans_response):
    """Test retrieval of plans with tag filter."""
    with patch(
        "pecha_api.plans.public.plan_views.get_published_plans_cached",
        new_callable=AsyncMock,
        return_value=sample_plans_response,
    ) as mock_service:
        response = client.get("/api/v1/plans?tag=meditation")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["plans"]) == 1

        mock_service.assert_called_once_with(
            tag="meditation",
            group_id=None,
            search=None,
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20,
            timezone_name=None,
        )


@pytest.mark.asyncio
async def test_get_plans_with_group_filter(sample_plans_response):
    group_id = uuid4()
    with patch(
        "pecha_api.plans.public.plan_views.get_published_plans_cached",
        new_callable=AsyncMock,
        return_value=sample_plans_response,
    ) as mock_service:
        response = client.get(f"/api/v1/plans?group_id={group_id}")

        assert response.status_code == status.HTTP_200_OK

        mock_service.assert_called_once_with(
            tag=None,
            group_id=group_id,
            search=None,
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20,
            timezone_name=None,
        )


def test_cleanup_plan_day_cache_success():
    plan_id = uuid4()
    day_number = 1
    from pecha_api.config import get as real_config_get

    def _config_get(key: str) -> str:
        if key == "DEPLOYMENT_MODE":
            return "DEBUG"
        return real_config_get(key)

    with patch("pecha_api.plans.public.plan_views.config.get", side_effect=_config_get), patch(
        "pecha_api.plans.public.plan_views.invalidate_plan_day_detail_cache",
        new_callable=AsyncMock,
        return_value=2,
    ) as mock_invalidate:
        response = client.delete(f"/api/v1/plans/{plan_id}/days/{day_number}/cache")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "plan_id": str(plan_id),
        "day_number": day_number,
        "keys_deleted": 2,
    }
    mock_invalidate.assert_awaited_once_with(plan_id=plan_id, day_number=day_number)


def test_cleanup_plan_days_cache_success():
    plan_id = uuid4()
    from pecha_api.config import get as real_config_get

    def _config_get(key: str) -> str:
        if key == "DEPLOYMENT_MODE":
            return "DEBUG"
        return real_config_get(key)

    with patch("pecha_api.plans.public.plan_views.config.get", side_effect=_config_get), patch(
        "pecha_api.plans.public.plan_views.SessionLocal"
    ) as mock_session_local, patch(
        "pecha_api.plans.public.plan_views.invalidate_all_plan_day_detail_caches_for_plan",
        new_callable=AsyncMock,
        return_value=6,
    ) as mock_invalidate:
        mock_session_local.return_value.__enter__.return_value = MagicMock()
        response = client.delete(f"/api/v1/plans/{plan_id}/cache/plan-days")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "plan_id": str(plan_id),
        "day_number": None,
        "keys_deleted": 6,
    }
    mock_invalidate.assert_awaited_once()


def test_cleanup_plan_day_cache_forbidden_outside_debug():
    plan_id = uuid4()
    from pecha_api.config import get as real_config_get

    def _config_get(key: str) -> str:
        if key == "DEPLOYMENT_MODE":
            return "PRODUCTION"
        return real_config_get(key)

    with patch("pecha_api.plans.public.plan_views.config.get", side_effect=_config_get):
        response = client.delete(f"/api/v1/plans/{plan_id}/days/1/cache")

    assert response.status_code == status.HTTP_403_FORBIDDEN