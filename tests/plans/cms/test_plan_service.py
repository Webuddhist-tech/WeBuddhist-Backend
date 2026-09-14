import uuid
import pytest
from unittest.mock import patch, MagicMock, ANY, AsyncMock
from fastapi import HTTPException
from datetime import datetime, timezone

import pecha_api.plans.cms.cms_plans_service as plans_service
from pecha_api.plans.plans_enums import DifficultyLevel, PlanStatus, ContentType, PlanAudioType, MonlamVoiceName
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.tasks.plan_tasks_models import PlanTask
from pecha_api.plans.plans_response_models import (
    CreatePlanRequest, UpdatePlanRequest, PlanStatusUpdate,
    PlanDTO,PlanWithAggregates, PlansRepositoryResponse, AuthorDTO
)
from pecha_api.plans.cms.cms_plans_service import (
    create_new_plan, get_filtered_plans, get_details_plan,
    update_plan_details, update_selected_plan_status, delete_selected_plan, get_plan_day_details,
    DUMMY_PLANS, DUMMY_DAYS,
    _get_subscription_count, _validate_start_date_update, _apply_plan_field_updates, _generate_plan_image_url,
    _validate_plan_schedule_within_series, shift_subsequent_series_plans,
    generate_plan_audio_service, _generate_subtask_audio, _generate_audio_segments,
    _build_combined_wav, _update_subtask_timestamps, _upload_and_persist_audio,
)
from pecha_api.plans.platform_enums import PlatformRole
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole

TEST_GROUP_ID = uuid.uuid4()


def _mock_session_local(mock_session_local):
    mock_db_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db_session
    mock_session_local.return_value.__exit__.return_value = False
    return mock_db_session


# ============================================================================
# Tests for helper functions (extracted to reduce cognitive complexity)
# ============================================================================

def test_get_subscription_count_returns_count():
    """Test _get_subscription_count returns the correct count"""
    plan_id = uuid.uuid4()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.scalar.return_value = 15
    
    result = _get_subscription_count(mock_db, plan_id)
    
    assert result == 15
    mock_db.query.assert_called_once()


def test_get_subscription_count_returns_zero_when_none():
    """Test _get_subscription_count returns 0 when scalar returns None"""
    plan_id = uuid.uuid4()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.scalar.return_value = None
    
    result = _get_subscription_count(mock_db, plan_id)
    
    assert result == 0


def test_validate_start_date_update_raises_for_published_with_subscribers():
    """Test _validate_start_date_update raises HTTPException for published plan with subscribers"""
    plan_id = uuid.uuid4()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.scalar.return_value = 5
    
    mock_plan = MagicMock()
    mock_plan.status = PlanStatus.PUBLISHED
    mock_plan.start_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    new_start_date = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    with pytest.raises(HTTPException) as exc_info:
        _validate_start_date_update(mock_db, mock_plan, plan_id, new_start_date)
    
    assert exc_info.value.status_code == 400


def test_validate_start_date_update_allows_draft_plan():
    """Test _validate_start_date_update does not raise for draft plan"""
    plan_id = uuid.uuid4()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.scalar.return_value = 5
    
    mock_plan = MagicMock()
    mock_plan.status = PlanStatus.DRAFT
    
    new_start_date = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    _validate_start_date_update(mock_db, mock_plan, plan_id, new_start_date)


def test_validate_start_date_update_allows_published_with_no_subscribers():
    """Test _validate_start_date_update does not raise for published plan with no subscribers"""
    plan_id = uuid.uuid4()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.scalar.return_value = 0
    
    mock_plan = MagicMock()
    mock_plan.status = PlanStatus.PUBLISHED
    
    new_start_date = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    _validate_start_date_update(mock_db, mock_plan, plan_id, new_start_date)


def test_validate_start_date_update_allows_same_date_for_published_with_subscribers():
    """Test _validate_start_date_update does not raise when start date is not changing for published plan with subscribers"""
    plan_id = uuid.uuid4()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.scalar.return_value = 5
    
    same_start_date = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    mock_plan = MagicMock()
    mock_plan.status = PlanStatus.PUBLISHED
    mock_plan.start_date = same_start_date
    
    # This should not raise because the date is not actually changing
    _validate_start_date_update(mock_db, mock_plan, plan_id, same_start_date)


def _mock_series_plan_for_schedule(start_date, display_order=2):
    mock_plan = MagicMock()
    mock_plan.id = uuid.uuid4()
    mock_plan.series_id = uuid.uuid4()
    mock_plan.display_order = display_order
    mock_plan.start_date = start_date
    return mock_plan


def test_validate_plan_schedule_raises_when_plan_runs_into_next_plan():
    """Moving start_date later makes the plan's 26 days spill past the next plan's start"""
    mock_db = MagicMock()
    # Plan starts Jul 1 with 26 days -> ends Jul 26; next plan starts Jul 10
    mock_plan = _mock_series_plan_for_schedule(datetime(2026, 7, 1, tzinfo=timezone.utc))

    with patch("pecha_api.plans.cms.cms_plans_service.get_last_day_number", return_value=26), \
         patch("pecha_api.plans.cms.cms_plans_service.get_next_series_plan_start_date",
               return_value=datetime(2026, 7, 10, tzinfo=timezone.utc)), \
         patch("pecha_api.plans.cms.cms_plans_service.get_previous_series_plans_schedule", return_value=[]):
        with pytest.raises(HTTPException) as exc_info:
            _validate_plan_schedule_within_series(db=mock_db, plan=mock_plan)

    assert exc_info.value.status_code == 400
    assert "2026-07-26" in exc_info.value.detail["message"]
    assert "2026-07-10" in exc_info.value.detail["message"]


def test_validate_plan_schedule_raises_when_previous_plan_overlaps_new_start():
    """Moving start_date earlier lands inside the previous plan's span"""
    mock_db = MagicMock()
    # Previous plan starts Jun 14 with 26 days -> ends Jul 9; this plan moved to Jul 5
    mock_plan = _mock_series_plan_for_schedule(datetime(2026, 7, 5, tzinfo=timezone.utc))

    with patch("pecha_api.plans.cms.cms_plans_service.get_last_day_number", return_value=0), \
         patch("pecha_api.plans.cms.cms_plans_service.get_next_series_plan_start_date", return_value=None), \
         patch("pecha_api.plans.cms.cms_plans_service.get_previous_series_plans_schedule",
               return_value=[(datetime(2026, 6, 14, tzinfo=timezone.utc), 26)]):
        with pytest.raises(HTTPException) as exc_info:
            _validate_plan_schedule_within_series(db=mock_db, plan=mock_plan)

    assert exc_info.value.status_code == 400
    assert "2026-07-09" in exc_info.value.detail["message"]


def test_validate_plan_schedule_allows_non_overlapping_schedule():
    """Plan ends the day before the next plan starts and starts after the previous plan ends"""
    mock_db = MagicMock()
    # Previous ends Jul 9, this plan runs Jul 10 - Jul 23 (14 days), next starts Jul 24
    mock_plan = _mock_series_plan_for_schedule(datetime(2026, 7, 10, tzinfo=timezone.utc))

    with patch("pecha_api.plans.cms.cms_plans_service.get_last_day_number", return_value=14), \
         patch("pecha_api.plans.cms.cms_plans_service.get_next_series_plan_start_date",
               return_value=datetime(2026, 7, 24, tzinfo=timezone.utc)), \
         patch("pecha_api.plans.cms.cms_plans_service.get_previous_series_plans_schedule",
               return_value=[(datetime(2026, 6, 14, tzinfo=timezone.utc), 26)]):
        _validate_plan_schedule_within_series(db=mock_db, plan=mock_plan)


def test_validate_plan_schedule_skips_plans_outside_series():
    """No series, no start_date, or no display_order -> validation is a no-op"""
    mock_db = MagicMock()
    mock_plan = _mock_series_plan_for_schedule(datetime(2026, 7, 1, tzinfo=timezone.utc))
    mock_plan.series_id = None

    with patch("pecha_api.plans.cms.cms_plans_service.get_last_day_number") as mock_last_day:
        _validate_plan_schedule_within_series(db=mock_db, plan=mock_plan)

    mock_last_day.assert_not_called()


def _mock_super_admin_author():
    author = MagicMock()
    author.id = uuid.uuid4()
    author.platform_role = PlatformRole.SUPER_ADMIN
    return author


def test_shift_subsequent_series_plans_noop_when_no_shift_needed():
    """shift_days <= 0, or plan not in a series, should not touch the repository"""
    mock_db = MagicMock()
    author = _mock_super_admin_author()

    with patch("pecha_api.plans.cms.cms_plans_service.get_subsequent_series_plans") as mock_get_subsequent:
        shift_subsequent_series_plans(db=mock_db, plan=_mock_series_plan_for_schedule(datetime(2026, 7, 1, tzinfo=timezone.utc)), shift_days=0, author=author)
        mock_get_subsequent.assert_not_called()

        no_series_plan = _mock_series_plan_for_schedule(datetime(2026, 7, 1, tzinfo=timezone.utc))
        no_series_plan.series_id = None
        shift_subsequent_series_plans(db=mock_db, plan=no_series_plan, shift_days=3, author=author)
        mock_get_subsequent.assert_not_called()


