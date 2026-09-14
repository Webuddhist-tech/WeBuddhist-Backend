import pytest
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, Mock, AsyncMock, call
from datetime import date as DateType, datetime, timedelta, timezone
from fastapi import HTTPException
from starlette import status

from pecha_api.plans.public.plan_service import (
    get_published_plans,
    get_published_plan,
    get_plan_days,
    get_plan_day_details,
    get_plan_daily_content,
    get_tags,
    get_public_tags,
    auto_enroll_plan,
    is_user_enrolled_in_previous_plan,
    is_within_plan_date_range,
    _to_plan_date,
    _resolve_plan_for_date_in_series,
    _resolve_daily_plan,
    _filter_series_metadata_by_language,
)
from pecha_api.plans.public.plan_response_models import (
    PublicPlansResponse,
    PublicPlanDTO,
    PlanDaysResponse,
    PlanDayDTO,
    TagsResponse,
    DailyPlanResponse,
)
from pecha_api.plans.tags.tag_response_models import PublicTagsListResponse
from pecha_api.plans.plans_enums import PlanStatus, DifficultyLevel, LanguageCode
from pecha_api.error_contants import ErrorConstants
from pecha_api.plans.plans_enums import ContentType

FIXTURE_GROUP_ID = uuid4()
FIXTURE_SERIES_ID = uuid4()

@pytest.fixture
def sample_author():
    author = MagicMock()
    author.id = uuid4()
    author.first_name = "John"
    author.last_name = "Doe"
    author.email = "john.doe@example.com"
    author.image_url = "images/author_avatars/author-id/avatar.jpg"
    author.is_verified = True
    return author

def _mock_session_local(mock_session_local):
    """Helper function to mock SessionLocal context manager"""
    mock_db_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db_session
    mock_session_local.return_value.__exit__.return_value = False
    return mock_db_session

@pytest.fixture
def sample_plan(sample_author):
    plan = MagicMock()
    plan.id = uuid4()
    plan.title = "Introduction to Meditation"
    plan.description = "A comprehensive guide to meditation practices"
    plan.language = LanguageCode.EN
    plan.difficulty_level = DifficultyLevel.BEGINNER
    plan.image_url = "images/plan_images/plan-id/uuid/image.jpg"
    plan.status = PlanStatus.PUBLISHED
    plan.tag_list = []
    plan.author = sample_author
    plan.deleted_at = None
    plan.start_date = None
    plan.group_id = FIXTURE_GROUP_ID
    plan.series_id = FIXTURE_SERIES_ID
    return plan


@pytest.fixture
def sample_plan_aggregate(sample_plan):
    aggregate = MagicMock()
    aggregate.plan = sample_plan
    aggregate.total_days = 30
    aggregate.subscription_count = 150
    return aggregate


@pytest.fixture
def mock_db_session():
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_get_published_plans_success(sample_plan_aggregate, mock_db_session):
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=[sample_plan_aggregate]) as mock_repo, \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=1), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url") as mock_presigned_url:
        
        result = await get_published_plans(
            search=None,
            language="en",  # Use default language
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20
        )
        
        assert isinstance(result, PublicPlansResponse)
        assert len(result.plans) == 1
        assert result.skip == 0
        assert result.limit == 20
        assert result.total == 1
        
        plan_dto = result.plans[0]
        assert plan_dto.title == "Introduction to Meditation"
        assert plan_dto.language == "EN"
        assert plan_dto.total_days == 30
        assert plan_dto.image is not None
        assert plan_dto.image.thumbnail == "https://bucket.s3.amazonaws.com/presigned-url"
        assert plan_dto.image.medium == "https://bucket.s3.amazonaws.com/presigned-url"
        assert plan_dto.image.original == "https://bucket.s3.amazonaws.com/presigned-url"
        
        assert plan_dto.author is not None
        assert plan_dto.author.id == sample_plan_aggregate.plan.author.id
        assert plan_dto.author.firstname == "John"
        assert plan_dto.author.lastname == "Doe"
        assert plan_dto.author.image is not None
        assert plan_dto.author.image.thumbnail == "https://bucket.s3.amazonaws.com/presigned-url"
        
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            skip=0,
            limit=20,
            search=None,
            language="EN",  
            sort_by="title",
            sort_order="asc",
            tag=None,
            group_id=None,
        )


@pytest.mark.asyncio
async def test_get_published_plans_with_search(sample_plan_aggregate, mock_db_session):
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=[sample_plan_aggregate]) as mock_repo, \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=1), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plans(
            search="meditation",
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20
        )
        
        assert len(result.plans) == 1
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            skip=0,
            limit=20,
            search="meditation",
            language="EN", 
            sort_by="title",
            sort_order="asc",
            tag=None,
            group_id=None,
        )


@pytest.mark.asyncio
async def test_get_published_plans_with_language_filter(sample_plan_aggregate, mock_db_session):
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=[sample_plan_aggregate]) as mock_repo, \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=1), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plans(
            search=None,
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20
        )
        
        assert len(result.plans) == 1
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            skip=0,
            limit=20,
            search=None,
            language="EN", 
            sort_by="title",
            sort_order="asc",
            tag=None,
            group_id=None,
        )


@pytest.mark.asyncio
async def test_get_published_plans_sort_by_title_asc(sample_plan_aggregate, mock_db_session):
    plan1 = MagicMock()
    plan1.id = uuid4()
    plan1.title = "Advanced Meditation"
    plan1.description = "Advanced techniques"
    plan1.language = LanguageCode.EN
    plan1.difficulty_level = DifficultyLevel.BEGINNER
    plan1.image_url = None
    plan1.status = PlanStatus.PUBLISHED
    plan1.tag_list = []
    plan1.author = None
    plan1.series_id = None
    
    plan2 = MagicMock()
    plan2.id = uuid4()
    plan2.title = "Beginner Meditation"
    plan2.description = "Basic techniques"
    plan2.language = LanguageCode.EN
    plan2.difficulty_level = DifficultyLevel.BEGINNER
    plan2.image_url = None
    plan2.status = PlanStatus.PUBLISHED
    plan2.tag_list = []
    plan2.author = None
    plan2.series_id = None
    
    agg1 = MagicMock()
    agg1.plan = plan1
    agg1.total_days = 20
    agg1.subscription_count = 100
    
    agg2 = MagicMock()
    agg2.plan = plan2
    agg2.total_days = 10
    agg2.subscription_count = 50
    
    aggregates = [agg1, agg2]
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=aggregates), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=2), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value=None):
        
        result = await get_published_plans(sort_by="title", sort_order="asc")
        
        assert result.plans[0].title == "Advanced Meditation"
        assert result.plans[1].title == "Beginner Meditation"


@pytest.mark.asyncio
async def test_get_published_plans_sort_by_title_desc(sample_plan_aggregate, mock_db_session):
    plan1 = MagicMock()
    plan1.id = uuid4()
    plan1.title = "Advanced Meditation"
    plan1.description = "Advanced techniques"
    plan1.language = LanguageCode.EN
    plan1.difficulty_level = DifficultyLevel.BEGINNER
    plan1.image_url = None
    plan1.status = PlanStatus.PUBLISHED
    plan1.tag_list = []
    plan1.author = None
    plan1.series_id = None
    
    plan2 = MagicMock()
    plan2.id = uuid4()
    plan2.title = "Beginner Meditation"
    plan2.description = "Basic techniques"
    plan2.language = LanguageCode.EN
    plan2.difficulty_level = DifficultyLevel.BEGINNER
    plan2.image_url = None
    plan2.status = PlanStatus.PUBLISHED
    plan2.tag_list = []
    plan2.author = None
    plan2.series_id = None
    
    agg1 = MagicMock()
    agg1.plan = plan1
    agg1.total_days = 20
    agg1.subscription_count = 100
    
    agg2 = MagicMock()
    agg2.plan = plan2
    agg2.total_days = 10
    agg2.subscription_count = 50
    
    aggregates = [agg1, agg2]
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=aggregates), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=2), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value=None):
        
        result = await get_published_plans(sort_by="title", sort_order="desc")
        
        assert len(result.plans) == 2
        assert result.plans[0].title == "Advanced Meditation"
        assert result.plans[1].title == "Beginner Meditation"