def test_shift_subsequent_series_plans_shifts_all_when_none_blocked():
    """Pushes every later plan's start_date forward by shift_days when none are published with subscribers"""
    mock_db = MagicMock()
    plan = _mock_series_plan_for_schedule(datetime(2026, 7, 1, tzinfo=timezone.utc))
    author = _mock_super_admin_author()

    next_plan = MagicMock()
    next_plan.id = uuid.uuid4()
    next_plan.title = "Next Plan"
    next_plan.status = PlanStatus.DRAFT
    next_plan.start_date = datetime(2026, 7, 10, tzinfo=timezone.utc)
    next_plan.group_id = TEST_GROUP_ID

    later_plan = MagicMock()
    later_plan.id = uuid.uuid4()
    later_plan.title = "Later Plan"
    later_plan.status = PlanStatus.DRAFT
    later_plan.start_date = datetime(2026, 7, 20, tzinfo=timezone.utc)
    later_plan.group_id = TEST_GROUP_ID

    with patch("pecha_api.plans.cms.cms_plans_service.get_subsequent_series_plans", return_value=[next_plan, later_plan]), \
         patch("pecha_api.plans.cms.cms_plans_service._get_subscription_count", return_value=0):
        shift_subsequent_series_plans(db=mock_db, plan=plan, shift_days=3, author=author)

    assert next_plan.start_date == datetime(2026, 7, 13, tzinfo=timezone.utc)
    assert later_plan.start_date == datetime(2026, 7, 23, tzinfo=timezone.utc)


def test_shift_subsequent_series_plans_blocked_by_published_plan_with_subscribers():
    """Raises identifying the blocking plan and leaves every start_date untouched"""
    mock_db = MagicMock()
    plan = _mock_series_plan_for_schedule(datetime(2026, 7, 1, tzinfo=timezone.utc))
    author = _mock_super_admin_author()

    next_plan = MagicMock()
    next_plan.id = uuid.uuid4()
    next_plan.title = "Locked Plan"
    next_plan.status = PlanStatus.PUBLISHED
    original_next_start = datetime(2026, 7, 10, tzinfo=timezone.utc)
    next_plan.start_date = original_next_start
    next_plan.group_id = TEST_GROUP_ID

    with patch("pecha_api.plans.cms.cms_plans_service.get_subsequent_series_plans", return_value=[next_plan]), \
         patch("pecha_api.plans.cms.cms_plans_service._get_subscription_count", return_value=5):
        with pytest.raises(HTTPException) as exc_info:
            shift_subsequent_series_plans(db=mock_db, plan=plan, shift_days=3, author=author)

    assert exc_info.value.status_code == 400
    assert "Locked Plan" in exc_info.value.detail["message"]
    assert next_plan.start_date == original_next_start


def test_shift_subsequent_series_plans_blocked_by_author_lacking_edit_permission():
    """A group AUTHOR cascading from a DRAFT plan must not be able to shift a subsequent
    PUBLISHED/UNPUBLISHED/ARCHIVED plan's schedule, even with no active subscribers.

    require_can_edit_content is stubbed globally by the autouse _stub_cms_group_permissions
    fixture, so it's overridden here with the real 403-raising behavior for this one test.
    """
    mock_db = MagicMock()
    plan = _mock_series_plan_for_schedule(datetime(2026, 7, 1, tzinfo=timezone.utc))

    author = MagicMock()
    author.id = uuid.uuid4()
    author.platform_role = PlatformRole.CREATOR

    next_plan = MagicMock()
    next_plan.id = uuid.uuid4()
    next_plan.title = "Published Plan"
    next_plan.status = PlanStatus.PUBLISHED
    next_plan.start_date = datetime(2026, 7, 10, tzinfo=timezone.utc)
    next_plan.group_id = TEST_GROUP_ID

    def _fake_require_can_edit_content(db, group_id, author, content_status):
        if content_status != PlanStatus.DRAFT:
            raise HTTPException(status_code=403, detail="CONTENT_PUBLISHED_READ_ONLY")
        return AuthorGroupMemberRole.AUTHOR

    with patch("pecha_api.plans.cms.cms_plans_service.get_subsequent_series_plans", return_value=[next_plan]), \
         patch("pecha_api.plans.cms.cms_plans_service._get_subscription_count", return_value=0), \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content", side_effect=_fake_require_can_edit_content) as mock_edit_check:
        with pytest.raises(HTTPException) as exc_info:
            shift_subsequent_series_plans(db=mock_db, plan=plan, shift_days=3, author=author)

    mock_edit_check.assert_called_once_with(
        db=mock_db, group_id=TEST_GROUP_ID, author=author, content_status=PlanStatus.PUBLISHED,
    )
    assert exc_info.value.status_code == 403
    assert next_plan.start_date == datetime(2026, 7, 10, tzinfo=timezone.utc)


def test_apply_plan_field_updates_updates_all_fields():
    """Test _apply_plan_field_updates updates all provided fields"""
    mock_plan = MagicMock()
    mock_plan.title = "Original"
    mock_plan.description = "Original Desc"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = "original.jpg"
    mock_plan.language = "en"
    
    update_request = UpdatePlanRequest(
        title="New Title",
        description="New Description",
        difficulty_level=DifficultyLevel.ADVANCED,
        image_url="new.jpg",
        language="bo"
    )
    
    _apply_plan_field_updates(mock_plan, update_request)
    
    assert mock_plan.title == "New Title"
    assert mock_plan.description == "New Description"
    assert mock_plan.difficulty_level == DifficultyLevel.ADVANCED
    assert mock_plan.image_url == "new.jpg"
    assert mock_plan.language == "bo"


def test_apply_plan_field_updates_skips_none_fields():
    """Test _apply_plan_field_updates does not update fields that are None"""
    mock_plan = MagicMock()
    mock_plan.title = "Original"
    mock_plan.description = "Original Desc"
    
    update_request = UpdatePlanRequest(title="New Title")
    
    _apply_plan_field_updates(mock_plan, update_request)
    
    assert mock_plan.title == "New Title"
    assert mock_plan.description == "Original Desc"


def test_generate_plan_image_url_returns_presigned_url():
    """Test _generate_plan_image_url returns presigned URL when successful"""
    with patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get, \
         patch("pecha_api.plans.cms.cms_plans_service.generate_presigned_access_url") as mock_presign:
        mock_get.return_value = "test-bucket"
        mock_presign.return_value = "https://s3.amazonaws.com/presigned-url"
        
        result = _generate_plan_image_url("images/test.jpg")
        
        assert result == "https://s3.amazonaws.com/presigned-url"
        mock_get.assert_called_once_with("AWS_BUCKET_NAME")
        mock_presign.assert_called_once_with("test-bucket", "images/test.jpg")


def test_generate_plan_image_url_returns_none_for_empty_key():
    """Test _generate_plan_image_url returns None when image key is empty"""
    result = _generate_plan_image_url(None)
    assert result is None
    
    result = _generate_plan_image_url("")
    assert result is None


def test_generate_plan_image_url_returns_key_on_exception():
    """Test _generate_plan_image_url returns original key when presign fails"""
    with patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get, \
         patch("pecha_api.plans.cms.cms_plans_service.generate_presigned_access_url") as mock_presign:
        mock_get.return_value = "test-bucket"
        mock_presign.side_effect = Exception("S3 error")
        
        result = _generate_plan_image_url("images/test.jpg")
        
        assert result == "images/test.jpg"


# ============================================================================
# Tests for main service functions
# ============================================================================

def test_create_new_plan_success():
    request = CreatePlanRequest(
        group_id=TEST_GROUP_ID,
        title="Mindfulness Basics",
        description="A simple plan to get started with mindfulness.",
        difficulty_level=DifficultyLevel.BEGINNER,
        total_days=7,
        language="en",
        image_url="https://example.com/image.jpg",
        tag_ids=[],
        start_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )

    saved_plan = MagicMock()
    saved_plan.id = uuid.uuid4()
    saved_plan.title = request.title
    saved_plan.description = request.description
    saved_plan.difficulty_level = request.difficulty_level
    saved_plan.image_url = request.image_url
    saved_plan.tag_list = []
    saved_plan.language = request.language
    saved_plan.status = PlanStatus.DRAFT
    saved_plan.start_date = request.start_date
    saved_plan.series_id = None
    saved_plan.display_order = None
    saved_plan.group_id = TEST_GROUP_ID

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.save_plan") as mock_save_plan, \
        patch("pecha_api.plans.cms.cms_plans_service.save_plan_items") as mock_save_plan_items, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_progress") as mock_get_plan_progress, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        db_session = _mock_session_local(mock_session_local)
        mock_save_plan.return_value = saved_plan
        # save_plan_items returns the list of saved items; return a list sized to total_days
        mock_save_plan_items.return_value = [MagicMock() for _ in range(request.total_days)]
        mock_get_plan_progress.return_value = []

        author = MagicMock()
        author.id = uuid.uuid4()
        author.email = "author@example.com"
        author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = author

        response = create_new_plan(token="dummy", create_plan_request=request)

        mock_validate_author.assert_called_once_with(token="dummy")
        mock_get_plan_progress.assert_called_once_with(db=db_session, plan_id=saved_plan.id)

        # verify repository interactions - plan
        mock_save_plan.assert_called_once_with(db=db_session, plan=ANY)
        called_kwargs = mock_save_plan.call_args.kwargs
        created_plan_model = called_kwargs["plan"]
        assert created_plan_model.title == request.title
        assert created_plan_model.description == request.description
        assert created_plan_model.image_url == request.image_url
        assert created_plan_model.start_date == request.start_date
        assert created_plan_model.author_id is not None
        assert str(created_plan_model.author_id) != ""

        # verify repository interactions - plan items (bulk)
        mock_save_plan_items.assert_called_once_with(db=db_session, plan_items=ANY)
        called_item_kwargs = mock_save_plan_items.call_args.kwargs
        created_plan_items = called_item_kwargs["plan_items"]
        assert isinstance(created_plan_items, list)
        assert len(created_plan_items) == request.total_days
        # verify each generated PlanItem model
        expected_days = list(range(1, request.total_days + 1))
        actual_days = [item.day_number for item in created_plan_items]
        assert actual_days == expected_days
        assert all(item.plan_id == saved_plan.id for item in created_plan_items)
        assert all(item.created_by == author.email for item in created_plan_items)

        # verify response mapping
        assert response is not None
        assert response.id == saved_plan.id
        assert response.title == request.title
        assert response.description == request.description
        assert response.image_url == request.image_url
        assert response.total_days == request.total_days
        assert response.status == PlanStatus.DRAFT
        assert response.subscription_count == 0
        assert response.start_date == request.start_date


def test_create_new_plan_with_series_id():
    series_id = uuid.uuid4()
    request = CreatePlanRequest(
        group_id=TEST_GROUP_ID,
        title="Series Plan",
        description="Attached to a series on create.",
        difficulty_level=DifficultyLevel.BEGINNER,
        total_days=3,
        language="en",
        series_id=series_id,
        display_order=2,
    )

    saved_plan = MagicMock()
    saved_plan.id = uuid.uuid4()
    saved_plan.title = request.title
    saved_plan.description = request.description
    saved_plan.difficulty_level = request.difficulty_level
    saved_plan.image_url = None
    saved_plan.tag_list = []
    saved_plan.language = request.language
    saved_plan.status = PlanStatus.DRAFT
    saved_plan.start_date = None
    saved_plan.series_id = None
    saved_plan.display_order = None
    saved_plan.group_id = TEST_GROUP_ID

    mock_series = MagicMock()
    mock_series.author_id = uuid.uuid4()
    mock_series.group_id = TEST_GROUP_ID

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.save_plan") as mock_save_plan, \
        patch("pecha_api.plans.cms.cms_plans_service.save_plan_items") as mock_save_plan_items, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_progress") as mock_get_plan_progress, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
        patch("pecha_api.plans.cms.cms_plans_service.get_series_by_id") as mock_get_series:
        db_session = _mock_session_local(mock_session_local)
        mock_save_plan.return_value = saved_plan
        mock_save_plan_items.return_value = [MagicMock() for _ in range(request.total_days)]
        mock_get_plan_progress.return_value = []
        mock_get_series.return_value = mock_series

        author = MagicMock()
        author.id = mock_series.author_id
        author.email = "author@example.com"
        author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = author

        create_new_plan(token="dummy", create_plan_request=request)

        created_plan_model = mock_save_plan.call_args.kwargs["plan"]
        assert created_plan_model.series_id == series_id
        assert created_plan_model.display_order == 2
        series_lookup_calls = [
            call_args
            for call_args in mock_get_series.call_args_list
            if call_args.kwargs.get("db") is not None
        ]
        assert len(series_lookup_calls) == 2
        assert all(
            call_args.kwargs == {"db": db_session, "series_id": series_id}
            for call_args in series_lookup_calls
        )
        assert mock_get_series.call_count == 2
        for call in mock_get_series.call_args_list:
            assert call.kwargs == {"db": db_session, "series_id": series_id}


def test_create_new_plan_with_series_id_auto_display_order():
    series_id = uuid.uuid4()
    request = CreatePlanRequest(
        group_id=TEST_GROUP_ID,
        title="Series Plan",
        description="Auto display order.",
        difficulty_level=DifficultyLevel.BEGINNER,
        total_days=1,
        language="en",
        series_id=series_id,
    )

    saved_plan = MagicMock()
    saved_plan.id = uuid.uuid4()
    saved_plan.title = request.title
    saved_plan.description = request.description
    saved_plan.difficulty_level = request.difficulty_level
    saved_plan.image_url = None
    saved_plan.tag_list = []
    saved_plan.language = request.language
    saved_plan.status = PlanStatus.DRAFT
    saved_plan.start_date = None
    saved_plan.series_id = None
    saved_plan.display_order = None
    saved_plan.group_id = TEST_GROUP_ID

    mock_series = MagicMock()
    mock_series.author_id = uuid.uuid4()
    mock_series.group_id = TEST_GROUP_ID

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.save_plan") as mock_save_plan, \
        patch("pecha_api.plans.cms.cms_plans_service.save_plan_items") as mock_save_plan_items, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_progress") as mock_get_plan_progress, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
        patch("pecha_api.plans.cms.cms_plans_service.get_series_by_id") as mock_get_series:
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 4
        mock_save_plan.return_value = saved_plan
        mock_save_plan_items.return_value = [MagicMock()]
        mock_get_plan_progress.return_value = []
        mock_get_series.return_value = mock_series

        author = MagicMock()
        author.id = mock_series.author_id
        author.email = "author@example.com"
        author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = author

        create_new_plan(token="dummy", create_plan_request=request)

        created_plan_model = mock_save_plan.call_args.kwargs["plan"]
        assert created_plan_model.series_id == series_id
        assert created_plan_model.display_order == 5


def test_create_new_plan_series_not_found():
    series_id = uuid.uuid4()
    request = CreatePlanRequest(
        group_id=TEST_GROUP_ID,
        title="Series Plan",
        description="Missing series.",
        difficulty_level=DifficultyLevel.BEGINNER,
        total_days=1,
        language="en",
        series_id=series_id,
    )

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
        patch("pecha_api.plans.cms.cms_plans_service.get_series_by_id") as mock_get_series:
        _mock_session_local(mock_session_local)
        mock_get_series.return_value = None

        author = MagicMock()
        author.id = uuid.uuid4()
        author.email = "author@example.com"
        author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = author

        with pytest.raises(HTTPException) as exc_info:
            create_new_plan(token="dummy", create_plan_request=request)

        assert exc_info.value.status_code == 404
        assert str(series_id) in exc_info.value.detail


def test_get_filtered_plans_success():
    plan1 = Plan(
        id=uuid.uuid4(),
        title="Plan One",
        description="Description One",
        image_url="https://example.com/one.jpg",
        status=PlanStatus.PUBLISHED,
        author_id=uuid.uuid4(),
        group_id=TEST_GROUP_ID,
        created_by="tester@example.com",
    )

    plan2 = Plan(
        id=uuid.uuid4(),
        title="Plan Two",
        description="Description Two",
        language="en",
        image_url="https://example.com/two.jpg",
        status=PlanStatus.DRAFT,
        author_id=uuid.uuid4(),
        group_id=TEST_GROUP_ID,
        created_by="tester@example.com",
    )
    plan1.tag_list = []
    plan2.tag_list = []

    # Repository now returns PlansRepositoryResponse with PlanWithAggregates items
    repo_response = PlansRepositoryResponse(
        plan_info=[
            PlanWithAggregates(plan=plan1, total_days=5, subscription_count=2),
            PlanWithAggregates(plan=plan2, total_days=0, subscription_count=0),
        ],
        total=2,
    )

    # attach minimal author relation attributes used by service when mapping AuthorDTO
    plan1.author = MagicMock()
    plan1.author.first_name = "A"
    plan1.author.last_name = "Author"
    plan1.author.image_url = "authors/a.jpg"
    plan2.author = MagicMock()
    plan2.author.first_name = "B"
    plan2.author.last_name = "Author"
    plan2.author.image_url = "authors/b.jpg"

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plans_by_author_id") as mock_get_plans_by_author_id, \
        patch("pecha_api.plans.cms.cms_plans_service.get_group_ids_by_plan_ids", return_value={plan1.id: TEST_GROUP_ID, plan2.id: TEST_GROUP_ID}), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
        patch("pecha_api.plans.cms.cms_plans_service.generate_presigned_access_url") as mock_presign, \
        patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get_config:
        db_session = _mock_session_local(mock_session_local)
        mock_get_plans_by_author_id.return_value = repo_response
        # author.id is used in service to pass author_id to repository
        mock_author = MagicMock(id=uuid.uuid4(), platform_role=PlatformRole.CREATOR, is_active=True)
        mock_validate_author.return_value = mock_author
        # Return the original key so assertions comparing to plan.image_url still pass
        mock_presign.side_effect = lambda bucket_name, s3_key: s3_key
        mock_get_config.return_value = "dummy-bucket"

        resp = get_filtered_plans(
            token="dummy-token",
            search="plan",
            sort_by="created_at",
            sort_order="desc",
            skip=5,
            limit=10,
        )

        mock_validate_author.assert_called_once_with(token="dummy-token")

        # verify repository interaction
        mock_get_plans_by_author_id.assert_called_once()
        called_kwargs = mock_get_plans_by_author_id.call_args.kwargs
        assert called_kwargs == {
            "db": db_session,
            "author": mock_author,
            "search": "plan",
            "sort_by": "created_at",
            "sort_order": "desc",
            "skip": 5,
            "limit": 10,
            "tag": None,
            "language": None,
            "group_id": None,
        }

        # verify response mapping
        assert resp is not None
        assert resp.skip == 5
        assert resp.limit == 10
        assert resp.total == 2
        assert len(resp.plans) == 2

        p1 = resp.plans[0]
        assert p1.id == plan1.id
        assert p1.title == plan1.title
        assert p1.description == plan1.description
        assert p1.image_url == plan1.image_url
        assert p1.total_days == 5
        assert p1.status == PlanStatus.PUBLISHED
        assert p1.subscription_count == 2
        # language fallback to default when missing on plan
        assert p1.language == "EN"
        # author DTO mapping
        assert p1.author == AuthorDTO(
            id=plan1.author_id,
            firstname="A",
            lastname="Author",
            image_url=plan1.author.image_url,
        )

        p2 = resp.plans[1]
        assert p2.id == plan2.id
        assert p2.status == PlanStatus.DRAFT
        # language preserved when provided on plan
        assert p2.language == "en"
        assert p2.author == AuthorDTO(
            id=plan2.author_id,
            firstname="B",
            lastname="Author",
            image_url=plan2.author.image_url,
        )