@pytest.mark.asyncio
async def test_get_published_plans_sort_by_total_days(sample_plan_aggregate, mock_db_session):
    plan1 = MagicMock()
    plan1.id = uuid4()
    plan1.title = "Short Plan"
    plan1.description = "Short plan"
    plan1.language = LanguageCode.EN
    plan1.difficulty_level = DifficultyLevel.BEGINNER
    plan1.image_url = None
    plan1.status = PlanStatus.PUBLISHED
    plan1.tag_list = []
    plan1.author = None
    plan1.series_id = None
    
    plan2 = MagicMock()
    plan2.id = uuid4()
    plan2.title = "Long Plan"
    plan2.description = "Long plan"
    plan2.language = LanguageCode.EN
    plan2.difficulty_level = DifficultyLevel.BEGINNER
    plan2.image_url = None
    plan2.status = PlanStatus.PUBLISHED
    plan2.tag_list = []
    plan2.author = None
    plan2.series_id = None
    
    agg1 = MagicMock()
    agg1.plan = plan1
    agg1.total_days = 10
    agg1.subscription_count = 100
    
    agg2 = MagicMock()
    agg2.plan = plan2
    agg2.total_days = 30
    agg2.subscription_count = 50
    
    aggregates = [agg1, agg2]
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=aggregates), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=2), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value=None):
        
        result = await get_published_plans(sort_by="total_days", sort_order="asc")
        
        assert result.plans[0].total_days == 10
        assert result.plans[1].total_days == 30


@pytest.mark.asyncio
async def test_get_published_plans_sort_by_subscription_count(sample_plan_aggregate, mock_db_session):
    plan1 = MagicMock()
    plan1.id = uuid4()
    plan1.title = "Popular Plan"
    plan1.description = "Popular plan"
    plan1.language = LanguageCode.EN
    plan1.difficulty_level = DifficultyLevel.BEGINNER
    plan1.image_url = None
    plan1.status = PlanStatus.PUBLISHED
    plan1.tag_list = []
    plan1.author = None
    plan1.series_id = None
    
    plan2 = MagicMock()
    plan2.id = uuid4()
    plan2.title = "Less Popular Plan"
    plan2.description = "Less popular plan"
    plan2.language = LanguageCode.EN
    plan2.difficulty_level = DifficultyLevel.BEGINNER
    plan2.image_url = None
    plan2.status = PlanStatus.PUBLISHED
    plan2.tag_list = []
    plan2.author = None
    plan2.series_id = None
    
    agg1 = MagicMock()
    agg1.plan = plan1
    agg1.total_days = 10
    agg1.subscription_count = 200
    
    agg2 = MagicMock()
    agg2.plan = plan2
    agg2.total_days = 10
    agg2.subscription_count = 50
    
    aggregates = [agg1, agg2]
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=aggregates), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=2), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value=None):
        
        result = await get_published_plans(sort_by="subscription_count", sort_order="desc")
        
        assert len(result.plans) == 2
        assert result.plans[0].title == "Popular Plan"
        assert result.plans[1].title == "Less Popular Plan"


@pytest.mark.asyncio
async def test_get_published_plans_empty_result(mock_db_session):
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=[]), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=0):
        
        result = await get_published_plans()
        
        assert isinstance(result, PublicPlansResponse)
        assert len(result.plans) == 0
        assert result.total == 0


@pytest.mark.asyncio
async def test_get_published_plans_without_author(mock_db_session):
    plan_no_author = MagicMock()
    plan_no_author.id = uuid4()
    plan_no_author.title = "Orphan Plan"
    plan_no_author.description = "Plan without author"
    plan_no_author.language = LanguageCode.EN
    plan_no_author.difficulty_level = DifficultyLevel.BEGINNER
    plan_no_author.image_url = None
    plan_no_author.status = PlanStatus.PUBLISHED
    plan_no_author.tag_list = []
    plan_no_author.author = None
    plan_no_author.series_id = None

    aggregate = MagicMock()
    aggregate.plan = plan_no_author
    aggregate.total_days = 10
    aggregate.subscription_count = 0
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=[aggregate]), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=1), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plans()
        
        assert len(result.plans) == 1
        assert result.plans[0].author is None


@pytest.mark.asyncio
async def test_get_published_plans_with_pagination(sample_plan_aggregate, mock_db_session):
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=[sample_plan_aggregate]) as mock_repo, \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=1), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plans(skip=10, limit=5)
        
        assert result.skip == 10
        assert result.limit == 5
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            skip=10,
            limit=5,
            search=None,
            language="EN",  # Service converts to uppercase before calling repository
            sort_by="title",
            sort_order="asc",
            tag=None,
            group_id=None,
        )


@pytest.mark.asyncio
async def test_get_published_plans_image_url_generation_failure(sample_plan_aggregate, mock_db_session):
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", return_value=[sample_plan_aggregate]), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_count", return_value=1), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plans()
        
        assert len(result.plans) == 1
        assert result.plans[0].image is not None


@pytest.mark.asyncio
async def test_get_published_plans_database_error(mock_db_session):
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_from_db", side_effect=Exception("Database connection error")):
        
        with pytest.raises(HTTPException) as exc_info:
            await get_published_plans()
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to fetch published plans" in str(exc_info.value.detail)

@pytest.mark.asyncio
async def test_get_published_plan_success(sample_plan, sample_author, mock_db_session):
    plan_id = sample_plan.id
    
    mock_query = MagicMock()
    mock_db_session.__enter__.return_value.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = 30 
    mock_query.filter.return_value.distinct.return_value.count.return_value = 150 
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=sample_plan) as mock_repo, \
         patch("pecha_api.plans.public.plan_service.get_group_id_for_plan", return_value=FIXTURE_GROUP_ID), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url") as mock_presigned_url:
        
        result = await get_published_plan(plan_id=plan_id)
        
        assert isinstance(result, PublicPlanDTO)
        assert result.id == plan_id
        assert result.title == "Introduction to Meditation"
        assert result.language == "EN" 
        assert result.total_days == 30
        assert result.image is not None
        assert result.image.thumbnail == "https://bucket.s3.amazonaws.com/presigned-url"
        assert result.image.medium == "https://bucket.s3.amazonaws.com/presigned-url"
        assert result.image.original == "https://bucket.s3.amazonaws.com/presigned-url"
        
        assert result.author is not None
        assert result.author.firstname == "John"
        assert result.author.lastname == "Doe"
        assert result.author.image is not None
        assert result.author.image.thumbnail == "https://bucket.s3.amazonaws.com/presigned-url"
        assert result.series_id == FIXTURE_SERIES_ID

        mock_repo.assert_called_once_with(db=mock_db_session.__enter__.return_value, plan_id=plan_id)


@pytest.mark.asyncio
async def test_get_published_plan_not_found(mock_db_session):
    plan_id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=None):
        
        with pytest.raises(HTTPException) as exc_info:
            await get_published_plan(plan_id=plan_id)
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to fetch published plan details" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_published_plan_without_author(mock_db_session):
    plan_no_author = MagicMock()
    plan_no_author.id = uuid4()
    plan_no_author.title = "Orphan Plan"
    plan_no_author.description = "Plan without author"
    plan_no_author.language = LanguageCode.EN
    plan_no_author.difficulty_level = DifficultyLevel.BEGINNER
    plan_no_author.image_url = None
    plan_no_author.status = PlanStatus.PUBLISHED
    plan_no_author.tag_list = []
    plan_no_author.author = None
    plan_no_author.deleted_at = None
    plan_no_author.group_id = FIXTURE_GROUP_ID
    plan_no_author.series_id = None

    mock_query = MagicMock()
    mock_db_session.__enter__.return_value.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = 10
    mock_query.filter.return_value.distinct.return_value.count.return_value = 5
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=plan_no_author), \
         patch("pecha_api.plans.public.plan_service.get_group_id_for_plan", return_value=FIXTURE_GROUP_ID), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plan(plan_id=plan_no_author.id)
        
        assert result.author is None
        assert result.title == "Orphan Plan"