@pytest.mark.asyncio
async def test_get_details_plan_success():
    from datetime import datetime, timezone
    
    plan = Plan(
        id=uuid.uuid4(),
        title="Test Plan",
        description="Test Description",
        image_url="https://example.com/image.jpg",
        status=PlanStatus.PUBLISHED,
        author_id=uuid.uuid4(),
        group_id=TEST_GROUP_ID,
        created_by="tester@example.com",
    )
    # Ensure required fields used by service/DTO are present
    plan.difficulty_level = "BEGINNER"
    plan.tag_list = []
    plan.start_date = datetime(2025, 1, 1, tzinfo=timezone.utc)

    item1 = PlanItem(id=uuid.uuid4(), plan_id=plan.id, day_number=1, created_by="tester@example.com")
    item2 = PlanItem(id=uuid.uuid4(), plan_id=plan.id, day_number=2, created_by="tester@example.com")

    task1 = PlanTask(
        id=uuid.uuid4(),
        plan_item_id=item1.id,
        title="Morning Practice",
        display_order=1,
        estimated_time=10,
        created_by="tester@example.com",
    )
    task2 = PlanTask(
        id=uuid.uuid4(),
        plan_item_id=item2.id,
        title="Listen Audio",
        display_order=1,
        estimated_time=20,
        created_by="tester@example.com",
    )

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan_by_id, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_plan_items_by_plan_id, \
        patch("pecha_api.plans.cms.cms_plans_service.get_tasks_by_item_ids") as mock_get_tasks_by_item_ids, \
        patch("pecha_api.plans.audio.plan_item_audio_repository.get_plan_item_audio_by_plan_item_ids", return_value=[]) as mock_get_audio, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
        patch("pecha_api.plans.cms.cms_plans_service.generate_presigned_access_url") as mock_presign, \
        patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get_config:
        db_session = _mock_session_local(mock_session_local)
        mock_validate_author.return_value = MagicMock(platform_role=PlatformRole.CREATOR)
        mock_get_plan_by_id.return_value = plan
        mock_get_plan_items_by_plan_id.return_value = [item1, item2]
        mock_get_tasks_by_item_ids.return_value = [task1, task2]
        mock_presign.side_effect = lambda bucket_name, s3_key: s3_key
        mock_get_config.return_value = "dummy-bucket"

        response = await get_details_plan(token="dummy-token", plan_id=plan.id)

        mock_validate_author.assert_called_once_with(token="dummy-token")
        assert mock_get_plan_by_id.call_count == 2
        mock_get_plan_items_by_plan_id.assert_called_once_with(db=db_session, plan_id=plan.id)
        mock_get_tasks_by_item_ids.assert_called_once_with(db=db_session, plan_item_ids=[item1.id, item2.id])

        assert response is not None
        assert response.id == plan.id
        assert response.title == plan.title
        assert response.description == plan.description
        assert response.total_days == 2
        assert len(response.days) == 2
        # Image URL should be the same as input since we stub presign to echo key
        assert response.image_url == plan.image_url

        day1 = next(d for d in response.days if d.id == item1.id)
        assert day1.day_number == 1
        assert len(day1.tasks) == 1
        assert day1.tasks[0].id == task1.id
        assert day1.tasks[0].title == task1.title
        assert day1.tasks[0].estimated_time == task1.estimated_time

        day2 = next(d for d in response.days if d.id == item2.id)
        assert day2.day_number == 2
        assert len(day2.tasks) == 1
        assert day2.tasks[0].id == task2.id
        assert day2.tasks[0].estimated_time == task2.estimated_time
        
        # Verify start_date is returned
        assert response.start_date == datetime(2025, 1, 1, tzinfo=timezone.utc)

@pytest.mark.asyncio
async def test_get_plan_day_details_success():
    plan_id = uuid.uuid4()
    day_number = 3

    subtask1 = MagicMock()
    subtask1.id = uuid.uuid4()
    subtask1.content_type = ContentType.TEXT
    subtask1.content = "Practice for 10 minutes"
    subtask1.display_order = 1
    subtask1.timestamp = None
    subtask1.reference_id = None
    subtask2 = MagicMock()
    subtask2.id = uuid.uuid4()
    subtask2.content_type = ContentType.AUDIO
    subtask2.content = "https://example.com/audio.mp3"
    subtask2.display_order = 2
    subtask2.timestamp = None
    subtask2.reference_id = None
    task = MagicMock()
    task.id = uuid.uuid4()
    task.title = "Guided Meditation"
    task.estimated_time = 15
    task.display_order = 1
    task.sub_tasks = [subtask1, subtask2]

    plan_item = MagicMock()
    plan_item.id = uuid.uuid4()
    plan_item.day_number = day_number
    plan_item.tasks = [task]
    plan_item.audio = None
    plan_item.shareable_images = None
    plan_item.videos = []

    mock_plan_for_day = MagicMock()
    mock_plan_for_day.group_id = TEST_GROUP_ID
    mock_plan_for_day.deleted_at = None

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id", return_value=mock_plan_for_day), \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_day_with_tasks_and_subtasks") as mock_get_day, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        _ = _mock_session_local(mock_session_local)
        mock_validate_author.return_value = MagicMock()
        mock_get_day.return_value = plan_item

        resp = await get_plan_day_details(token="tkn", plan_id=plan_id, day_number=day_number)

        mock_validate_author.assert_called_once_with(token="tkn")
        mock_get_day.assert_called_once()

        assert resp.id == plan_item.id
        assert resp.day_number == day_number
        assert len(resp.tasks) == 1

        t = resp.tasks[0]
        assert t.id == task.id
        assert t.title == task.title
        assert t.estimated_time == task.estimated_time
        assert t.display_order == task.display_order
        assert len(t.subtasks) == 2
        assert t.subtasks[0].id == subtask1.id
        assert t.subtasks[0].content_type == ContentType.TEXT
        assert t.subtasks[0].content == subtask1.content
        assert t.subtasks[0].display_order == 1
        assert t.subtasks[1].id == subtask2.id
        assert t.subtasks[1].content_type == ContentType.AUDIO
        assert t.subtasks[1].content == subtask2.content
        assert t.subtasks[1].display_order == 2

@pytest.mark.asyncio
async def test_get_plan_day_details_not_found():
    non_existent_plan_id = uuid.uuid4()
    mock_plan_for_day = MagicMock()
    mock_plan_for_day.group_id = TEST_GROUP_ID
    mock_plan_for_day.deleted_at = None

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id", return_value=mock_plan_for_day), \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_day_with_tasks_and_subtasks") as mock_get_day, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        _ = _mock_session_local(mock_session_local)
        mock_validate_author.return_value = MagicMock()
        mock_get_day.side_effect = HTTPException(status_code=404, detail={"error": "Bad request", "message": "Plan day not found"})

        with pytest.raises(HTTPException) as exc_info:
            await get_plan_day_details(token="tkn", plan_id=non_existent_plan_id, day_number=1)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == {"error": "Bad request", "message": "Plan day not found"}
@pytest.mark.asyncio
async def test_get_plan_day_details_no_subtasks():
    plan_id = uuid.uuid4()
    day_number = 2

    task = MagicMock()
    task.id = uuid.uuid4()
    task.title = "Reading Practice"
    task.estimated_time = 5
    task.display_order = 1
    task.sub_tasks = []

    plan_item = MagicMock()
    plan_item.id = uuid.uuid4()
    plan_item.day_number = day_number
    plan_item.tasks = [task]
    plan_item.audio = None
    plan_item.shareable_images = None
    plan_item.videos = []

    mock_plan_for_day = MagicMock()
    mock_plan_for_day.group_id = TEST_GROUP_ID
    mock_plan_for_day.deleted_at = None

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id", return_value=mock_plan_for_day), \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_day_with_tasks_and_subtasks") as mock_get_day, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        _ = _mock_session_local(mock_session_local)
        mock_validate_author.return_value = MagicMock()
        mock_get_day.return_value = plan_item

        resp = await get_plan_day_details(token="tkn", plan_id=plan_id, day_number=day_number)

        assert resp.id == plan_item.id
        assert resp.day_number == day_number
        assert len(resp.tasks) == 1
        t = resp.tasks[0]
        assert t.id == task.id
        assert t.title == task.title
        assert t.display_order == task.display_order
        assert t.estimated_time == task.estimated_time
        assert t.subtasks == []
@pytest.mark.asyncio
async def test_get_details_plan_not_found():
    non_existent_id = uuid.uuid4()


    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan_by_id, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        _ = _mock_session_local(mock_session_local)

        mock_validate_author.return_value = MagicMock()
        mock_get_plan_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_details_plan(token="dummy-token", plan_id=non_existent_id)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == {"error": "Bad request", "message": "Plan not found"}