@pytest.mark.asyncio
async def test_get_published_plan_image_url_generation_failure(sample_plan, mock_db_session):
    plan_id = sample_plan.id
    
    mock_query = MagicMock()
    mock_db_session.__enter__.return_value.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = 30
    mock_query.filter.return_value.distinct.return_value.count.return_value = 150
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=sample_plan), \
         patch("pecha_api.plans.public.plan_service.get_group_id_for_plan", return_value=FIXTURE_GROUP_ID), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plan(plan_id=plan_id)
        
        assert result.image is not None


@pytest.mark.asyncio
async def test_get_published_plan_database_error(mock_db_session):
    plan_id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", side_effect=Exception("Database connection error")):
        
        with pytest.raises(HTTPException) as exc_info:
            await get_published_plan(plan_id=plan_id)
        
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to fetch published plan details" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_published_plan_with_empty_tags(sample_plan, mock_db_session):
    sample_plan.tag_list = None
    
    mock_query = MagicMock()
    mock_db_session.__enter__.return_value.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = 10
    mock_query.filter.return_value.distinct.return_value.count.return_value = 5
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=sample_plan), \
         patch("pecha_api.plans.public.plan_service.get_group_id_for_plan", return_value=FIXTURE_GROUP_ID), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plan(plan_id=sample_plan.id)
        
        assert result.tags == []


@pytest.mark.asyncio
async def test_get_published_plan_zero_subscriptions(sample_plan, mock_db_session):
    mock_query = MagicMock()
    mock_db_session.__enter__.return_value.query.return_value = mock_db_session
    mock_query.filter.return_value.count.return_value = 15
    mock_query.filter.return_value.distinct.return_value.count.return_value = 0
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=sample_plan), \
         patch("pecha_api.plans.public.plan_service.get_group_id_for_plan", return_value=FIXTURE_GROUP_ID), \
         patch("pecha_api.plans.public.plan_service.generate_presigned_access_url", return_value="https://bucket.s3.amazonaws.com/presigned-url"):
        
        result = await get_published_plan(plan_id=sample_plan.id)
        
        assert result.title == sample_plan.title
        assert result.id == sample_plan.id

@pytest.mark.asyncio
async def test_get_plan_days_success():
    """Test successful retrieval of plan days"""
    plan_id = uuid4()
    
    mock_plan = MagicMock()
    mock_plan.id = plan_id
    mock_plan.title = "Test Plan"
    
    mock_day_1 = MagicMock()
    mock_day_1.id = uuid4()
    mock_day_1.day_number = 1
    
    mock_day_2 = MagicMock()
    mock_day_2.id = uuid4()
    mock_day_2.day_number = 2
    
    mock_plan_days = [mock_day_1, mock_day_2]

    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.public.plan_service.get_days_by_plan_id") as mock_get_days:
        
        db_session = _mock_session_local(mock_session_local)
        mock_get_plan.return_value = mock_plan
        mock_get_days.return_value = mock_plan_days

        response = await get_plan_days(plan_id=plan_id)

        mock_get_plan.assert_called_once_with(db=db_session, plan_id=plan_id)
        mock_get_days.assert_called_once_with(db=db_session, plan_id=plan_id)

        assert isinstance(response, PlanDaysResponse)
        assert len(response.days) == 2
        
        assert response.days[0].id == str(mock_day_1.id)
        assert response.days[0].day_number == 1
        assert response.days[1].id == str(mock_day_2.id)
        assert response.days[1].day_number == 2


@pytest.mark.asyncio
async def test_get_plan_days_empty_days():
    """Test retrieval when plan has no days"""
    plan_id = uuid4()
    
    mock_plan = MagicMock()
    mock_plan.id = plan_id
    mock_plan.title = "Empty Plan"

    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.public.plan_service.get_days_by_plan_id") as mock_get_days:
        
        db_session = _mock_session_local(mock_session_local)
        mock_get_plan.return_value = mock_plan
        mock_get_days.return_value = []

        response = await get_plan_days(plan_id=plan_id)

        mock_get_plan.assert_called_once_with(db=db_session, plan_id=plan_id)
        mock_get_days.assert_called_once_with(db=db_session, plan_id=plan_id)

        assert isinstance(response, PlanDaysResponse)
        assert len(response.days) == 0


@pytest.mark.asyncio
async def test_get_plan_days_plan_not_found():
    """Test when plan does not exist"""
    plan_id = uuid4()

    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_plan_by_id") as mock_get_plan:
        
        db_session = _mock_session_local(mock_session_local)
        mock_get_plan.return_value = None 

        with pytest.raises(HTTPException) as exc_info:
            await get_plan_days(plan_id=plan_id)

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.detail == ErrorConstants.PLAN_NOT_FOUND

        mock_get_plan.assert_called_once_with(db=db_session, plan_id=plan_id)


def test_to_plan_date_from_datetime_and_date():
    assert _to_plan_date(datetime(2026, 5, 1, tzinfo=timezone.utc)) == DateType(2026, 5, 1)
    assert _to_plan_date(DateType(2026, 5, 2)) == DateType(2026, 5, 2)


def test_resolve_plan_for_date_in_series_empty():
    assert _resolve_plan_for_date_in_series([], DateType(2026, 5, 1)) is None


def test_resolve_plan_for_date_in_series_picks_active_plan():
    series_id = uuid4()
    plan_one = _daily_content_series_plan(
        uuid4(), series_id, 1, start_date=datetime(2026, 5, 1, tzinfo=timezone.utc)
    )
    plan_two = _daily_content_series_plan(
        uuid4(), series_id, 2, start_date=datetime(2026, 5, 10, tzinfo=timezone.utc)
    )

    assert _resolve_plan_for_date_in_series(
        [plan_two, plan_one], DateType(2026, 5, 5)
    ).id == plan_one.id
    assert _resolve_plan_for_date_in_series(
        [plan_one, plan_two], DateType(2026, 5, 15)
    ).id == plan_two.id


def test_resolve_plan_for_date_in_series_before_first_start():
    series_id = uuid4()
    plan = _daily_content_series_plan(
        uuid4(), series_id, 1, start_date=datetime(2026, 5, 10, tzinfo=timezone.utc)
    )

    assert _resolve_plan_for_date_in_series([plan], DateType(2026, 5, 1)).id == plan.id


def test_resolve_plan_for_date_in_series_without_start_dates():
    series_id = uuid4()
    plan = _daily_content_series_plan(uuid4(), series_id, 1)
    plan.start_date = None

    assert _resolve_plan_for_date_in_series([plan], DateType(2026, 5, 1)).id == plan.id


def test_filter_series_metadata_by_language():
    entry_en = MagicMock()
    entry_en.language = MagicMock(value="EN")
    entry_bo = MagicMock()
    entry_bo.language = "BO"

    filtered = _filter_series_metadata_by_language([entry_en, entry_bo], "en")

    assert filtered == [entry_en]


def test_filter_series_metadata_without_language_returns_entries():
    entry = MagicMock()
    entries = [entry]

    assert _filter_series_metadata_by_language(entries, None) == entries
    assert _filter_series_metadata_by_language(None, "en") == []


def test_filter_series_metadata_falls_back_to_en_when_language_missing():
    entry_en = MagicMock()
    entry_en.language = MagicMock(value="EN")

    # Requesting 'bo' which is absent -> falls back to the EN entry.
    filtered = _filter_series_metadata_by_language([entry_en], "bo")

    assert filtered == [entry_en]