@pytest.mark.asyncio
async def test_update_plan_details_success():
    plan_id = uuid.uuid4()
    author_email = "author@example.com"
    author_id = uuid.uuid4()
    start_date = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Original Title"
    mock_plan.description = "Original Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = "images/plan_images/original.jpg"
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.start_date = None
    mock_plan.series_id = None
    mock_plan.display_order = None
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None
    
    existing_items = [MagicMock(spec=PlanItem, day_number=i) for i in range(1, 6)]
    
    update_request = UpdatePlanRequest(
        title="Updated Title",
        description="Updated Description",
        difficulty_level=DifficultyLevel.INTERMEDIATE,
        image_url="images/plan_images/updated.jpg",
        tag_ids=[],
        total_days=5,
        start_date=start_date,
    )
    
    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items, \
         patch("pecha_api.plans.cms.cms_plans_service.generate_presigned_access_url") as mock_presigned_url, \
         patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get_config:
        
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 10  
        
        mock_author = MagicMock()
        mock_author.email = author_email
        mock_author.id = author_id
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author
        
        mock_get_plan.return_value = mock_plan
        mock_update_plan.return_value = mock_plan
        mock_get_items.return_value = existing_items
        mock_presigned_url.return_value = "https://s3.amazonaws.com/presigned-url"
        mock_get_config.return_value = "test-bucket"
        
        response = await update_plan_details(
            token="test-token",
            plan_id=plan_id,
            update_plan_request=update_request
        )
        
        mock_validate_author.assert_called_once_with(token="test-token")
        mock_get_plan.assert_called_once_with(db=db_session, plan_id=plan_id)
        mock_update_plan.assert_called_once_with(db_session, mock_plan)
        
        assert mock_plan.title == update_request.title
        assert mock_plan.description == update_request.description
        assert mock_plan.difficulty_level == update_request.difficulty_level
        assert mock_plan.image_url == update_request.image_url
        assert mock_plan.tag_list == []
        assert mock_plan.updated_by == author_email
        assert mock_plan.start_date == start_date
        
        assert response.id == plan_id
        assert response.title == update_request.title
        assert response.description == update_request.description
        assert response.difficulty_level == update_request.difficulty_level
        assert response.total_days == 5
        assert response.subscription_count == 10
        assert response.image_url == "https://s3.amazonaws.com/presigned-url"
        assert response.start_date == start_date


@pytest.mark.asyncio
async def test_update_plan_details_cannot_update_start_date_for_published_with_subscribers():
    plan_id = uuid.uuid4()
    author_email = "author@example.com"
    author_id = uuid.uuid4()
    start_date = datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)

    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Original Title"
    mock_plan.description = "Original Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = "images/plan_images/original.jpg"
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.PUBLISHED
    mock_plan.start_date = None
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None

    update_request = UpdatePlanRequest(start_date=start_date)

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan:

        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 1

        mock_author = MagicMock()
        mock_author.email = author_email
        mock_author.id = author_id
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author

        mock_get_plan.return_value = mock_plan

        with pytest.raises(HTTPException) as exc:
            await update_plan_details(
                token="test-token",
                plan_id=plan_id,
                update_plan_request=update_request,
            )

        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_plan_details_partial_update():
    """Test updating only some fields (partial update)"""
    plan_id = uuid.uuid4()
    author_id = uuid.uuid4()
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Original Title"
    mock_plan.description = "Original Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = "images/original.jpg"
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.start_date = None
    mock_plan.series_id = None
    mock_plan.display_order = None
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None
    
    existing_items = [MagicMock(spec=PlanItem, day_number=i) for i in range(1, 6)]
    
    update_request = UpdatePlanRequest(
        title="New Title",
        description="New Description"
    )
    
    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items:
        
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 5
        
        mock_author = MagicMock()
        mock_author.email = "author@example.com"
        mock_author.id = author_id
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author
        
        mock_get_plan.return_value = mock_plan
        mock_update_plan.return_value = mock_plan
        mock_get_items.return_value = existing_items
        
        response = await update_plan_details(
            token="test-token",
            plan_id=plan_id,
            update_plan_request=update_request
        )
        
        assert mock_plan.title == "New Title"
        assert mock_plan.description == "New Description"
        assert mock_plan.difficulty_level == DifficultyLevel.BEGINNER
        assert mock_plan.image_url == "images/original.jpg"
        assert mock_plan.tag_list == []

        assert response.total_days == 5


@pytest.mark.asyncio
async def test_update_plan_details_not_found():
    """Test updating non-existent plan returns 404"""
    non_existent_id = uuid.uuid4()
    update_request = UpdatePlanRequest(title="Updated Title")
    
    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan:
        
        _mock_session_local(mock_session_local)
        
        mock_author = MagicMock()
        mock_validate_author.return_value = mock_author
        
        mock_get_plan.return_value = None  
        
        with pytest.raises(HTTPException) as exc_info:
            await update_plan_details(
                token="test-token",
                plan_id=non_existent_id,
                update_plan_request=update_request
            )
        
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == {"error": "Bad request", "message": "Plan not found"}


@pytest.mark.asyncio
async def test_update_plan_details_with_image_url_generation():
    """Test that image_url is properly generated with presigned URL"""
    plan_id = uuid.uuid4()
    author_id = uuid.uuid4()
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Test Plan"
    mock_plan.description = "Test Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = "images/plan_images/test.jpg"
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.start_date = None
    mock_plan.series_id = None
    mock_plan.display_order = None
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None
    
    existing_items = [MagicMock(spec=PlanItem, day_number=1)]
    
    update_request = UpdatePlanRequest(title="Test Plan")
    
    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items, \
         patch("pecha_api.plans.cms.cms_plans_service.generate_presigned_access_url") as mock_presigned_url, \
         patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get_config:
        
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 0
        
        mock_author = MagicMock()
        mock_author.id = author_id
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author
        
        mock_get_plan.return_value = mock_plan
        mock_update_plan.return_value = mock_plan
        mock_get_items.return_value = existing_items
        
        presigned_url = "https://s3.amazonaws.com/bucket/test.jpg?signature=xyz"
        mock_presigned_url.return_value = presigned_url
        mock_get_config.return_value = "test-bucket"
        
        response = await update_plan_details(
            token="test-token",
            plan_id=plan_id,
            update_plan_request=update_request
        )
        
        mock_get_config.assert_called_with("AWS_BUCKET_NAME")
        mock_presigned_url.assert_called_once_with("test-bucket", "images/plan_images/test.jpg")
        assert response.image_url == presigned_url


@pytest.mark.asyncio
async def test_update_plan_details_image_url_generation_failure():
    """Test that original image_url is used when presigned URL generation fails"""
    plan_id = uuid.uuid4()
    author_id = uuid.uuid4()
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Test Plan"
    mock_plan.description = "Test Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = "images/plan_images/test.jpg"
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.start_date = None
    mock_plan.series_id = None
    mock_plan.display_order = None
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None
    
    existing_items = [MagicMock(spec=PlanItem, day_number=1)]
    
    update_request = UpdatePlanRequest(title="Test Plan")
    
    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items, \
         patch("pecha_api.plans.cms.cms_plans_service.generate_presigned_access_url") as mock_presigned_url, \
         patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get_config:
        
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 0
        
        mock_author = MagicMock()
        mock_author.id = author_id
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author
        
        mock_get_plan.return_value = mock_plan
        mock_update_plan.return_value = mock_plan
        mock_get_items.return_value = existing_items
        
        mock_presigned_url.side_effect = Exception("S3 error")
        mock_get_config.return_value = "test-bucket"
        
        response = await update_plan_details(
            token="test-token",
            plan_id=plan_id,
            update_plan_request=update_request
        )
        
        assert response.image_url == "images/plan_images/test.jpg"


@pytest.mark.asyncio
async def test_update_plan_details_no_image_url():
    """Test updating plan with no image_url"""
    plan_id = uuid.uuid4()
    author_id = uuid.uuid4()
    
    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Test Plan"
    mock_plan.description = "Test Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = None
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.start_date = None
    mock_plan.series_id = None
    mock_plan.display_order = None
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None
    
    existing_items = [MagicMock(spec=PlanItem, day_number=1)]
    
    update_request = UpdatePlanRequest(title="Test Plan")
    
    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items:
        
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 0
        
        mock_author = MagicMock()
        mock_author.id = author_id
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author
        
        mock_get_plan.return_value = mock_plan
        mock_update_plan.return_value = mock_plan
        mock_get_items.return_value = existing_items
        
        response = await update_plan_details(
            token="test-token",
            plan_id=plan_id,
            update_plan_request=update_request
        )
        
        assert response.image_url is None


@pytest.mark.asyncio
async def test_update_plan_details_with_series_id():
    plan_id = uuid.uuid4()
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Test Plan"
    mock_plan.description = "Test Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = None
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.start_date = None
    mock_plan.series_id = None
    mock_plan.display_order = None
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None

    mock_series = MagicMock()
    mock_series.author_id = author_id
    mock_series.group_id = TEST_GROUP_ID

    existing_items = [MagicMock(spec=PlanItem, day_number=1)]
    update_request = UpdatePlanRequest(series_id=series_id, display_order=1)

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items, \
         patch("pecha_api.plans.cms.cms_plans_service.get_series_by_id") as mock_get_series:
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 0

        mock_author = MagicMock()
        mock_author.id = author_id
        mock_author.email = "author@example.com"
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author

        mock_get_plan.return_value = mock_plan
        mock_update_plan.return_value = mock_plan
        mock_get_items.return_value = existing_items
        mock_get_series.return_value = mock_series

        await update_plan_details(
            token="test-token",
            plan_id=plan_id,
            update_plan_request=update_request,
        )

        assert mock_plan.series_id == series_id
        assert mock_plan.display_order == 1
        mock_get_series.assert_called_once_with(db=db_session, series_id=series_id)


@pytest.mark.asyncio
async def test_update_plan_details_detach_series():
    plan_id = uuid.uuid4()
    author_id = uuid.uuid4()
    existing_series_id = uuid.uuid4()

    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Test Plan"
    mock_plan.description = "Test Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = None
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.start_date = None
    mock_plan.series_id = existing_series_id
    mock_plan.display_order = 2
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None

    existing_items = [MagicMock(spec=PlanItem, day_number=1)]
    update_request = UpdatePlanRequest.model_validate({"series_id": None})

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items:
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 0

        mock_author = MagicMock()
        mock_author.id = author_id
        mock_author.email = "author@example.com"
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author

        mock_get_plan.return_value = mock_plan
        mock_update_plan.return_value = mock_plan
        mock_get_items.return_value = existing_items

        await update_plan_details(
            token="test-token",
            plan_id=plan_id,
            update_plan_request=update_request,
        )

        assert mock_plan.series_id is None
        assert mock_plan.display_order is None


@pytest.mark.asyncio
async def test_update_plan_details_unchanged_series_id_skips_validation():
    """Regression: resending the existing (unchanged) series_id on an edit must
    not re-run series-group validation, even when the plan's group_id no longer
    matches the series' group_id (real data drift seen in production)."""
    plan_id = uuid.uuid4()
    author_id = uuid.uuid4()
    existing_series_id = uuid.uuid4()

    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Old Title"
    mock_plan.description = "Test Description"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = None
    mock_plan.tag_list = []
    mock_plan.language = MagicMock(value="en")
    mock_plan.status = PlanStatus.PUBLISHED
    mock_plan.start_date = None
    mock_plan.series_id = existing_series_id
    mock_plan.display_order = 3
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None

    existing_items = [MagicMock(spec=PlanItem, day_number=1)]
    # Frontend resends the whole object, including the unchanged series_id.
    update_request = UpdatePlanRequest(
        title="New Title", series_id=existing_series_id
    )

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items, \
         patch("pecha_api.plans.cms.cms_plans_service.get_series_by_id") as mock_get_series:
        db_session = _mock_session_local(mock_session_local)
        db_session.query.return_value.filter.return_value.scalar.return_value = 0

        mock_author = MagicMock()
        mock_author.id = author_id
        mock_author.email = "author@example.com"
        mock_author.platform_role = PlatformRole.CREATOR
        mock_validate_author.return_value = mock_author

        mock_get_plan.return_value = mock_plan
        mock_update_plan.return_value = mock_plan
        mock_get_items.return_value = existing_items

        await update_plan_details(
            token="test-token",
            plan_id=plan_id,
            update_plan_request=update_request,
        )

        # Title applied, series attachment left untouched, no re-validation.
        assert mock_plan.title == "New Title"
        assert mock_plan.series_id == existing_series_id
        assert mock_plan.display_order == 3
        mock_get_series.assert_not_called()


@pytest.mark.asyncio
async def test_update_selected_plan_status_success_db_backed():
    plan_id = uuid.uuid4()
    author_id = uuid.uuid4()

    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.title = "Title"
    mock_plan.description = "Desc"
    mock_plan.language = "EN"
    mock_plan.difficulty_level = DifficultyLevel.BEGINNER
    mock_plan.image_url = "images/plan.jpg"
    mock_plan.tag_list = []
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.series_id = None
    mock_plan.display_order = None
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None

    items = [MagicMock(spec=PlanItem), MagicMock(spec=PlanItem)]
    user_progress = [MagicMock(), MagicMock(), MagicMock()]

    status_update = PlanStatusUpdate(status=PlanStatus.PUBLISHED)

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan_by_id, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_progress") as mock_get_progress, \
         patch("pecha_api.plans.cms.cms_plans_service.update_plan") as mock_update_plan, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        db_session = _mock_session_local(mock_session_local)

        mock_validate_author.return_value = MagicMock(id=author_id, platform_role=PlatformRole.CREATOR)
        mock_get_plan_by_id.return_value = mock_plan
        mock_get_items.return_value = items
        mock_get_progress.return_value = user_progress
        mock_update_plan.return_value = mock_plan

        resp = await update_selected_plan_status(
            token="tkn",
            plan_id=plan_id,
            plan_status_update=status_update,
        )

        mock_get_plan_by_id.assert_called_once_with(db=db_session, plan_id=plan_id)
        mock_get_items.assert_called_with(db=db_session, plan_id=plan_id)
        mock_update_plan.assert_called_once_with(db=db_session, plan=mock_plan)

        assert resp.id == plan_id
        assert resp.status == PlanStatus.PUBLISHED
        assert resp.total_days == len(items)
        assert resp.subscription_count == len(user_progress)
        assert resp.image_url == mock_plan.image_url


@pytest.mark.asyncio
async def test_update_selected_plan_status_invalid_transition_no_days():
    plan_id = uuid.uuid4()
    author_id = uuid.uuid4()

    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = author_id
    mock_plan.status = PlanStatus.DRAFT
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan_by_id, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_items_by_plan_id") as mock_get_items, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        _ = _mock_session_local(mock_session_local)
        mock_validate_author.return_value = MagicMock(id=author_id, platform_role=PlatformRole.CREATOR)
        mock_get_plan_by_id.return_value = mock_plan
        mock_get_items.return_value = []

        with pytest.raises(HTTPException) as exc_info:
            await update_selected_plan_status(
                token="tkn",
                plan_id=plan_id,
                plan_status_update=PlanStatusUpdate(status=PlanStatus.PUBLISHED),
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == {"error": "Bad request", "message": "Plan must have at least one day with content to be published"}


@pytest.mark.asyncio
async def test_update_selected_plan_status_not_found():
    plan_id = uuid.uuid4()

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan_by_id, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        _ = _mock_session_local(mock_session_local)
        mock_validate_author.return_value = MagicMock(id=uuid.uuid4(), platform_role=PlatformRole.CREATOR)
        mock_get_plan_by_id.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await update_selected_plan_status(
                token="tkn",
                plan_id=plan_id,
                plan_status_update=PlanStatusUpdate(status=PlanStatus.PUBLISHED),
            )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == {"error": "Bad request", "message": "Plan not found"}


@pytest.mark.asyncio
async def test_update_selected_plan_status_author_mismatch():
    plan_id = uuid.uuid4()

    mock_plan = MagicMock(spec=Plan)
    mock_plan.id = plan_id
    mock_plan.author_id = uuid.uuid4()
    mock_plan.group_id = TEST_GROUP_ID
    mock_plan.deleted_at = None

    forbidden = HTTPException(
        status_code=403,
        detail={"error": "Bad request", "message": "You are not authorized to update this plan"},
    )

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan_by_id, \
         patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status", side_effect=forbidden), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        _ = _mock_session_local(mock_session_local)
        mock_validate_author.return_value = MagicMock(id=uuid.uuid4(), platform_role=PlatformRole.CREATOR)
        mock_get_plan_by_id.return_value = mock_plan

        with pytest.raises(HTTPException) as exc_info:
            await update_selected_plan_status(
                token="tkn",
                plan_id=plan_id,
                plan_status_update=PlanStatusUpdate(status=PlanStatus.PUBLISHED),
            )

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == {"error": "Bad request", "message": "You are not authorized to update this plan"}


@pytest.mark.asyncio
async def test_delete_selected_plan_success():
    plan_id = uuid.uuid4()
    author = MagicMock()
    author.id = uuid.uuid4()
    author.platform_role = PlatformRole.CREATOR

    plan = MagicMock(spec=Plan)
    plan.id = plan_id
    plan.author_id = author.id
    plan.group_id = TEST_GROUP_ID
    plan.deleted_at = None

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.cms.cms_plans_service.get_plan_by_id") as mock_get_plan_by_id, \
        patch("pecha_api.plans.cms.cms_plans_service._soft_delete_plan_by_id") as mock_soft_delete, \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_create_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_edit_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_read_group_content"), \
        patch("pecha_api.plans.cms.cms_plans_service.require_can_change_status"), \
        patch("pecha_api.plans.cms.cms_plans_service.validate_cms_author_details") as mock_validate_author:
        db_session = _mock_session_local(mock_session_local)
        mock_validate_author.return_value = author
        mock_get_plan_by_id.return_value = plan

        await delete_selected_plan(token="dummy-token", plan_id=plan_id)

        mock_validate_author.assert_called_once_with(token="dummy-token")
        mock_get_plan_by_id.assert_called_once_with(db=db_session, plan_id=plan_id)
        mock_soft_delete.assert_called_once_with(db=db_session, plan_id=plan_id, author=author)


# ============================================================================
# Tests for generate_plan_audio_service and _generate_subtask_audio
# ============================================================================