def test_resolve_daily_plan_returns_entry_when_not_in_series():
    plan_id = uuid4()
    mock_plan = MagicMock()
    mock_plan.series_id = None
    mock_db = MagicMock()

    with patch(
        "pecha_api.plans.public.plan_service.get_published_plan_by_id",
        return_value=mock_plan,
    ) as mock_get:
        result = _resolve_daily_plan(db=mock_db, plan_id=plan_id, requested_date=None, language="en")

    assert result is mock_plan
    mock_get.assert_called_once_with(db=mock_db, plan_id=plan_id)


def test_resolve_daily_plan_raises_when_entry_not_found():
    mock_db = MagicMock()

    with patch(
        "pecha_api.plans.public.plan_service.get_published_plan_by_id",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_daily_plan(db=mock_db, plan_id=uuid4(), requested_date=None, language="en")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_resolve_daily_plan_raises_when_no_language_plans_in_series():
    series_id = uuid4()
    entry_plan = MagicMock()
    entry_plan.series_id = series_id
    entry_plan.language = LanguageCode.EN
    mock_db = MagicMock()

    with patch(
        "pecha_api.plans.public.plan_service.get_published_plan_by_id",
        return_value=entry_plan,
    ), patch(
        "pecha_api.plans.public.plan_service.get_published_plans_in_series",
        return_value=[],
    ):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_daily_plan(db=mock_db, plan_id=uuid4(), requested_date=None, language=None)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_resolve_daily_plan_uses_entry_language_when_omitted():
    series_id = uuid4()
    plan_id = uuid4()
    entry_plan = _daily_content_series_plan(plan_id, series_id, 1)
    mock_db = MagicMock()

    with patch(
        "pecha_api.plans.public.plan_service.get_published_plan_by_id",
        return_value=entry_plan,
    ), patch(
        "pecha_api.plans.public.plan_service.get_published_plans_in_series",
        return_value=[entry_plan],
    ) as mock_series:
        result = _resolve_daily_plan(
            db=mock_db, plan_id=plan_id, requested_date=DateType(2026, 5, 1), language=None
        )

    assert result is entry_plan
    mock_series.assert_called_once_with(db=mock_db, series_id=series_id, language="EN")


def _daily_content_mock_db_session(total_days: int):
    mock_db = MagicMock()
    mock_db.__enter__ = Mock(return_value=mock_db)
    mock_db.__exit__ = Mock(return_value=None)
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = total_days
    return mock_db


def _daily_content_series_plan(
    plan_id,
    series_id,
    display_order: int,
    start_date=None,
    language_value: str = "EN",
):
    mock_plan = MagicMock()
    mock_plan.id = plan_id
    mock_plan.title = f"Plan {display_order}"
    mock_plan.description = "Desc"
    mock_plan.image_url = None
    mock_plan.series_id = series_id
    mock_plan.display_order = display_order
    mock_plan.start_date = start_date or datetime(2026, 5, 1, tzinfo=timezone.utc)
    mock_plan.language = MagicMock(value=language_value)
    mock_series = MagicMock()
    mock_series.id = series_id
    metadata_entry = MagicMock()
    metadata_entry.id = uuid4()
    metadata_entry.title = "Series"
    metadata_entry.description = None
    metadata_entry.language = MagicMock(value="EN")
    mock_series.metadata_entries = [metadata_entry]
    mock_series.image = None
    mock_plan.series = mock_series
    return mock_plan


@pytest.mark.asyncio
async def test_get_plan_daily_content_first_day_sets_previous_plan_id_in_series():
    plan_id = uuid4()
    series_id = uuid4()
    prev_plan_uuid = uuid4()
    mock_plan = _daily_content_series_plan(plan_id, series_id, display_order=2)
    mock_plan_item = MagicMock()
    mock_plan_item.tasks = []
    mock_prev = MagicMock()
    mock_prev.id = prev_plan_uuid
    mock_db = _daily_content_mock_db_session(total_days=3)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_in_series", return_value=[mock_plan]), \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks", return_value=mock_plan_item), \
         patch("pecha_api.plans.public.plan_service.get_previous_plan_in_series", return_value=mock_prev) as mock_prev_fn, \
         patch("pecha_api.plans.public.plan_service.get_next_plan_in_series") as mock_next_fn, \
         patch("pecha_api.plans.public.plan_service.get_image_url", new_callable=AsyncMock, return_value=None):

        result = await get_plan_daily_content(
            plan_id=plan_id, requested_date=DateType(2026, 5, 1), language="en"
        )

    assert isinstance(result, DailyPlanResponse)
    assert result.previous_plan_id == prev_plan_uuid
    assert result.next_plan_id is None
    mock_prev_fn.assert_called_once_with(
        db=mock_db, series_id=series_id, current_display_order=2, language="en"
    )
    mock_next_fn.assert_not_called()


@pytest.mark.asyncio
async def test_get_plan_daily_content_last_day_sets_next_plan_id_in_series():
    plan_id = uuid4()
    series_id = uuid4()
    next_plan_uuid = uuid4()
    mock_plan = _daily_content_series_plan(plan_id, series_id, display_order=2)
    mock_plan_item = MagicMock()
    mock_plan_item.tasks = []
    mock_next = MagicMock()
    mock_next.id = next_plan_uuid
    mock_db = _daily_content_mock_db_session(total_days=3)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_in_series", return_value=[mock_plan]), \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks", return_value=mock_plan_item), \
         patch("pecha_api.plans.public.plan_service.get_previous_plan_in_series") as mock_prev_fn, \
         patch("pecha_api.plans.public.plan_service.get_next_plan_in_series", return_value=mock_next) as mock_next_fn, \
         patch("pecha_api.plans.public.plan_service.get_image_url", new_callable=AsyncMock, return_value=None):

        result = await get_plan_daily_content(
            plan_id=plan_id, requested_date=DateType(2026, 5, 3), language="en"
        )

    assert isinstance(result, DailyPlanResponse)
    assert result.next_plan_id == next_plan_uuid
    assert result.previous_plan_id is None
    mock_next_fn.assert_called_once_with(
        db=mock_db, series_id=series_id, current_display_order=2, language="en"
    )
    mock_prev_fn.assert_not_called()

@pytest.mark.asyncio
async def test_get_plan_daily_content_resolves_plan_by_date_in_series():
    series_id = uuid4()
    plan_one_id = uuid4()
    plan_two_id = uuid4()
    entry_plan = _daily_content_series_plan(
        plan_two_id,
        series_id,
        display_order=2,
        start_date=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    active_plan = _daily_content_series_plan(
        plan_one_id,
        series_id,
        display_order=1,
        start_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    mock_plan_item = MagicMock()
    mock_plan_item.tasks = []
    mock_db = _daily_content_mock_db_session(total_days=3)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=entry_plan), \
         patch(
             "pecha_api.plans.public.plan_service.get_published_plans_in_series",
             return_value=[active_plan, entry_plan],
         ) as mock_series_plans, \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks", return_value=mock_plan_item) as mock_day_fn, \
         patch("pecha_api.plans.public.plan_service.get_next_plan_in_series", return_value=None), \
         patch("pecha_api.plans.public.plan_service.get_previous_plan_in_series", return_value=None), \
         patch("pecha_api.plans.public.plan_service.get_image_url", new_callable=AsyncMock, return_value=None):

        result = await get_plan_daily_content(
            plan_id=plan_two_id,
            requested_date=DateType(2026, 5, 3),
            language="en",
        )

    assert result.plan_id == plan_one_id
    mock_series_plans.assert_called_with(
        db=mock_db, series_id=series_id, language="en"
    )
    assert mock_series_plans.call_count == 2
    mock_day_fn.assert_called_once_with(db=mock_db, plan_id=plan_one_id, day_number=3)


@pytest.mark.asyncio
async def test_get_plan_daily_content_plan_not_found():
    plan_id = uuid4()
    mock_db = _daily_content_mock_db_session(total_days=0)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=None):

        with pytest.raises(HTTPException) as exc_info:
            await get_plan_daily_content(plan_id=plan_id)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def _standalone_daily_plan(plan_id, *, start_date=None):
    return SimpleNamespace(
        id=plan_id,
        title="Solo Plan",
        description="Desc",
        image_url=None,
        series_id=None,
        series=None,
        display_order=None,
        start_date=start_date,
        language=SimpleNamespace(value="EN"),
    )