@pytest.mark.asyncio
async def test_generate_plan_audio_service_routes_to_subtask_audio():
    """Test generate_plan_audio_service routes to _generate_subtask_audio when sub_task_id provided"""
    sub_task_id = uuid.uuid4()
    expected_response = {
        "audio_url": "https://s3.example.com/audio.wav",
        "audio_duration_ms": 3000,
        "s3_key": "audio/plan_subtasks/test.wav",
    }

    with patch(
        "pecha_api.plans.cms.cms_plans_service._generate_subtask_audio",
        new_callable=AsyncMock,
        return_value=expected_response,
    ) as mock_subtask_audio:
        result = await generate_plan_audio_service(
            language="bo",
            sub_task_id=sub_task_id,
            audio_type=PlanAudioType.TEXT_READING,
            voice_name=MonlamVoiceName.DOLKAR_LHASA_FEMALE,
        )

        mock_subtask_audio.assert_called_once_with(
            sub_task_id=sub_task_id,
            audio_type=PlanAudioType.TEXT_READING,
            language="bo",
            voice_name=MonlamVoiceName.DOLKAR_LHASA_FEMALE,
        )
        assert result == expected_response


@pytest.mark.asyncio
async def test_generate_plan_audio_service_generates_day_audio():
    """Test generate_plan_audio_service generates combined audio for day_id"""
    day_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    task_id = uuid.uuid4()
    subtask_id = uuid.uuid4()

    subtask = MagicMock()
    subtask.id = subtask_id
    subtask.task_id = task_id
    subtask.content = "Test content"
    subtask.content_type = ContentType.TEXT
    subtask.audio_url = None

    task = MagicMock()
    task.sub_tasks = [subtask]

    plan_item = MagicMock()
    plan_item.id = day_id
    plan_item.plan_id = plan_id
    plan_item.tasks = [task]

    worker_response = {
        "s3_key": "audio/plan_subtasks/test.wav",
        "audio_url": "https://s3.example.com/audio.wav",
        "audio_duration_ms": 3000,
    }

    wav_header = b"RIFF" + b"\x00" * 40
    raw_pcm = b"\x00\x01\x02\x03" * 100

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_day_by_id_any_plan", return_value=plan_item), \
         patch("pecha_api.plans.audio.worker_client.generate_audio_from_text", new_callable=AsyncMock, return_value=worker_response), \
         patch("pecha_api.plans.cms.cms_plans_service.download_bytes", return_value=wav_header + raw_pcm), \
         patch("pecha_api.plans.cms.cms_plans_service.upload_bytes"), \
         patch("pecha_api.plans.cms.cms_plans_service.upsert_sub_task_timestamp"), \
         patch("pecha_api.plans.cms.cms_plans_service.upsert_plan_item_audio") as mock_upsert_audio, \
         patch("pecha_api.plans.cms.cms_plans_service.generate_presigned_access_url", return_value="https://presigned.url"):

        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_session_local.return_value.__exit__.return_value = False

        audio_row = MagicMock()
        audio_row.audio_key = "audio/plan_days/combined.wav"
        audio_row.duration_ms = 5000
        mock_upsert_audio.return_value = audio_row

        result = await generate_plan_audio_service(
            language="bo",
            day_id=day_id,
            audio_type=PlanAudioType.TEXT_READING,
            voice_name=MonlamVoiceName.DOLKAR_LHASA_FEMALE,
        )

        assert "audio_url" in result
        assert "audio_duration_ms" in result
        assert "s3_key" in result


@pytest.mark.asyncio
async def test_generate_plan_audio_service_returns_empty_for_no_segments():
    """Test generate_plan_audio_service returns empty list when no audio segments"""
    day_id = uuid.uuid4()

    plan_item = MagicMock()
    plan_item.id = day_id
    plan_item.plan_id = uuid.uuid4()
    plan_item.tasks = []

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_plan_day_by_id_any_plan", return_value=plan_item):

        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_session_local.return_value.__exit__.return_value = False

        result = await generate_plan_audio_service(
            language="bo",
            day_id=day_id,
        )

        assert result == []


@pytest.mark.asyncio
async def test_generate_subtask_audio_success():
    """Test _generate_subtask_audio calls worker, updates DB, returns response"""
    sub_task_id = uuid.uuid4()
    task_id = uuid.uuid4()

    subtask = MagicMock()
    subtask.id = sub_task_id
    subtask.task_id = task_id
    subtask.content = "བཀྲ་ཤིས་བདེ་ལེགས"
    subtask.content_type = ContentType.TEXT
    subtask.audio_url = None

    worker_response = {
        "s3_key": "audio/plan_subtasks/test.wav",
        "audio_url": "https://s3.example.com/audio.wav",
        "audio_duration_ms": 3000,
    }

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_sub_task_by_subtask_id", return_value=subtask), \
         patch("pecha_api.plans.audio.worker_client.generate_audio_from_text", new_callable=AsyncMock, return_value=worker_response) as mock_worker, \
         patch("pecha_api.plans.cms.cms_plans_service.upsert_sub_task_timestamp") as mock_upsert_timestamp:

        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_session_local.return_value.__exit__.return_value = False

        result = await _generate_subtask_audio(
            sub_task_id=sub_task_id,
            audio_type=PlanAudioType.TEXT_READING,
            language="bo",
            voice_name=MonlamVoiceName.DOLKAR_LHASA_FEMALE,
        )

        mock_worker.assert_called_once_with(
            text="བཀྲ་ཤིས་བདེ་ལེགས",
            language="bo",
            audio_type=PlanAudioType.TEXT_READING,
            voice_name=MonlamVoiceName.DOLKAR_LHASA_FEMALE,
            s3_key_prefix=f"audio/plan_subtasks/{task_id}/{sub_task_id}",
        )

        assert subtask.audio_url == "audio/plan_subtasks/test.wav"
        assert subtask.duration == "3000"
        mock_db.commit.assert_called()

        mock_upsert_timestamp.assert_called_once_with(
            db=mock_db,
            sub_task_id=sub_task_id,
            start_ms=0,
            end_ms=3000,
            created_by="system",
        )

        assert result == {
            "audio_url": "https://s3.example.com/audio.wav",
            "audio_duration_ms": 3000,
            "s3_key": "audio/plan_subtasks/test.wav",
        }


@pytest.mark.asyncio
async def test_generate_subtask_audio_not_found_raises_404():
    """Test _generate_subtask_audio raises 404 for missing subtask"""
    sub_task_id = uuid.uuid4()

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_sub_task_by_subtask_id", return_value=None):

        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_session_local.return_value.__exit__.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await _generate_subtask_audio(
                sub_task_id=sub_task_id,
                audio_type=PlanAudioType.TEXT_READING,
                language="bo",
            )

        assert exc_info.value.status_code == 404
        assert "Sub task not found" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_generate_subtask_audio_invalid_content_type_raises_400():
    """Test _generate_subtask_audio raises 400 for non-text content type"""
    sub_task_id = uuid.uuid4()

    subtask = MagicMock()
    subtask.id = sub_task_id
    subtask.content = "video_url"
    subtask.content_type = ContentType.VIDEO

    with patch("pecha_api.plans.cms.cms_plans_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.cms.cms_plans_service.get_sub_task_by_subtask_id", return_value=subtask):

        mock_db = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_db
        mock_session_local.return_value.__exit__.return_value = False

        with pytest.raises(HTTPException) as exc_info:
            await _generate_subtask_audio(
                sub_task_id=sub_task_id,
                audio_type=PlanAudioType.TEXT_READING,
                language="bo",
            )

        assert exc_info.value.status_code == 400
        assert "TEXT or SOURCE_REFERENCE" in str(exc_info.value.detail)


# ============================================================================
# Tests for helper functions
# ============================================================================

@pytest.mark.asyncio
async def test_generate_audio_segments_uses_existing_audio():
    """Test _generate_audio_segments downloads existing audio when audio_url is present"""
    task_id = uuid.uuid4()
    subtask_id = uuid.uuid4()

    subtask = MagicMock()
    subtask.id = subtask_id
    subtask.task_id = task_id
    subtask.content = "Test content"
    subtask.content_type = ContentType.TEXT
    subtask.audio_url = "audio/existing.wav"

    task = MagicMock()
    task.sub_tasks = [subtask]

    wav_header = b"RIFF" + b"\x00" * 40
    raw_pcm = b"\x00\x01\x02\x03" * 100
    existing_wav = wav_header + raw_pcm

    with patch("pecha_api.plans.cms.cms_plans_service.download_bytes", return_value=existing_wav) as mock_download, \
         patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get:
        
        mock_get.return_value = "test-bucket"

        audio_segments, subtask_refs = await _generate_audio_segments(
            tasks=[task],
            audio_type=PlanAudioType.TEXT_READING,
            language="bo",
            voice_name=MonlamVoiceName.DOLKAR_LHASA_FEMALE,
        )

        mock_download.assert_called_once_with(
            bucket_name="test-bucket",
            s3_key="audio/existing.wav",
        )
        assert len(audio_segments) == 1
        assert audio_segments[0] == raw_pcm
        assert len(subtask_refs) == 1
        assert subtask_refs[0] == subtask