@pytest.mark.asyncio
async def test_get_plan_daily_content_standalone_plan_without_series():
    plan_id = uuid4()
    mock_plan = _standalone_daily_plan(
        plan_id, start_date=datetime(2026, 5, 1, tzinfo=timezone.utc)
    )
    mock_plan_item = MagicMock()
    mock_plan_item.tasks = []
    mock_db = _daily_content_mock_db_session(total_days=2)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan), \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks", return_value=mock_plan_item), \
         patch("pecha_api.plans.public.plan_service.get_image_url", new_callable=AsyncMock, return_value=None):

        result = await get_plan_daily_content(
            plan_id=plan_id, requested_date=DateType(2026, 5, 2)
        )

    assert result.plan_id == plan_id
    assert result.series is None
    assert result.day_number == 2


@pytest.mark.asyncio
async def test_get_plan_daily_content_no_content_yet():
    plan_id = uuid4()
    mock_plan = _standalone_daily_plan(plan_id)
    mock_db = _daily_content_mock_db_session(total_days=0)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan):

        with pytest.raises(HTTPException) as exc_info:
            await get_plan_daily_content(plan_id=plan_id)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "no content yet" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_plan_daily_content_date_out_of_range():
    plan_id = uuid4()
    mock_plan = _standalone_daily_plan(
        plan_id, start_date=datetime(2026, 5, 1, tzinfo=timezone.utc)
    )
    mock_db = _daily_content_mock_db_session(total_days=3)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan):

        with pytest.raises(HTTPException) as exc_info:
            await get_plan_daily_content(
                plan_id=plan_id, requested_date=DateType(2026, 5, 10)
            )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "No content for date" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_plan_daily_content_defaults_date_when_before_plan_window():
    plan_id = uuid4()
    mock_plan = _standalone_daily_plan(
        plan_id, start_date=datetime(2099, 1, 1, tzinfo=timezone.utc)
    )
    mock_plan.title = "Future Plan"
    mock_plan_item = MagicMock()
    mock_plan_item.tasks = []
    mock_db = _daily_content_mock_db_session(total_days=5)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan), \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks", return_value=mock_plan_item), \
         patch("pecha_api.plans.public.plan_service.get_image_url", new_callable=AsyncMock, return_value=None):

        result = await get_plan_daily_content(plan_id=plan_id)

    assert result.date == DateType(2099, 1, 1)
    assert result.day_number == 1


@pytest.mark.asyncio
async def test_get_plan_daily_content_filters_series_metadata_by_navigation_language():
    plan_id = uuid4()
    series_id = uuid4()
    mock_plan = _daily_content_series_plan(plan_id, series_id, display_order=1)
    bo_entry = MagicMock()
    bo_entry.id = uuid4()
    bo_entry.title = "Tibetan"
    bo_entry.description = None
    bo_entry.language = MagicMock(value="BO")
    mock_plan.series.metadata_entries = [
        mock_plan.series.metadata_entries[0],
        bo_entry,
    ]
    mock_plan_item = MagicMock()
    mock_plan_item.tasks = []
    mock_db = _daily_content_mock_db_session(total_days=1)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan), \
         patch("pecha_api.plans.public.plan_service.get_published_plans_in_series", return_value=[mock_plan]), \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks", return_value=mock_plan_item), \
         patch("pecha_api.plans.public.plan_service.get_previous_plan_in_series", return_value=None), \
         patch("pecha_api.plans.public.plan_service.get_next_plan_in_series", return_value=None), \
         patch("pecha_api.plans.public.plan_service.get_image_url", new_callable=AsyncMock, return_value=None):

        result = await get_plan_daily_content(
            plan_id=plan_id, requested_date=DateType(2026, 5, 1), language="en"
        )

    assert result.series is not None
    assert result.series.metadata.language == "EN"


@pytest.mark.asyncio
async def test_get_plan_daily_content_defaults_date_to_today_when_in_window():
    from pecha_api.plans.public import plan_service

    plan_id = uuid4()
    today = plan_service.dt.now(timezone.utc).date()
    # Anchor the window relative to today so the test stays stable on any date:
    # start 5 days ago with a 30-day window keeps today inside the window.
    start = today - timedelta(days=5)
    mock_plan = _standalone_daily_plan(
        plan_id,
        start_date=datetime(start.year, start.month, start.day, tzinfo=timezone.utc),
    )
    mock_plan_item = MagicMock()
    mock_plan_item.tasks = []
    mock_db = _daily_content_mock_db_session(total_days=30)

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan), \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks", return_value=mock_plan_item), \
         patch("pecha_api.plans.public.plan_service.get_image_url", new_callable=AsyncMock, return_value=None):

        result = await get_plan_daily_content(plan_id=plan_id)

    assert result.date == today
    assert result.day_number == (today - start).days + 1


@pytest.mark.asyncio
async def test_get_plan_daily_content_without_start_date_uses_today():
    from pecha_api.plans.public import plan_service

    plan_id = uuid4()
    mock_plan = _standalone_daily_plan(plan_id)
    mock_plan.start_date = None
    mock_plan_item = MagicMock()
    mock_plan_item.tasks = []
    mock_db = _daily_content_mock_db_session(total_days=1)
    today = plan_service.dt.now(timezone.utc).date()

    with patch("pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db), \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan), \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks", return_value=mock_plan_item), \
         patch("pecha_api.plans.public.plan_service.get_image_url", new_callable=AsyncMock, return_value=None):

        result = await get_plan_daily_content(plan_id=plan_id)

    assert result.date == today
    assert result.day_number == 1


def test_resolve_daily_plan_raises_when_date_resolution_fails():
    series_id = uuid4()
    entry_plan = _daily_content_series_plan(uuid4(), series_id, 1)
    mock_db = MagicMock()

    with patch(
        "pecha_api.plans.public.plan_service.get_published_plan_by_id",
        return_value=entry_plan,
    ), patch(
        "pecha_api.plans.public.plan_service.get_published_plans_in_series",
        return_value=[entry_plan],
    ), patch(
        "pecha_api.plans.public.plan_service._resolve_plan_for_date_in_series",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_daily_plan(db=mock_db, plan_id=entry_plan.id, requested_date=None, language="en")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_plan_day_details_success():
    """Test successful retrieval of plan day details with tasks and subtasks"""
    plan_id = uuid4()
    day_number = 1
    
    mock_subtask_1 = MagicMock()
    mock_subtask_1.id = uuid4()
    mock_subtask_1.content_type = ContentType.TEXT
    mock_subtask_1.content = "Subtask content 1"
    mock_subtask_1.duration = "10 minutes"
    mock_subtask_1.display_order = 1
    mock_subtask_1.source_text_id = None
    mock_subtask_1.pecha_segment_id = None
    mock_subtask_1.segment_ids = None
    mock_subtask_1.reference_id = None
    
    mock_task = MagicMock()
    mock_task.id = uuid4()
    mock_task.title = "Test Task"
    mock_task.estimated_time = 30
    mock_task.display_order = 1
    mock_task.sub_tasks = [mock_subtask_1]
    
    mock_plan_item = MagicMock()
    mock_plan_item.id = uuid4()
    mock_plan_item.day_number = day_number
    mock_plan_item.tasks = [mock_task]
    mock_plan_item.shareable_images = None
    mock_plan_item.videos = []
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks") as mock_get_plan_day, \
         patch("pecha_api.plans.public.plan_service.get_plan_day_detail_cache", return_value=None) as mock_get_cache, \
         patch("pecha_api.plans.public.plan_service.set_plan_day_detail_cache") as mock_set_cache:
        
        db_session = _mock_session_local(mock_session_local)
        mock_get_plan_day.return_value = mock_plan_item
        series_id = uuid4()
        db_session.query.return_value.filter.return_value.scalar.return_value = series_id

        response = await get_plan_day_details(plan_id=plan_id, day_number=day_number)

        mock_get_cache.assert_awaited_once_with(plan_id=plan_id, day_number=day_number)
        mock_get_plan_day.assert_called_once_with(db=db_session, plan_id=plan_id, day_number=day_number)
        mock_set_cache.assert_awaited_once()
        assert response.series_id == series_id

        assert isinstance(response, PlanDayDTO)
        assert response.id == mock_plan_item.id
        assert response.day_number == day_number
        assert len(response.tasks) == 1
        
        task = response.tasks[0]
        assert task.id == mock_task.id
        assert task.title == "Test Task"
        assert task.estimated_time == 30
        assert task.display_order == 1
        assert len(task.subtasks) == 1
        
        assert task.subtasks[0].id == mock_subtask_1.id
        assert task.subtasks[0].content_type == ContentType.TEXT
        assert task.subtasks[0].content == "Subtask content 1"
        assert task.subtasks[0].display_order == 1
        assert response.thumbnail_url is None
        assert response.shareable_image_url is None


@pytest.mark.asyncio
async def test_get_plan_day_details_cache_hit_resolves_series_id():
    """Cached entries written before series_id existed still get it filled in."""
    plan_id = uuid4()
    series_id = uuid4()
    cached = PlanDayDTO(id=uuid4(), day_number=1, tasks=[])

    with patch("pecha_api.plans.public.plan_service.get_plan_day_detail_cache", return_value=cached), \
         patch("pecha_api.plans.public.plan_service._get_plan_series_id", return_value=series_id):

        response = await get_plan_day_details(plan_id=plan_id, day_number=1)

    assert response is cached
    assert response.series_id == series_id


@pytest.mark.asyncio
async def test_get_plan_day_details_includes_shareable_image_urls():
    plan_id = uuid4()
    day_number = 1

    mock_shareable_images = MagicMock()
    mock_shareable_images.thumbnail_key = "images/day_shareable/thumb.webp"
    mock_shareable_images.shareable_image_key = "images/day_shareable/share.webp"

    mock_plan_item = MagicMock()
    mock_plan_item.id = uuid4()
    mock_plan_item.day_number = day_number
    mock_plan_item.tasks = []
    mock_plan_item.shareable_images = mock_shareable_images
    mock_plan_item.videos = []

    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_plan_day_with_tasks_and_subtasks") as mock_get_plan_day, \
         patch("pecha_api.plans.public.plan_service.get_plan_day_detail_cache", return_value=None), \
         patch("pecha_api.plans.public.plan_service.set_plan_day_detail_cache"), \
         patch(
             "pecha_api.plans.public.plan_service.build_plan_day_shareable_image_fields",
             return_value=(
                 "https://bucket.s3.amazonaws.com/thumb",
                 "images/day_shareable/thumb.webp",
                 "https://bucket.s3.amazonaws.com/share",
                 "images/day_shareable/share.webp",
             ),
         ):
        _mock_session_local(mock_session_local)
        mock_get_plan_day.return_value = mock_plan_item

        response = await get_plan_day_details(plan_id=plan_id, day_number=day_number)

        assert response.thumbnail_url == "https://bucket.s3.amazonaws.com/thumb"
        assert response.shareable_image_url == "https://bucket.s3.amazonaws.com/share"

def test_get_tags_success(mock_db_session):
    """Test successful retrieval of tags."""
    # Create metadata entries for tag_one
    meta_one = MagicMock()
    meta_one.language = MagicMock()
    meta_one.language.value = "EN"
    meta_one.name = "meditation"
    meta_one.description = None
    
    tag_one = MagicMock()
    tag_one.id = uuid4()
    tag_one.image_key = None
    tag_one.deleted_at = None
    tag_one.metadata_entries = [meta_one]
    tag_one.featured = False
    tag_one.display_order = None
    
    # Create metadata entries for tag_two
    meta_two = MagicMock()
    meta_two.language = MagicMock()
    meta_two.language.value = "EN"
    meta_two.name = "sleep"
    meta_two.description = None
    
    tag_two = MagicMock()
    tag_two.id = uuid4()
    tag_two.image_key = None
    tag_two.deleted_at = None
    tag_two.metadata_entries = [meta_two]
    tag_two.featured = False
    tag_two.display_order = None

    with patch(
        "pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session
    ), patch(
        "pecha_api.plans.public.plan_service.get_published_tags_for_language",
        return_value=[tag_one, tag_two],
    ) as mock_repo:

        result = get_tags(language="en")

        assert isinstance(result, TagsResponse)
        assert len(result.tags) == 2
        assert result.tags[0].name == "meditation"
        assert result.tags[1].name == "sleep"

        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value, language="EN"
        )

def test_get_tags_empty(mock_db_session):
    """Test retrieval when no tags exist."""
    with patch(
        "pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session
    ), patch(
        "pecha_api.plans.public.plan_service.get_published_tags_for_language", return_value=[]
    ) as mock_repo:

        result = get_tags(language="en")

        assert isinstance(result, TagsResponse)
        assert result.tags == []


def test_get_public_tags_success(mock_db_session):
    # Create metadata entries for tag_one
    meta_one = MagicMock()
    meta_one.language = MagicMock()
    meta_one.language.value = "EN"
    meta_one.name = "meditation"
    meta_one.description = None
    
    tag_one = MagicMock()
    tag_one.id = uuid4()
    tag_one.image_key = None
    tag_one.deleted_at = None
    tag_one.metadata_entries = [meta_one]
    tag_one.featured = False
    tag_one.display_order = None
    
    # Create metadata entries for tag_two
    meta_two = MagicMock()
    meta_two.language = MagicMock()
    meta_two.language.value = "EN"
    meta_two.name = "sleep"
    meta_two.description = None
    
    tag_two = MagicMock()
    tag_two.id = uuid4()
    tag_two.image_key = None
    tag_two.deleted_at = None
    tag_two.metadata_entries = [meta_two]
    tag_two.featured = False
    tag_two.display_order = None

    with patch(
        "pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session
    ), patch(
        "pecha_api.plans.public.plan_service.get_all_tags_paginated",
        return_value=([tag_one, tag_two], 2),
    ) as mock_repo:
        result = get_public_tags(
            featured=True,
            search="med",
            skip=0,
            limit=10,
        )

    assert isinstance(result, PublicTagsListResponse)
    assert len(result.tags) == 2
    assert result.total == 2
    assert result.skip == 0
    assert result.limit == 10
    mock_repo.assert_called_once_with(
        db=mock_db_session.__enter__.return_value,
        featured=True,
        search="med",
        skip=0,
        limit=10,
    )

@pytest.mark.asyncio
async def test_get_published_plans_with_tag_filter(
    sample_plan_aggregate, mock_db_session
):
    with patch(
        "pecha_api.plans.public.plan_service.SessionLocal", return_value=mock_db_session
    ), patch(
        "pecha_api.plans.public.plan_service.get_published_plans_from_db",
        return_value=[sample_plan_aggregate],
    ) as mock_repo, patch(
        "pecha_api.plans.public.plan_service.get_published_plans_count", return_value=1
    ), patch(
        "pecha_api.plans.public.plan_service.generate_presigned_access_url",
        return_value="https://bucket.s3.amazonaws.com/presigned-url",
    ):

        result = await get_published_plans(
            tag="meditation",
            search=None,
            language="en",
            sort_by="title",
            sort_order="asc",
            skip=0,
            limit=20,
            group_id=None,
        )

        assert len(result.plans) == 1
        mock_repo.assert_called_once_with(
            db=mock_db_session.__enter__.return_value,
            skip=0,
            limit=20,
            search=None,
            language="EN",
            sort_by="title",
            sort_order="asc",
            tag="meditation",
            group_id=None,
        )