@pytest.mark.asyncio
async def test_generate_audio_segments_generates_new_audio():
    """Test _generate_audio_segments calls worker API for new audio generation"""
    task_id = uuid.uuid4()
    subtask_id = uuid.uuid4()

    subtask = MagicMock()
    subtask.id = subtask_id
    subtask.task_id = task_id
    subtask.content = "New content"
    subtask.content_type = ContentType.TEXT
    subtask.audio_url = None

    task = MagicMock()
    task.sub_tasks = [subtask]

    worker_response = {
        "s3_key": "audio/plan_subtasks/new.wav",
        "audio_url": "https://s3.example.com/new.wav",
        "audio_duration_ms": 2000,
    }

    wav_header = b"RIFF" + b"\x00" * 40
    raw_pcm = b"\x00\x01\x02\x03" * 50
    generated_wav = wav_header + raw_pcm

    with patch("pecha_api.plans.audio.worker_client.generate_audio_from_text", new_callable=AsyncMock, return_value=worker_response) as mock_worker, \
         patch("pecha_api.plans.cms.cms_plans_service.download_bytes", return_value=generated_wav) as mock_download, \
         patch("pecha_api.plans.cms.cms_plans_service.get") as mock_get:
        
        mock_get.return_value = "test-bucket"

        audio_segments, subtask_refs = await _generate_audio_segments(
            tasks=[task],
            audio_type=PlanAudioType.RECITATION,
            language="en",
            voice_name=MonlamVoiceName.YANGCHEN_LHASA_FEMALE,
        )

        mock_worker.assert_called_once_with(
            text="New content",
            language="en",
            audio_type=PlanAudioType.RECITATION,
            voice_name=MonlamVoiceName.YANGCHEN_LHASA_FEMALE,
            s3_key_prefix=f"audio/plan_subtasks/{task_id}/{subtask_id}",
        )
        mock_download.assert_called_once_with(
            bucket_name="test-bucket",
            s3_key="audio/plan_subtasks/new.wav",
        )
        assert len(audio_segments) == 1
        assert audio_segments[0] == raw_pcm
        assert len(subtask_refs) == 1
        assert subtask_refs[0] == subtask


@pytest.mark.asyncio
async def test_generate_audio_segments_skips_non_text_content():
    """Test _generate_audio_segments skips subtasks with non-text content types"""
    task = MagicMock()
    
    text_subtask = MagicMock()
    text_subtask.content_type = ContentType.TEXT
    text_subtask.audio_url = "audio/text.wav"
    
    video_subtask = MagicMock()
    video_subtask.content_type = ContentType.VIDEO
    
    image_subtask = MagicMock()
    image_subtask.content_type = ContentType.IMAGE
    
    task.sub_tasks = [text_subtask, video_subtask, image_subtask]

    wav_header = b"RIFF" + b"\x00" * 40
    raw_pcm = b"\x00\x01" * 50
    wav_data = wav_header + raw_pcm

    with patch("pecha_api.plans.cms.cms_plans_service.download_bytes", return_value=wav_data), \
         patch("pecha_api.plans.cms.cms_plans_service.get", return_value="test-bucket"):

        audio_segments, subtask_refs = await _generate_audio_segments(
            tasks=[task],
            audio_type=PlanAudioType.TEXT_READING,
            language="bo",
        )

        assert len(audio_segments) == 1
        assert len(subtask_refs) == 1
        assert subtask_refs[0] == text_subtask


@pytest.mark.asyncio
async def test_generate_audio_segments_handles_source_reference():
    """Test _generate_audio_segments processes SOURCE_REFERENCE content type"""
    subtask = MagicMock()
    subtask.content_type = ContentType.SOURCE_REFERENCE
    subtask.audio_url = "audio/source.wav"
    
    task = MagicMock()
    task.sub_tasks = [subtask]

    wav_header = b"RIFF" + b"\x00" * 40
    raw_pcm = b"\x00\x01" * 30
    wav_data = wav_header + raw_pcm

    with patch("pecha_api.plans.cms.cms_plans_service.download_bytes", return_value=wav_data), \
         patch("pecha_api.plans.cms.cms_plans_service.get", return_value="test-bucket"):

        audio_segments, subtask_refs = await _generate_audio_segments(
            tasks=[task],
            audio_type=PlanAudioType.TEXT_READING,
            language="bo",
        )

        assert len(audio_segments) == 1
        assert len(subtask_refs) == 1


def test_build_combined_wav_produces_valid_header():
    """Test _build_combined_wav creates valid WAV file with correct header"""
    segment1 = b"\x00\x01" * 100
    segment2 = b"\x02\x03" * 150
    segment3 = b"\x04\x05" * 200

    combined_wav, data_size = _build_combined_wav([segment1, segment2, segment3])

    assert len(combined_wav) > 44
    assert combined_wav[:4] == b"RIFF"
    assert combined_wav[8:12] == b"WAVE"
    assert combined_wav[12:16] == b"fmt "
    assert combined_wav[36:40] == b"data"
    
    expected_data_size = len(segment1) + len(segment2) + len(segment3)
    assert data_size == expected_data_size
    assert len(combined_wav) == 44 + expected_data_size


def test_build_combined_wav_empty_segments():
    """Test _build_combined_wav handles empty segments list"""
    combined_wav, data_size = _build_combined_wav([])

    assert len(combined_wav) == 44
    assert data_size == 0
    assert combined_wav[:4] == b"RIFF"


def test_build_combined_wav_single_segment():
    """Test _build_combined_wav handles single segment"""
    segment = b"\x00\x01\x02\x03" * 50

    combined_wav, data_size = _build_combined_wav([segment])

    assert data_size == len(segment)
    assert len(combined_wav) == 44 + len(segment)
    assert combined_wav[44:] == segment


def test_update_subtask_timestamps_calculates_offsets():
    """Test _update_subtask_timestamps calculates correct timestamp offsets"""
    mock_db = MagicMock()
    
    subtask1 = MagicMock()
    subtask1.id = uuid.uuid4()
    subtask2 = MagicMock()
    subtask2.id = uuid.uuid4()
    subtask3 = MagicMock()
    subtask3.id = uuid.uuid4()

    segment1 = b"\x00\x01" * 24000
    segment2 = b"\x02\x03" * 48000
    segment3 = b"\x04\x05" * 12000

    with patch("pecha_api.plans.cms.cms_plans_service.upsert_sub_task_timestamp") as mock_upsert:
        total_duration = _update_subtask_timestamps(
            db=mock_db,
            audio_segments=[segment1, segment2, segment3],
            subtask_refs=[subtask1, subtask2, subtask3],
            sample_rate=24000,
            bytes_per_sample=2,
        )

        assert mock_upsert.call_count == 3
        
        call1 = mock_upsert.call_args_list[0]
        assert call1.kwargs["sub_task_id"] == subtask1.id
        assert call1.kwargs["start_ms"] == 0
        assert call1.kwargs["end_ms"] == 1000
        
        call2 = mock_upsert.call_args_list[1]
        assert call2.kwargs["sub_task_id"] == subtask2.id
        assert call2.kwargs["start_ms"] == 1000
        assert call2.kwargs["end_ms"] == 3000
        
        call3 = mock_upsert.call_args_list[2]
        assert call3.kwargs["sub_task_id"] == subtask3.id
        assert call3.kwargs["start_ms"] == 3000
        assert call3.kwargs["end_ms"] == 3500
        
        assert total_duration == 3500


def test_update_subtask_timestamps_empty_segments():
    """Test _update_subtask_timestamps handles empty segments"""
    mock_db = MagicMock()

    with patch("pecha_api.plans.cms.cms_plans_service.upsert_sub_task_timestamp") as mock_upsert:
        total_duration = _update_subtask_timestamps(
            db=mock_db,
            audio_segments=[],
            subtask_refs=[],
            sample_rate=24000,
            bytes_per_sample=2,
        )

        mock_upsert.assert_not_called()
        assert total_duration == 0


def test_upload_and_persist_audio_uploads_to_s3():
    """Test _upload_and_persist_audio uploads to S3 and persists to DB"""
    mock_db = MagicMock()
    plan_id = uuid.uuid4()
    plan_item_id = uuid.uuid4()
    combined_wav = b"RIFF" + b"\x00" * 100
    duration_ms = 5000

    mock_audio_row = MagicMock()
    mock_audio_row.audio_key = "audio/plan_days/test.wav"
    mock_audio_row.duration_ms = duration_ms

    with patch("pecha_api.plans.cms.cms_plans_service.upload_bytes") as mock_upload, \
         patch("pecha_api.plans.cms.cms_plans_service.upsert_plan_item_audio", return_value=mock_audio_row) as mock_upsert, \
         patch("pecha_api.plans.cms.cms_plans_service.get", return_value="test-bucket"):

        result = _upload_and_persist_audio(
            db=mock_db,
            combined_wav=combined_wav,
            duration_ms=duration_ms,
            plan_id=plan_id,
            plan_item_id=plan_item_id,
        )

        mock_upload.assert_called_once()
        upload_call = mock_upload.call_args
        assert upload_call.kwargs["bucket_name"] == "test-bucket"
        assert upload_call.kwargs["s3_key"].startswith(f"audio/plan_days/{plan_id}/{plan_item_id}/")
        assert upload_call.kwargs["s3_key"].endswith(".wav")
        assert upload_call.kwargs["content_type"] == "audio/wav"

        mock_upsert.assert_called_once()
        upsert_call = mock_upsert.call_args
        assert upsert_call.kwargs["db"] == mock_db
        audio_obj = upsert_call.kwargs["plan_item_audio"]
        assert audio_obj.plan_item_id == plan_item_id
        assert audio_obj.duration_ms == duration_ms
        assert audio_obj.mime_type == "audio/wav"
        assert audio_obj.file_size_bytes == len(combined_wav)
        assert audio_obj.created_by == "system"

        assert result == mock_audio_row