# ============================================================================
# AUTO ENROLL PLAN TESTS
# ============================================================================

@pytest.fixture
def mock_plan_for_enrollment():
    plan = MagicMock()
    plan.id = uuid4()
    plan.title = "Plan Week 2"
    plan.series_id = uuid4()
    plan.display_order = 2
    plan.start_date = datetime(2026, 5, 10, tzinfo=timezone.utc)
    return plan


@pytest.fixture
def mock_previous_plan():
    plan = MagicMock()
    plan.id = uuid4()
    plan.title = "Plan Week 1"
    plan.series_id = uuid4()
    plan.display_order = 1
    plan.start_date = datetime(2026, 5, 1, tzinfo=timezone.utc)
    return plan


@pytest.fixture
def mock_next_plan():
    plan = MagicMock()
    plan.id = uuid4()
    plan.title = "Plan Week 3"
    plan.series_id = uuid4()
    plan.display_order = 3
    plan.start_date = datetime(2026, 5, 20, tzinfo=timezone.utc)
    return plan


def test_auto_enroll_plan_success(mock_plan_for_enrollment, mock_previous_plan, mock_next_plan):
    """Test successful auto-enrollment when all conditions are met"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    mock_previous_enrollment = MagicMock()
    mock_previous_enrollment.id = uuid4()
    
    mock_new_progress = MagicMock()
    mock_new_progress.user_id = user_id
    mock_new_progress.plan_id = plan_id
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id") as mock_get_progress, \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=mock_previous_plan.id), \
         patch("pecha_api.plans.public.plan_service.is_within_plan_date_range", return_value=True), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save, \
         patch("pecha_api.plans.public.plan_service.UserPlanProgress", return_value=mock_new_progress) as mock_progress_class, \
         patch("pecha_api.plans.public.plan_service.dt") as mock_dt:
        
        db_session = _mock_session_local(mock_session_local)
        
        mock_get_progress.return_value = None
        
        mock_dt.now.return_value.date.return_value = DateType(2026, 5, 15)
        mock_dt.now.return_value = datetime(2026, 5, 15, tzinfo=timezone.utc)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_called_once()
        mock_progress_class.assert_called_once()
        call_kwargs = mock_progress_class.call_args.kwargs
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["plan_id"] == plan_id


def test_auto_enroll_plan_no_user_id():
    """Test that auto-enrollment does nothing when user_id is None"""
    plan_id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local:
        auto_enroll_plan(plan_id=plan_id, user_id=None)
        
        mock_session_local.assert_not_called()


def test_auto_enroll_plan_already_enrolled(mock_plan_for_enrollment):
    """Test that auto-enrollment skips when user is already enrolled"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    existing_enrollment = MagicMock()
    existing_enrollment.id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=existing_enrollment), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save:
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_not_called()


def test_auto_enroll_plan_not_in_series():
    """Test that auto-enrollment skips when plan is not in a series"""
    user_id = uuid4()
    
    plan_no_series = MagicMock()
    plan_no_series.id = uuid4()
    plan_no_series.series_id = None
    plan_no_series.display_order = None
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=plan_no_series), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=None), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save:
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_no_series.id, user_id=user_id)
        
        mock_save.assert_not_called()


def test_auto_enroll_plan_no_previous_plan(mock_plan_for_enrollment):
    """Test that auto-enrollment skips when there's no previous plan in series"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=None), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save:
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_not_called()


def test_auto_enroll_plan_not_enrolled_in_previous(mock_plan_for_enrollment, mock_previous_plan):
    """Test that auto-enrollment skips when user is not enrolled in previous plan"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=None), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save:
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_not_called()


def test_auto_enroll_plan_before_start_date(mock_plan_for_enrollment, mock_previous_plan):
    """Test that auto-enrollment skips when current date is before plan start date"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=mock_previous_plan.id), \
         patch("pecha_api.plans.public.plan_service.is_within_plan_date_range", return_value=False), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save:
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_not_called()


def test_auto_enroll_plan_after_next_plan_start(mock_plan_for_enrollment, mock_previous_plan, mock_next_plan):
    """Test that auto-enrollment skips when current date is after next plan's start date"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=mock_previous_plan.id), \
         patch("pecha_api.plans.public.plan_service.is_within_plan_date_range", return_value=False), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save:
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_not_called()


def test_auto_enroll_plan_no_start_date(mock_previous_plan):
    """Test that auto-enrollment skips when plan has no start date"""
    user_id = uuid4()
    
    plan_no_start = MagicMock()
    plan_no_start.id = uuid4()
    plan_no_start.series_id = uuid4()
    plan_no_start.display_order = 2
    plan_no_start.start_date = None
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=plan_no_start), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=mock_previous_plan.id), \
         patch("pecha_api.plans.public.plan_service.is_within_plan_date_range", return_value=False), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save:
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_no_start.id, user_id=user_id)
        
        mock_save.assert_not_called()


def test_auto_enroll_plan_no_next_plan(mock_plan_for_enrollment, mock_previous_plan):
    """Test successful auto-enrollment when there's no next plan (last plan in series)"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    mock_new_progress = MagicMock()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=mock_previous_plan.id), \
         patch("pecha_api.plans.public.plan_service.is_within_plan_date_range", return_value=True), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save, \
         patch("pecha_api.plans.public.plan_service.UserPlanProgress", return_value=mock_new_progress), \
         patch("pecha_api.plans.public.plan_service.dt") as mock_dt:
        
        _mock_session_local(mock_session_local)
        
        mock_dt.now.return_value.date.return_value = DateType(2026, 5, 15)
        mock_dt.now.return_value = datetime(2026, 5, 15, tzinfo=timezone.utc)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_called_once()


def test_auto_enroll_plan_plan_not_found():
    """Test that auto-enrollment handles plan not found gracefully"""
    user_id = uuid4()
    plan_id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save:
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_not_called()


def test_auto_enroll_plan_database_error():
    """Test that auto-enrollment handles database errors gracefully without raising"""
    user_id = uuid4()
    plan_id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", side_effect=Exception("Database error")):
        
        _mock_session_local(mock_session_local)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)


def test_auto_enroll_plan_adds_to_routine_time_blocks(mock_plan_for_enrollment, mock_previous_plan, mock_next_plan):
    """Test that auto-enrollment adds the new plan to routine time blocks where previous plan exists"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    mock_new_progress = MagicMock()
    
    mock_time_block = MagicMock()
    mock_time_block.id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=mock_previous_plan.id), \
         patch("pecha_api.plans.public.plan_service.is_within_plan_date_range", return_value=True), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save, \
         patch("pecha_api.plans.public.plan_service.UserPlanProgress", return_value=mock_new_progress), \
         patch("pecha_api.plans.public.plan_service.get_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_time_blocks_containing_series", return_value=[]), \
         patch("pecha_api.plans.public.plan_service.get_time_blocks_containing_plan", return_value=[mock_time_block]) as mock_get_blocks, \
         patch("pecha_api.plans.public.plan_service.get_max_display_order_in_time_block", return_value=2) as mock_get_max_order, \
         patch("pecha_api.plans.public.plan_service.add_plan_session_to_time_block") as mock_add_session, \
         patch("pecha_api.plans.public.plan_service.dt") as mock_dt:
        
        _mock_session_local(mock_session_local)
        
        mock_dt.now.return_value.date.return_value = DateType(2026, 5, 15)
        mock_dt.now.return_value = datetime(2026, 5, 15, tzinfo=timezone.utc)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_called_once()
        mock_get_blocks.assert_called_once()
        mock_get_max_order.assert_called_once_with(db=mock_session_local().__enter__(), time_block_id=mock_time_block.id)
        mock_add_session.assert_called_once_with(
            db=mock_session_local().__enter__(),
            time_block_id=mock_time_block.id,
            plan_id=plan_id,
            display_order=3
        )


def test_auto_enroll_plan_adds_to_multiple_time_blocks(mock_plan_for_enrollment, mock_previous_plan, mock_next_plan):
    """Test that auto-enrollment adds the new plan to all time blocks where previous plan exists"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    mock_new_progress = MagicMock()
    
    mock_time_block_1 = MagicMock()
    mock_time_block_1.id = uuid4()
    mock_time_block_2 = MagicMock()
    mock_time_block_2.id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=mock_previous_plan.id), \
         patch("pecha_api.plans.public.plan_service.is_within_plan_date_range", return_value=True), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress"), \
         patch("pecha_api.plans.public.plan_service.UserPlanProgress", return_value=mock_new_progress), \
         patch("pecha_api.plans.public.plan_service.get_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_time_blocks_containing_series", return_value=[]), \
         patch("pecha_api.plans.public.plan_service.get_time_blocks_containing_plan", return_value=[mock_time_block_1, mock_time_block_2]), \
         patch("pecha_api.plans.public.plan_service.get_max_display_order_in_time_block", return_value=1), \
         patch("pecha_api.plans.public.plan_service.add_plan_session_to_time_block") as mock_add_session, \
         patch("pecha_api.plans.public.plan_service.dt") as mock_dt:
        
        _mock_session_local(mock_session_local)
        
        mock_dt.now.return_value.date.return_value = DateType(2026, 5, 15)
        mock_dt.now.return_value = datetime(2026, 5, 15, tzinfo=timezone.utc)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        assert mock_add_session.call_count == 2


def test_auto_enroll_plan_no_time_blocks_with_previous_plan(mock_plan_for_enrollment, mock_previous_plan, mock_next_plan):
    """Test that auto-enrollment handles case when previous plan is not in any time block"""
    user_id = uuid4()
    plan_id = mock_plan_for_enrollment.id
    
    mock_new_progress = MagicMock()
    
    with patch("pecha_api.plans.public.plan_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.public.plan_service.get_published_plan_by_id", return_value=mock_plan_for_enrollment), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None), \
         patch("pecha_api.plans.public.plan_service.is_user_enrolled_in_previous_plan", return_value=mock_previous_plan.id), \
         patch("pecha_api.plans.public.plan_service.is_within_plan_date_range", return_value=True), \
         patch("pecha_api.plans.public.plan_service.save_plan_progress") as mock_save, \
         patch("pecha_api.plans.public.plan_service.UserPlanProgress", return_value=mock_new_progress), \
         patch("pecha_api.plans.public.plan_service.get_time_blocks_containing_plan", return_value=[]), \
         patch("pecha_api.plans.public.plan_service.add_plan_session_to_time_block") as mock_add_session, \
         patch("pecha_api.plans.public.plan_service.dt") as mock_dt:
        
        _mock_session_local(mock_session_local)
        
        mock_dt.now.return_value.date.return_value = DateType(2026, 5, 15)
        mock_dt.now.return_value = datetime(2026, 5, 15, tzinfo=timezone.utc)
        
        auto_enroll_plan(plan_id=plan_id, user_id=user_id)
        
        mock_save.assert_called_once()
        mock_add_session.assert_not_called()


# ============================================================================
# HELPER FUNCTION TESTS
# ============================================================================

def test_is_user_enrolled_in_previous_plan_success(mock_plan_for_enrollment, mock_previous_plan):
    """Test that helper returns previous plan ID when user is enrolled"""
    user_id = uuid4()
    mock_db = MagicMock()
    
    mock_previous_enrollment = MagicMock()
    mock_previous_enrollment.id = uuid4()
    
    with patch("pecha_api.plans.public.plan_service.get_previous_plan_in_series", return_value=mock_previous_plan), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=mock_previous_enrollment):
        
        result = is_user_enrolled_in_previous_plan(mock_db, user_id, mock_plan_for_enrollment)
        
        assert result == mock_previous_plan.id


def test_is_user_enrolled_in_previous_plan_not_in_series():
    """Test that helper returns None when plan is not in a series"""
    user_id = uuid4()
    mock_db = MagicMock()
    
    plan_no_series = MagicMock()
    plan_no_series.series_id = None
    plan_no_series.display_order = None
    
    result = is_user_enrolled_in_previous_plan(mock_db, user_id, plan_no_series)
    
    assert result is None


def test_is_user_enrolled_in_previous_plan_no_previous_plan(mock_plan_for_enrollment):
    """Test that helper returns None when there's no previous plan"""
    user_id = uuid4()
    mock_db = MagicMock()
    
    with patch("pecha_api.plans.public.plan_service.get_previous_plan_in_series", return_value=None):
        
        result = is_user_enrolled_in_previous_plan(mock_db, user_id, mock_plan_for_enrollment)
        
        assert result is None


def test_is_user_enrolled_in_previous_plan_not_enrolled(mock_plan_for_enrollment, mock_previous_plan):
    """Test that helper returns None when user is not enrolled in previous plan"""
    user_id = uuid4()
    mock_db = MagicMock()
    
    with patch("pecha_api.plans.public.plan_service.get_previous_plan_in_series", return_value=mock_previous_plan), \
         patch("pecha_api.plans.public.plan_service.get_plan_progress_by_user_id_and_plan_id", return_value=None):
        
        result = is_user_enrolled_in_previous_plan(mock_db, user_id, mock_plan_for_enrollment)
        
        assert result is None


def test_is_within_plan_date_range_success(mock_plan_for_enrollment):
    """Test that helper returns True when current date is within plan date range"""
    mock_db = MagicMock()
    
    with patch("pecha_api.plans.public.plan_service.dt") as mock_dt, \
         patch("pecha_api.plans.public.plan_service.get_next_plan_in_series", return_value=None):
        
        mock_dt.now.return_value.date.return_value = DateType(2026, 5, 15)
        
        result = is_within_plan_date_range(mock_db, mock_plan_for_enrollment)
        
        assert result is True


def test_is_within_plan_date_range_no_start_date():
    """Test that helper returns False when plan has no start date"""
    mock_db = MagicMock()
    
    plan_no_start = MagicMock()
    plan_no_start.start_date = None
    
    result = is_within_plan_date_range(mock_db, plan_no_start)
    
    assert result is False


def test_is_within_plan_date_range_before_start(mock_plan_for_enrollment):
    """Test that helper returns False when current date is before plan start"""
    mock_db = MagicMock()
    
    with patch("pecha_api.plans.public.plan_service.dt") as mock_dt:
        mock_dt.now.return_value.date.return_value = DateType(2026, 5, 5)
        
        result = is_within_plan_date_range(mock_db, mock_plan_for_enrollment)
        
        assert result is False


def test_is_within_plan_date_range_after_next_plan_start(mock_plan_for_enrollment, mock_next_plan):
    """Test that helper returns False when current date is after next plan's start"""
    mock_db = MagicMock()
    
    with patch("pecha_api.plans.public.plan_service.dt") as mock_dt, \
         patch("pecha_api.plans.public.plan_service.get_next_plan_in_series", return_value=mock_next_plan):
        
        mock_dt.now.return_value.date.return_value = DateType(2026, 5, 25)
        
        result = is_within_plan_date_range(mock_db, mock_plan_for_enrollment)
        
        assert result is False


def test_is_within_plan_date_range_no_next_plan(mock_plan_for_enrollment):
    """Test that helper returns True when there's no next plan and date is after start"""
    mock_db = MagicMock()
    
    with patch("pecha_api.plans.public.plan_service.dt") as mock_dt, \
         patch("pecha_api.plans.public.plan_service.get_next_plan_in_series", return_value=None):
        
        mock_dt.now.return_value.date.return_value = DateType(2026, 6, 15)
        
        result = is_within_plan_date_range(mock_db, mock_plan_for_enrollment)
        
        assert result is True