import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette import status

from pecha_api.plans.plans_enums import DifficultyLevel, LanguageCode, PlanStatus
from pecha_api.plans.groups.groups_enums import AuthorGroupType
from pecha_api.plans.series.series_model import Series
from pecha_api.plans.series.series_service import (
    _validate_plan_ids,
    _build_plan_order_pairs,
    _series_schedule_from_plans,
    _plan_total_days,
    _active_plan_ids,
    _group_summary_for_series,
    compute_user_series_progress,
    get_language_filtered_series_plan_ids,
    create_new_series,
    get_filtered_series,
    get_random_featured_series,
    get_series_detail,
    update_existing_series,
    update_existing_series_status,
    update_existing_series_featured,
    get_cms_filtered_series,
    get_cms_series_detail,
    delete_existing_series,
    clone_series_plans_for_language,
)
from pecha_api.plans.platform_enums import PlatformRole

FIXTURE_GROUP_ID = uuid.uuid4()
_SERIES_FORBIDDEN = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
_MEMBER_GROUP_IDS = [FIXTURE_GROUP_ID]

from pecha_api.plans.groups.group_summary_models import AuthorGroupSummaryDTO
from pecha_api.plans.groups.groups_enums import AuthorGroupType
from pecha_api.plans.media.media_response_models import ImageUrlModel
from pecha_api.plans.series.series_response_models import (
    CreateSeriesRequest,
    UpdateSeriesRequest,
    SeriesListItemDTO,
    UpdateSeriesStatusRequest,
    SeriesListResponse,
    SeriesMetadataInput,
    CloneSeriesPlansRequest,
)


def _metadata_entry(title="Series A", language=LanguageCode.EN, description=None):
    entry = MagicMock()
    entry.id = uuid.uuid4()
    entry.title = title
    entry.description = description
    entry.language = language
    return entry


def _metadata_input(title="Series A", language=LanguageCode.EN, description=None):
    return SeriesMetadataInput(title=title, description=description, language=language)


def _session_local_context(mock_session_local):
    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db
    mock_session_local.return_value.__exit__.return_value = False
    return mock_db


def test_get_filtered_series_maps_rows_to_response():
    author_id = uuid.uuid4()
    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [_metadata_entry(title="Series A")]
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = True
    row.status = PlanStatus.DRAFT
    row.plans = None

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_paginated",
        return_value=([(row, 3, 0)], 1),
    ) as mock_repo, patch(
        "pecha_api.plans.series.series_service.get_series_plan_schedule_by_series_ids",
        return_value={},
    ):
        _session_local_context(mock_session_local)

        result = get_filtered_series(search=None, skip=2, limit=5)

    mock_repo.assert_called_once()
    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["search"] is None
    assert call_kwargs["skip"] == 2
    assert call_kwargs["limit"] == 5
    assert call_kwargs["include_deleted"] is False
    assert call_kwargs["order_by_field"] == Series.created_at
    assert call_kwargs["order_desc"] is True
    assert call_kwargs["status"] == PlanStatus.PUBLISHED
    assert call_kwargs["exclude_event_linked"] is True

    assert isinstance(result, SeriesListResponse)
    assert result.skip == 2
    assert result.limit == 5
    assert result.total == 1
    assert len(result.series) == 1
    dto = result.series[0]
    assert dto.id == row.id
    assert len(dto.metadata) == 1
    assert dto.metadata[0].title == "Series A"
    assert dto.metadata[0].language == "EN"
    assert dto.image is None
    assert dto.image_key is None
    assert dto.author_id == author_id
    assert dto.featured is True
    assert dto.status == PlanStatus.DRAFT
    assert dto.plan_count == 3
    assert isinstance(dto, SeriesListItemDTO)
    assert "plans" not in SeriesListItemDTO.model_fields


def test_get_filtered_series_presigns_image_when_key_present():
    from pecha_api.plans.media.media_response_models import ImageUrlModel

    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [_metadata_entry(title="With cover")]
    row.image = "images/series_images/sid/uuid/original/cover.jpg"
    row.author_id = uuid.uuid4()
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = MagicMock()
    row.status.value = PlanStatus.PUBLISHED.value
    image_model = ImageUrlModel(
        thumbnail="https://signed.example/thumb.jpg",
        medium="https://signed.example/medium.jpg",
        original="https://signed.example/original.jpg",
    )

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_paginated",
        return_value=([(row, 0, 0)], 1),
    ), patch(
        "pecha_api.plans.series.series_service.get_image_url",
        return_value=image_model,
    ) as mock_get_image:
        _session_local_context(mock_session_local)

        result = get_filtered_series(search=None, skip=0, limit=10)

    assert result.series[0].image == image_model
    assert result.series[0].image_key == row.image
    mock_get_image.assert_called_once_with(image_url=row.image)


def test_get_filtered_series_empty_repository():
    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_paginated",
        return_value=([], 0),
    ):
        _session_local_context(mock_session_local)

        result = get_filtered_series(search="nomatch", skip=0, limit=10)

    assert result.series == []
    assert result.total == 0


def test_create_new_series_persists_and_returns_dto():
    author_id = uuid.uuid4()
    request = CreateSeriesRequest(
        group_id=FIXTURE_GROUP_ID,
        metadata=[_metadata_input(title="New")],
        image_key="img/key.png",
        featured=True,
    )
    saved = MagicMock()
    saved.id = uuid.uuid4()
    saved.metadata_entries = [_metadata_entry(title="New")]
    saved.image = request.image_key
    saved.author_id = author_id
    saved.group_id = FIXTURE_GROUP_ID
    saved.featured = True
    saved.status = PlanStatus.DRAFT

    mock_author = MagicMock()
    mock_author.id = author_id

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.save_series_with_plans",
        return_value=saved,
    ) as mock_save, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=saved,
    ), patch(
        "pecha_api.plans.series.series_service.get_image_url",
        return_value=ImageUrlModel(
            thumbnail="https://signed/img-thumb.png",
            medium="https://signed/img-medium.png",
            original="https://signed/img.png",
        ),
    ), patch("pecha_api.plans.series.series_service.require_can_create_content"), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        _session_local_context(mock_session_local)

        dto = create_new_series(token="dummy", create_series_request=request)

    mock_save.assert_called_once()
    passed_series = mock_save.call_args.kwargs["series"]
    assert mock_save.call_args.kwargs["metadata_entries"] == request.metadata
    assert passed_series.image == request.image_key
    assert passed_series.author_id == author_id
    assert passed_series.featured is True

    assert dto.id == saved.id
    assert dto.metadata[0].title == "New"
    assert dto.image is not None
    assert dto.image.original == "https://signed/img.png"
    assert dto.image_key == request.image_key
    assert dto.featured is True
    assert dto.status == PlanStatus.DRAFT


def test_create_new_series_featured_defaults_when_none():
    author_id = uuid.uuid4()
    request = CreateSeriesRequest(
        group_id=FIXTURE_GROUP_ID,
        metadata=[_metadata_input(title="བོད་", language=LanguageCode.BO)],
        featured=None,
    )
    saved = MagicMock()
    saved.id = uuid.uuid4()
    saved.metadata_entries = [_metadata_entry(title="བོད་", language=LanguageCode.BO)]
    saved.image = None
    saved.author_id = author_id
    saved.group_id = FIXTURE_GROUP_ID
    saved.featured = False
    saved.status = PlanStatus.DRAFT

    mock_author = MagicMock()
    mock_author.id = author_id

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.save_series_with_plans",
        return_value=saved,
    ) as mock_save, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=saved,
    ), patch("pecha_api.plans.series.series_service.require_can_create_content"), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        _session_local_context(mock_session_local)

        create_new_series(token="dummy", create_series_request=request)

    passed_series = mock_save.call_args.kwargs["series"]
    assert passed_series.featured is False


def test_create_new_series_integrity_error_raises_400():
    author_id = uuid.uuid4()
    request = CreateSeriesRequest(
        group_id=FIXTURE_GROUP_ID,
        metadata=[_metadata_input(title="Test")],
    )
    orig = Exception("foreign key violation")

    mock_author = MagicMock()
    mock_author.id = author_id

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.save_series_with_plans",
        side_effect=IntegrityError("statement", {}, orig),
    ), patch("pecha_api.plans.series.series_service.require_can_create_content"), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            create_new_series(token="dummy", create_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Database integrity error" in exc.value.detail


def test_clone_series_routes_to_clone_path_and_returns_dto():
    author_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    target_group_id = uuid.uuid4()
    request = CreateSeriesRequest(
        group_id=target_group_id,
        parent_series_id=parent_id,
        featured=True,
    )

    parent = MagicMock()
    parent.id = parent_id
    parent.group_id = FIXTURE_GROUP_ID
    parent.image = "img/parent.png"
    parent.featured = True

    cloned = MagicMock()
    cloned.id = uuid.uuid4()
    cloned.metadata_entries = [_metadata_entry(title="Cloned")]
    cloned.image = "img/parent.png"
    cloned.author_id = author_id
    cloned.group_id = target_group_id
    cloned.parent_series_id = parent_id
    cloned.featured = True
    cloned.status = PlanStatus.DRAFT
    cloned.plans = []

    mock_author = MagicMock()
    mock_author.id = author_id
    mock_author.email = "cloner@example.com"

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_for_clone",
        return_value=parent,
    ), patch(
        "pecha_api.plans.series.series_service.clone_series_with_plans",
        return_value=cloned,
    ) as mock_clone, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=cloned,
    ), patch(
        "pecha_api.plans.series.series_service.get_enrolled_count_map_by_series_ids",
        return_value={},
    ), patch(
        "pecha_api.plans.series.series_service._group_summary_for_series",
        return_value=None,
    ), patch(
        "pecha_api.plans.series.series_service.get_image_url",
        return_value=None,
    ), patch("pecha_api.plans.series.series_service.require_can_read_group_content"), patch(
        "pecha_api.plans.series.series_service.require_can_create_content"
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        _session_local_context(mock_session_local)

        dto = create_new_series(token="dummy", create_series_request=request)

    mock_clone.assert_called_once()
    clone_kwargs = mock_clone.call_args.kwargs
    assert clone_kwargs["parent_series"] is parent
    assert clone_kwargs["target_group_id"] == target_group_id
    assert clone_kwargs["author_id"] == author_id
    assert clone_kwargs["image"] == "img/parent.png"
    assert clone_kwargs["featured"] is True

    assert dto.id == cloned.id
    assert dto.parent_series_id == parent_id
    assert dto.status == PlanStatus.DRAFT


def test_clone_series_raises_404_when_parent_missing():
    request = CreateSeriesRequest(
        group_id=uuid.uuid4(),
        parent_series_id=uuid.uuid4(),
    )
    mock_author = MagicMock()
    mock_author.id = uuid.uuid4()

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_for_clone",
        return_value=None,
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            create_new_series(token="dummy", create_series_request=request)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_clone_series_requires_read_on_parent_group():
    parent = MagicMock()
    parent.group_id = FIXTURE_GROUP_ID
    request = CreateSeriesRequest(
        group_id=uuid.uuid4(),
        parent_series_id=uuid.uuid4(),
    )
    mock_author = MagicMock()
    mock_author.id = uuid.uuid4()

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_for_clone",
        return_value=parent,
    ), patch(
        "pecha_api.plans.series.series_service.require_can_read_group_content",
        side_effect=_SERIES_FORBIDDEN,
    ), patch(
        "pecha_api.plans.series.series_service.clone_series_with_plans",
    ) as mock_clone, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            create_new_series(token="dummy", create_series_request=request)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_clone.assert_not_called()


def test_get_series_detail_raises_404_when_not_found():
    series_id = uuid.uuid4()
    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            get_series_detail(series_id=series_id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert str(series_id) in exc.value.detail


def test_get_series_detail_raises_404_when_not_published():
    series_id = uuid.uuid4()
    row = MagicMock()
    row.id = series_id
    row.status = PlanStatus.DRAFT

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            get_series_detail(series_id=series_id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_get_series_detail_returns_dto_without_plans():
    series_id = uuid.uuid4()
    row = MagicMock()
    row.id = series_id
    row.metadata_entries = [_metadata_entry(title="Only series")]
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.plans = []

    group_id = uuid.uuid4()
    group_summary = AuthorGroupSummaryDTO(
        id=group_id,
        slug="test-group",
        group_type=AuthorGroupType.PAGE,
        is_public=True,
        metadata=[],
    )
    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ), patch(
        "pecha_api.plans.series.series_service._group_summary_for_series",
        return_value=group_summary,
    ):
        _session_local_context(mock_session_local)

        dto = get_series_detail(series_id=series_id)

    assert dto.id == series_id
    assert dto.plans == []
    assert dto.group is not None
    assert dto.group.id == group_id


def test_get_series_detail_falls_back_to_en_metadata_when_language_missing():
    series_id = uuid.uuid4()
    row = MagicMock()
    row.id = series_id
    row.metadata_entries = [
        _metadata_entry(title="English only", language=LanguageCode.EN),
    ]
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.plans = []

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ), patch(
        "pecha_api.plans.series.series_service._group_summary_for_series",
        return_value=None,
    ):
        _session_local_context(mock_session_local)

        # Requesting 'bo' which the series does not have -> falls back to EN.
        dto = get_series_detail(series_id=series_id, language="bo")

    assert dto.metadata is not None
    assert dto.metadata.title == "English only"
    assert dto.metadata.language == "EN"


def test_get_series_detail_includes_active_plans_sorted_and_presigns_images():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    plan_b_id = uuid.uuid4()
    plan_a_id = uuid.uuid4()

    deleted_plan = MagicMock()
    deleted_plan.deleted_at = datetime.now(timezone.utc)
    deleted_plan.display_order = 0
    deleted_plan.group_id = FIXTURE_GROUP_ID

    plan_b = MagicMock()
    plan_b.deleted_at = None
    plan_b.display_order = 2
    plan_b.id = plan_b_id
    plan_b.title = "Second order"
    plan_b.description = None
    plan_b.language = LanguageCode.EN
    plan_b.difficulty_level = DifficultyLevel.BEGINNER
    plan_b.image_url = "plans/b.jpg"
    plan_b.tag_list = []
    plan_b.status = PlanStatus.PUBLISHED
    plan_b.featured = False
    plan_b.start_date = None
    plan_b.group_id = FIXTURE_GROUP_ID

    plan_a = MagicMock()
    plan_a.deleted_at = None
    plan_a.display_order = 1
    plan_a.id = plan_a_id
    plan_a.title = "First order"
    plan_a.description = "Desc"
    plan_a.language = LanguageCode.BO
    plan_a.difficulty_level = None
    plan_a.image_url = None
    plan_a.tag_list = None
    plan_a.status = MagicMock()
    plan_a.status.value = PlanStatus.PUBLISHED.value
    plan_a.featured = 1
    plan_a.start_date = None
    plan_a.group_id = FIXTURE_GROUP_ID

    row = MagicMock()
    row.id = series_id
    row.metadata_entries = [_metadata_entry(title="With plans")]
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = True
    row.status = PlanStatus.PUBLISHED
    row.plans = [deleted_plan, plan_b, plan_a]

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ), patch(
        "pecha_api.plans.series.series_service.safe_get_image_url",
        side_effect=lambda image_url, **kwargs: (
            ImageUrlModel(
                thumbnail="https://signed/b-thumb.jpg",
                medium="https://signed/b-medium.jpg",
                original="https://signed/b.jpg",
            )
            if image_url
            else None
        ),
    ) as mock_safe_image:
        _session_local_context(mock_session_local)

        dto = get_series_detail(series_id=series_id)

    assert len(dto.plans) == 2
    assert dto.plans[0].id == plan_a_id
    assert dto.plans[0].title == "First order"
    assert dto.plans[0].image is None
    assert dto.plans[0].image_key is None
    assert dto.plans[0].tags == []
    assert dto.plans[0].status == PlanStatus.PUBLISHED
    assert dto.plans[0].featured is True

    assert dto.plans[1].id == plan_b_id
    assert dto.plans[1].image is not None
    assert dto.plans[1].image.original == "https://signed/b.jpg"
    assert dto.plans[1].image_key == "plans/b.jpg"
    mock_safe_image.assert_any_call(
        "plans/b.jpg", resource_id=plan_b_id, resource_type="plan"
    )
    assert mock_safe_image.call_count == 2


def test_get_series_detail_includes_total_days_for_each_plan():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    item_1 = MagicMock()
    item_2 = MagicMock()
    item_3 = MagicMock()

    plan_a = MagicMock()
    plan_a.deleted_at = None
    plan_a.display_order = 1
    plan_a.id = uuid.uuid4()
    plan_a.title = "Plan A"
    plan_a.description = "First plan"
    plan_a.language = LanguageCode.EN
    plan_a.difficulty_level = DifficultyLevel.BEGINNER
    plan_a.image_url = None
    plan_a.tag_list = []
    plan_a.status = PlanStatus.PUBLISHED
    plan_a.featured = False
    plan_a.start_date = None
    plan_a.items = [item_1, item_2, item_3]
    plan_a.group_id = FIXTURE_GROUP_ID

    item_4 = MagicMock()
    item_5 = MagicMock()

    plan_b = MagicMock()
    plan_b.deleted_at = None
    plan_b.display_order = 2
    plan_b.id = uuid.uuid4()
    plan_b.title = "Plan B"
    plan_b.description = "Second plan"
    plan_b.language = LanguageCode.EN
    plan_b.difficulty_level = DifficultyLevel.INTERMEDIATE
    plan_b.image_url = None
    plan_b.tag_list = []
    plan_b.status = PlanStatus.PUBLISHED
    plan_b.featured = False
    plan_b.start_date = None
    plan_b.items = [item_4, item_5]
    plan_b.group_id = FIXTURE_GROUP_ID

    row = MagicMock()
    row.id = series_id
    row.metadata_entries = [_metadata_entry(title="Series with day counts")]
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.plans = [plan_a, plan_b]

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ):
        _session_local_context(mock_session_local)

        dto = get_series_detail(series_id=series_id)

    assert len(dto.plans) == 2
    assert dto.plans[0].total_days == 3
    assert dto.plans[1].total_days == 2
    assert dto.total_days == 5


def test_get_series_detail_total_days_zero_when_no_items():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    plan_empty = MagicMock()
    plan_empty.deleted_at = None
    plan_empty.display_order = 1
    plan_empty.id = uuid.uuid4()
    plan_empty.title = "Empty Plan"
    plan_empty.description = None
    plan_empty.language = LanguageCode.EN
    plan_empty.difficulty_level = DifficultyLevel.BEGINNER
    plan_empty.image_url = None
    plan_empty.tag_list = []
    plan_empty.status = PlanStatus.PUBLISHED
    plan_empty.featured = False
    plan_empty.start_date = None
    plan_empty.items = []
    plan_empty.group_id = FIXTURE_GROUP_ID

    row = MagicMock()
    row.id = series_id
    row.metadata_entries = [_metadata_entry(title="Series with empty plan")]
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.plans = [plan_empty]

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ):
        _session_local_context(mock_session_local)

        dto = get_series_detail(series_id=series_id)

    assert len(dto.plans) == 1
    assert dto.plans[0].total_days == 0
    assert dto.total_days == 0


def test_get_series_detail_total_days_zero_when_no_plans():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    row = MagicMock()
    row.id = series_id
    row.metadata_entries = [_metadata_entry(title="Series without plans")]
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.plans = []

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ):
        _session_local_context(mock_session_local)

        dto = get_series_detail(series_id=series_id)

    assert dto.plans == []
    assert dto.total_days == 0


def test_get_series_detail_handles_plan_without_items_attribute():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    plan_no_items = MagicMock(spec=["deleted_at", "display_order", "id", "title", "description", 
                                     "language", "difficulty_level", "image_url", "tag_list", 
                                     "status", "featured", "start_date", "group_id"])
    plan_no_items.deleted_at = None
    plan_no_items.display_order = 1
    plan_no_items.id = uuid.uuid4()
    plan_no_items.group_id = FIXTURE_GROUP_ID
    plan_no_items.title = "Plan without items"
    plan_no_items.description = None
    plan_no_items.language = LanguageCode.EN
    plan_no_items.difficulty_level = DifficultyLevel.BEGINNER
    plan_no_items.image_url = None
    plan_no_items.tag_list = []
    plan_no_items.status = PlanStatus.PUBLISHED
    plan_no_items.featured = False
    plan_no_items.start_date = None

    row = MagicMock()
    row.id = series_id
    row.metadata_entries = [_metadata_entry(title="Series with plan without items")]
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.plans = [plan_no_items]

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ):
        _session_local_context(mock_session_local)

        dto = get_series_detail(series_id=series_id)

    assert len(dto.plans) == 1
    assert dto.plans[0].total_days == 0
    assert dto.total_days == 0


def test_get_series_detail_excludes_non_published_plans():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    published_plan = MagicMock()
    published_plan.deleted_at = None
    published_plan.display_order = 1
    published_plan.id = uuid.uuid4()
    published_plan.title = "Published"
    published_plan.description = None
    published_plan.language = LanguageCode.EN
    published_plan.difficulty_level = DifficultyLevel.BEGINNER
    published_plan.image_url = None
    published_plan.tag_list = []
    published_plan.status = PlanStatus.PUBLISHED
    published_plan.featured = False
    published_plan.start_date = None
    published_plan.items = []
    published_plan.group_id = FIXTURE_GROUP_ID

    draft_plan = MagicMock()
    draft_plan.deleted_at = None
    draft_plan.display_order = 2
    draft_plan.id = uuid.uuid4()
    draft_plan.status = PlanStatus.DRAFT
    draft_plan.group_id = FIXTURE_GROUP_ID

    archived_plan = MagicMock()
    archived_plan.deleted_at = None
    archived_plan.display_order = 3
    archived_plan.id = uuid.uuid4()
    archived_plan.status = PlanStatus.ARCHIVED
    archived_plan.group_id = FIXTURE_GROUP_ID

    row = MagicMock()
    row.id = series_id
    row.metadata_entries = [_metadata_entry(title="Mixed statuses")]
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.plans = [published_plan, draft_plan, archived_plan]

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ):
        _session_local_context(mock_session_local)

        dto = get_series_detail(series_id=series_id)

    assert len(dto.plans) == 1
    assert dto.plans[0].id == published_plan.id
    assert dto.plans[0].status == PlanStatus.PUBLISHED


def test_get_series_detail_filters_plans_by_language():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    plan_en = MagicMock()
    plan_en.deleted_at = None
    plan_en.display_order = 0
    plan_en.id = uuid.uuid4()
    plan_en.title = "English plan"
    plan_en.description = None
    plan_en.language = LanguageCode.EN
    plan_en.difficulty_level = None
    plan_en.image_url = None
    plan_en.tag_list = []
    plan_en.status = PlanStatus.PUBLISHED
    plan_en.featured = False
    plan_en.start_date = None
    plan_en.items = []
    plan_en.group_id = FIXTURE_GROUP_ID

    plan_bo = MagicMock()
    plan_bo.deleted_at = None
    plan_bo.display_order = 1
    plan_bo.id = uuid.uuid4()
    plan_bo.title = "Tibetan plan"
    plan_bo.description = None
    plan_bo.language = LanguageCode.BO
    plan_bo.difficulty_level = None
    plan_bo.image_url = None
    plan_bo.tag_list = []
    plan_bo.status = PlanStatus.PUBLISHED
    plan_bo.featured = False
    plan_bo.start_date = None
    plan_bo.items = []
    plan_bo.group_id = FIXTURE_GROUP_ID

    row = MagicMock()
    row.id = series_id
    row.metadata_entries = []
    row.image = None
    row.author_id = author_id
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.group_id = FIXTURE_GROUP_ID
    row.plans = [plan_en, plan_bo]

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ):
        _session_local_context(mock_session_local)

        dto = get_series_detail(series_id=series_id, language="bo")

    assert len(dto.plans) == 1
    assert dto.plans[0].id == plan_bo.id
    assert dto.plans[0].language == "BO"


# ---------------------------------------------------------------------------
# Helpers shared by update_existing_series tests
# ---------------------------------------------------------------------------

def _make_existing_series(series_id, author_id, plans=None):
    series = MagicMock()
    series.id = series_id
    series.author_id = author_id
    series.group_id = FIXTURE_GROUP_ID
    series.status = PlanStatus.DRAFT
    series.plans = plans or []
    return series


def _make_refreshed_series(series_id, author_id):
    refreshed = MagicMock()
    refreshed.id = series_id
    refreshed.metadata_entries = [_metadata_entry(title="Updated")]
    refreshed.image = None
    refreshed.author_id = author_id
    refreshed.group_id = FIXTURE_GROUP_ID
    refreshed.featured = False
    refreshed.status = PlanStatus.DRAFT
    refreshed.plans = []
    return refreshed


def _make_mock_author(author_id, email="author@example.com", is_admin=False):
    author = MagicMock()
    author.id = author_id
    author.email = email
    author.platform_role = PlatformRole.SUPER_ADMIN if is_admin else PlatformRole.CREATOR
    author.is_active = True
    return author


# ---------------------------------------------------------------------------
# Group 1: Plans field behavior
# ---------------------------------------------------------------------------

def test_update_existing_series_plans_omitted_leaves_attachments_untouched():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    plan_a = MagicMock()
    plan_a.id = uuid.uuid4()
    plan_a.deleted_at = None
    plan_a.group_id = FIXTURE_GROUP_ID

    plan_b = MagicMock()
    plan_b.id = uuid.uuid4()
    plan_b.deleted_at = None
    plan_b.group_id = FIXTURE_GROUP_ID

    existing = _make_existing_series(series_id, author_id, plans=[plan_a, plan_b])
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(plans=None)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update, \
         patch("pecha_api.plans.series.series_service._validate_plan_ids") as mock_validate:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    mock_validate.assert_not_called()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["plans_to_attach"] == []
    assert call_kwargs["plan_ids_to_detach"] == []


def test_update_existing_series_plans_empty_dict_detaches_all():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    plan_a_id = uuid.uuid4()
    plan_b_id = uuid.uuid4()

    plan_a = MagicMock()
    plan_a.id = plan_a_id
    plan_a.deleted_at = None
    plan_a.group_id = FIXTURE_GROUP_ID

    plan_b = MagicMock()
    plan_b.id = plan_b_id
    plan_b.deleted_at = None
    plan_b.group_id = FIXTURE_GROUP_ID

    existing = _make_existing_series(series_id, author_id, plans=[plan_a, plan_b])
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(plans={})

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["plans_to_attach"] == []
    assert set(call_kwargs["plan_ids_to_detach"]) == {plan_a_id, plan_b_id}


def test_update_existing_series_full_replacement_with_diff():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    plan_a_id = uuid.uuid4()
    plan_b_id = uuid.uuid4()
    plan_c_id = uuid.uuid4()

    existing_plan_a = MagicMock()
    existing_plan_a.id = plan_a_id
    existing_plan_a.deleted_at = None
    existing_plan_a.group_id = FIXTURE_GROUP_ID

    existing_plan_b = MagicMock()
    existing_plan_b.id = plan_b_id
    existing_plan_b.deleted_at = None
    existing_plan_b.group_id = FIXTURE_GROUP_ID

    existing = _make_existing_series(series_id, author_id, plans=[existing_plan_a, existing_plan_b])
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    fetched_plan_a = MagicMock()
    fetched_plan_a.id = plan_a_id
    fetched_plan_a.deleted_at = None
    fetched_plan_a.series_id = series_id
    fetched_plan_a.author_id = author_id
    fetched_plan_a.group_id = FIXTURE_GROUP_ID

    fetched_plan_c = MagicMock()
    fetched_plan_c.id = plan_c_id
    fetched_plan_c.deleted_at = None
    fetched_plan_c.series_id = None
    fetched_plan_c.author_id = author_id
    fetched_plan_c.group_id = FIXTURE_GROUP_ID

    request = UpdateSeriesRequest(plans={"EN": [plan_a_id, plan_c_id]})

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[fetched_plan_a, fetched_plan_c]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    call_kwargs = mock_update.call_args.kwargs
    plans_to_attach = call_kwargs["plans_to_attach"]
    assert plans_to_attach == [(plan_a_id, 0), (plan_c_id, 1)]
    assert set(call_kwargs["plan_ids_to_detach"]) == {plan_b_id}


# ---------------------------------------------------------------------------
# Group 2: Field updates
# ---------------------------------------------------------------------------

def test_update_existing_series_updates_name_image_featured():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(
        metadata=[_metadata_input(title="New Name")],
        image_key="covers/new.jpg",
        featured=True,
    )

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["metadata_entries"] == request.metadata
    assert call_kwargs["image"] == "covers/new.jpg"
    assert call_kwargs["featured"] is True


def test_update_existing_series_sets_updated_at_and_updated_by():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id, email="user@pecha.org")

    request = UpdateSeriesRequest(metadata=[_metadata_input(title="Updated")])

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    call_kwargs = mock_update.call_args.kwargs
    assert isinstance(call_kwargs["updated_at"], datetime)
    assert call_kwargs["updated_at"].tzinfo is not None
    assert call_kwargs["updated_by"] == "user@pecha.org"


def test_update_existing_series_featured_not_modified_when_none():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    existing.featured = False
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(featured=None)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["featured"] is False


# ---------------------------------------------------------------------------
# Group 3: Authorization
# ---------------------------------------------------------------------------

def test_update_existing_series_returns_404_when_series_not_found():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(metadata=[_metadata_input(title="Updated")])

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=None), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    mock_update.assert_not_called()


def test_update_existing_series_returns_403_when_non_admin_other_author():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, other_author_id)
    mock_author = _make_mock_author(author_id, is_admin=False)

    request = UpdateSeriesRequest(metadata=[_metadata_input(title="Updated")])

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.require_can_edit_content", side_effect=_SERIES_FORBIDDEN), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_update.assert_not_called()


def test_update_existing_series_admin_can_edit_other_author_series():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, other_author_id)
    refreshed = _make_refreshed_series(series_id, other_author_id)
    mock_author = _make_mock_author(author_id, is_admin=True)

    request = UpdateSeriesRequest(metadata=[_metadata_input(title="Admin edit")])

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    mock_update.assert_called_once()


# ---------------------------------------------------------------------------
# Group 4: Plan validation
# ---------------------------------------------------------------------------

def test_update_existing_series_400_when_plan_does_not_exist():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    missing_plan_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(plans={"EN": [missing_plan_id]})

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not exist" in exc.value.detail
    mock_update.assert_not_called()


def test_update_existing_series_400_when_plan_attached_to_different_series():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    other_series_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    conflicting_plan = MagicMock()
    conflicting_plan.id = plan_id
    conflicting_plan.deleted_at = None
    conflicting_plan.series_id = other_series_id
    conflicting_plan.author_id = author_id
    conflicting_plan.group_id = FIXTURE_GROUP_ID

    request = UpdateSeriesRequest(plans={"EN": [plan_id]})

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[conflicting_plan]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "already attached to another series" in exc.value.detail
    mock_update.assert_not_called()


def test_update_existing_series_allows_plan_already_attached_to_current_series():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    plan_id = uuid.uuid4()

    existing_plan = MagicMock()
    existing_plan.id = plan_id
    existing_plan.deleted_at = None
    existing_plan.group_id = FIXTURE_GROUP_ID

    existing = _make_existing_series(series_id, author_id, plans=[existing_plan])
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    fetched_plan = MagicMock()
    fetched_plan.id = plan_id
    fetched_plan.deleted_at = None
    fetched_plan.series_id = series_id
    fetched_plan.author_id = author_id
    fetched_plan.group_id = FIXTURE_GROUP_ID

    request = UpdateSeriesRequest(plans={"EN": [plan_id]})

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[fetched_plan]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    mock_update.assert_called_once()


def test_update_existing_series_403_when_non_admin_plan_belongs_to_other_author():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    other_group_id = uuid.uuid4()
    plan_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    mock_author = _make_mock_author(author_id, is_admin=False)

    other_group_plan = MagicMock()
    other_group_plan.id = plan_id
    other_group_plan.deleted_at = None
    other_group_plan.series_id = None
    other_group_plan.author_id = uuid.uuid4()
    other_group_plan.group_id = other_group_id

    request = UpdateSeriesRequest(plans={"EN": [plan_id]})

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[other_group_plan]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "same group" in exc.value.detail
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# Group 5: Partial-update (UpdateSeriesRequest) field semantics
# ---------------------------------------------------------------------------

def test_update_existing_series_omitting_featured_keeps_existing_value():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    existing = _make_existing_series(series_id, author_id)
    existing.featured = True
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(metadata=[_metadata_input(title="Renamed only")])

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert existing.featured is True
    assert mock_update.call_args.kwargs["featured"] is True


def test_update_existing_series_omitting_image_key_keeps_existing_image():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    existing = _make_existing_series(series_id, author_id)
    existing.image = "series/covers/original.jpg"
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(featured=True)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert existing.image == "series/covers/original.jpg"
    assert mock_update.call_args.kwargs["image"] == "series/covers/original.jpg"


def test_update_existing_series_omitting_all_fields_is_noop_on_scalars():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    existing = _make_existing_series(series_id, author_id)
    existing.metadata_entries = [_metadata_entry(title="Original")]
    existing.image = "series/covers/original.jpg"
    existing.featured = False
    original_metadata = list(existing.metadata_entries)
    original_image = existing.image
    original_featured = existing.featured
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest()

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert existing.metadata_entries == original_metadata
    assert existing.image == original_image
    assert existing.featured == original_featured
    mock_update.assert_called_once()


# ---------------------------------------------------------------------------
# Group 6: Additional coverage tests
# ---------------------------------------------------------------------------

def test_update_existing_series_integrity_error_raises_400():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    orig = Exception("foreign key violation")

    existing = _make_existing_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesRequest(metadata=[_metadata_input(title="Updated")])

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans",
               side_effect=IntegrityError("statement", {}, orig)):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Database integrity error" in exc.value.detail


def test_create_new_series_with_plans_attaches_and_returns_dto():
    author_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    series_id = uuid.uuid4()

    request = CreateSeriesRequest(
        group_id=FIXTURE_GROUP_ID,
        metadata=[_metadata_input(title="Series with plan")],
        plans={"EN": [plan_id]},
    )

    mock_author = _make_mock_author(author_id)

    valid_plan = MagicMock()
    valid_plan.id = plan_id
    valid_plan.deleted_at = None
    valid_plan.series_id = None
    valid_plan.author_id = author_id
    valid_plan.status = PlanStatus.DRAFT
    valid_plan.title = "Test Plan"
    valid_plan.description = None
    valid_plan.language = LanguageCode.EN
    valid_plan.difficulty_level = DifficultyLevel.BEGINNER
    valid_plan.image_url = None
    valid_plan.tag_list = []
    valid_plan.items = []
    valid_plan.featured = False
    valid_plan.display_order = None
    valid_plan.start_date = None
    valid_plan.group_id = FIXTURE_GROUP_ID

    saved = MagicMock()
    saved.id = series_id
    saved.metadata_entries = [_metadata_entry(title="Series with plan")]
    saved.image = None
    saved.author_id = author_id
    saved.group_id = FIXTURE_GROUP_ID
    saved.featured = False
    saved.status = PlanStatus.DRAFT

    refreshed = MagicMock()
    refreshed.id = series_id
    refreshed.metadata_entries = [_metadata_entry(title="Series with plan")]
    refreshed.image = None
    refreshed.author_id = author_id
    refreshed.group_id = FIXTURE_GROUP_ID
    refreshed.featured = False
    refreshed.status = PlanStatus.DRAFT
    refreshed.plans = [valid_plan]

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[valid_plan]), \
         patch("pecha_api.plans.series.series_service.save_series_with_plans", return_value=saved) as mock_save, \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=refreshed):
        _session_local_context(mock_session_local)
        dto = create_new_series(token="dummy", create_series_request=request)

    mock_save.assert_called_once()
    assert mock_save.call_args.kwargs["plans_to_attach"] == [(plan_id, 0)]
    assert dto.id == series_id


def test_create_new_series_rejects_soft_deleted_plan():
    author_id = uuid.uuid4()
    plan_id = uuid.uuid4()

    request = CreateSeriesRequest(
        group_id=FIXTURE_GROUP_ID,
        metadata=[_metadata_input(title="Series")],
        plans={"EN": [plan_id]},
    )

    mock_author = _make_mock_author(author_id)

    deleted_plan = MagicMock()
    deleted_plan.id = plan_id
    deleted_plan.deleted_at = datetime.now(timezone.utc)
    deleted_plan.series_id = None
    deleted_plan.author_id = author_id
    deleted_plan.group_id = FIXTURE_GROUP_ID

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[deleted_plan]), \
         patch("pecha_api.plans.series.series_service.save_series_with_plans") as mock_save:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            create_new_series(token="dummy", create_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not exist" in exc.value.detail
    mock_save.assert_not_called()


def test_create_new_series_rejects_plan_already_attached_to_another_series():
    author_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    other_series_id = uuid.uuid4()

    request = CreateSeriesRequest(
        group_id=FIXTURE_GROUP_ID,
        metadata=[_metadata_input(title="Series")],
        plans={"EN": [plan_id]},
    )

    mock_author = _make_mock_author(author_id)

    attached_plan = MagicMock()
    attached_plan.id = plan_id
    attached_plan.deleted_at = None
    attached_plan.series_id = other_series_id
    attached_plan.author_id = author_id
    attached_plan.group_id = FIXTURE_GROUP_ID

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[attached_plan]), \
         patch("pecha_api.plans.series.series_service.save_series_with_plans") as mock_save:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            create_new_series(token="dummy", create_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "already attached to another series" in exc.value.detail
    mock_save.assert_not_called()


def test_create_new_series_rejects_plan_belonging_to_other_author_non_admin():
    author_id = uuid.uuid4()
    other_group_id = uuid.uuid4()
    plan_id = uuid.uuid4()

    request = CreateSeriesRequest(
        group_id=FIXTURE_GROUP_ID,
        metadata=[_metadata_input(title="Series")],
        plans={"EN": [plan_id]},
    )

    mock_author = _make_mock_author(author_id, is_admin=False)

    other_group_plan = MagicMock()
    other_group_plan.id = plan_id
    other_group_plan.deleted_at = None
    other_group_plan.series_id = None
    other_group_plan.author_id = uuid.uuid4()
    other_group_plan.group_id = other_group_id

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[other_group_plan]), \
         patch("pecha_api.plans.series.series_service.save_series_with_plans") as mock_save:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            create_new_series(token="dummy", create_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "same group" in exc.value.detail
    mock_save.assert_not_called()


def test_validate_plan_ids_dedupes_before_fetching():
    author_id = uuid.uuid4()
    plan_id = uuid.uuid4()

    request = CreateSeriesRequest(
        group_id=FIXTURE_GROUP_ID,
        metadata=[_metadata_input(title="Series")],
        plans={"EN": [plan_id], "BO": [plan_id]},
    )

    mock_author = _make_mock_author(author_id)

    valid_plan = MagicMock()
    valid_plan.id = plan_id
    valid_plan.deleted_at = None
    valid_plan.series_id = None
    valid_plan.author_id = author_id
    valid_plan.status = PlanStatus.DRAFT
    valid_plan.title = "Test Plan"
    valid_plan.description = None
    valid_plan.language = LanguageCode.EN
    valid_plan.difficulty_level = DifficultyLevel.BEGINNER
    valid_plan.image_url = None
    valid_plan.tag_list = []
    valid_plan.items = []
    valid_plan.featured = False
    valid_plan.display_order = None
    valid_plan.start_date = None
    valid_plan.group_id = FIXTURE_GROUP_ID

    saved = MagicMock()
    saved.id = uuid.uuid4()
    saved.metadata_entries = [_metadata_entry(title="Series")]
    saved.image = None
    saved.author_id = author_id
    saved.group_id = FIXTURE_GROUP_ID
    saved.featured = False
    saved.status = PlanStatus.DRAFT

    refreshed = MagicMock()
    refreshed.id = saved.id
    refreshed.metadata_entries = [_metadata_entry(title="Series")]
    refreshed.image = None
    refreshed.author_id = author_id
    refreshed.group_id = FIXTURE_GROUP_ID
    refreshed.featured = False
    refreshed.status = PlanStatus.DRAFT
    refreshed.plans = [valid_plan]

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[valid_plan]) as mock_get_plans, \
         patch("pecha_api.plans.series.series_service.save_series_with_plans", return_value=saved), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=refreshed):
        _session_local_context(mock_session_local)
        create_new_series(token="dummy", create_series_request=request)

    mock_get_plans.assert_called_once()
    fetched_ids = mock_get_plans.call_args.kwargs["plan_ids"]
    assert fetched_ids.count(plan_id) == 1


# ---------------------------------------------------------------------------
# CMS GET endpoints — get_cms_filtered_series
# ---------------------------------------------------------------------------

def test_get_cms_filtered_series_scopes_to_current_author_when_not_admin():
    author_id = uuid.uuid4()
    row = MagicMock()
    row.id = uuid.uuid4()
    row.name = {"en": "Mine"}
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.DRAFT
    row.plans = None

    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_author_group_ids", return_value=_MEMBER_GROUP_IDS), \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([(row, 2, 0)], 1)) as mock_repo:
        _session_local_context(mock_session_local)

        result = get_cms_filtered_series(token="dummy", search=None, skip=0, limit=10)

    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["author_id"] is None
    assert call_kwargs["group_ids"] == _MEMBER_GROUP_IDS
    assert call_kwargs["search"] is None
    assert call_kwargs["skip"] == 0
    assert call_kwargs["limit"] == 10
    assert call_kwargs["order_by_field"] == Series.created_at
    assert call_kwargs["order_desc"] is True

    assert isinstance(result, SeriesListResponse)
    assert result.total == 1
    assert len(result.series) == 1
    assert result.series[0].plan_count == 2


def test_get_cms_filtered_series_admin_sees_all_authors():
    admin_id = uuid.uuid4()
    row = MagicMock()
    row.id = uuid.uuid4()
    row.name = {"en": "Someone else's"}
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.DRAFT
    row.plans = None

    mock_admin = _make_mock_author(admin_id, is_admin=True)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_admin), \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([(row, 0, 0)], 1)) as mock_repo:
        _session_local_context(mock_session_local)

        get_cms_filtered_series(token="dummy", search=None, skip=0, limit=10)

    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["author_id"] is None


def test_get_cms_filtered_series_passes_search_and_pagination():
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_author_group_ids", return_value=_MEMBER_GROUP_IDS), \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([], 0)) as mock_repo:
        _session_local_context(mock_session_local)

        get_cms_filtered_series(token="dummy", search="meditation", skip=5, limit=20)

    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["search"] == "meditation"
    assert call_kwargs["skip"] == 5
    assert call_kwargs["limit"] == 20
    assert call_kwargs["author_id"] is None
    assert call_kwargs["group_ids"] == _MEMBER_GROUP_IDS


def test_get_filtered_series_passes_language_to_repository():
    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([], 0)) as mock_repo:
        _session_local_context(mock_session_local)

        get_filtered_series(search=None, skip=0, limit=10, language="zh")

    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["language"] == "zh"
    assert call_kwargs["status"] == PlanStatus.PUBLISHED
    # Public listing must opt into fallback so untranslated series still appear.
    assert call_kwargs["language_fallback"] is True


def test_get_cms_filtered_series_keeps_strict_language_filter():
    """CMS browsing stays strict: authors filter series by actual translation."""
    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details") as mock_author, \
         patch("pecha_api.plans.series.series_service.is_super_admin", return_value=True), \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([], 0)) as mock_repo:
        _session_local_context(mock_session_local)
        mock_author.return_value = MagicMock(id=uuid.uuid4())

        get_cms_filtered_series(token="dummy", search=None, skip=0, limit=10, language="ne")

    assert mock_repo.call_args.kwargs.get("language_fallback") in (None, False)


def test_get_random_featured_series_defaults_to_english_when_language_not_provided():
    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [
        _metadata_entry(title="Featured", language=LanguageCode.EN),
        _metadata_entry(title="བོད་", language=LanguageCode.BO),
    ]
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = None
    row.featured = True
    row.status = PlanStatus.PUBLISHED

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.get_random_featured_published_series",
               return_value=([(row, 4, 2)], 1)) as mock_repo, \
         patch("pecha_api.plans.series.series_service._group_summaries_for_series_rows",
               return_value={}):
        _session_local_context(mock_session_local)

        result = get_random_featured_series(limit=10)

    assert mock_repo.call_args.kwargs["limit"] == 10
    assert len(result.series) == 1
    assert result.total == 1
    assert result.series[0].featured is True
    assert result.series[0].plan_count == 4
    assert result.series[0].enrolled_count == 2
    assert result.series[0].metadata.title == "Featured"
    assert result.series[0].metadata.language == "EN"


def test_get_random_featured_series_passes_limit_to_repository():
    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.get_random_featured_published_series",
               return_value=([], 0)) as mock_repo:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc_info:
            get_random_featured_series(language="bo", limit=10)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["limit"] == 10


def test_get_random_featured_series_falls_back_to_en_metadata_when_requested_language_missing():
    row_with_bo = MagicMock()
    row_with_bo.id = uuid.uuid4()
    row_with_bo.metadata_entries = [_metadata_entry(title="བོད་", language=LanguageCode.BO)]
    row_with_bo.image = None
    row_with_bo.author_id = uuid.uuid4()
    row_with_bo.group_id = None
    row_with_bo.featured = True
    row_with_bo.status = PlanStatus.PUBLISHED

    row_en_only = MagicMock()
    row_en_only.id = uuid.uuid4()
    row_en_only.metadata_entries = [_metadata_entry(title="English only", language=LanguageCode.EN)]
    row_en_only.image = None
    row_en_only.author_id = uuid.uuid4()
    row_en_only.group_id = None
    row_en_only.featured = True
    row_en_only.status = PlanStatus.PUBLISHED

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.get_random_featured_published_series",
               return_value=([(row_with_bo, 2, 0), (row_en_only, 1, 0)], 2)), \
         patch("pecha_api.plans.series.series_service._group_summaries_for_series_rows",
               return_value={}):
        _session_local_context(mock_session_local)

        result = get_random_featured_series(language="bo", limit=10)

    assert len(result.series) == 2
    assert result.series[0].id == row_with_bo.id
    assert result.series[0].metadata.title == "བོད་"
    assert result.series[0].metadata.language == "BO"
    assert result.series[1].id == row_en_only.id
    assert result.series[1].metadata.title == "English only"
    assert result.series[1].metadata.language == "EN"


def test_get_random_featured_series_returns_404_when_no_metadata_available():
    row_no_metadata = MagicMock()
    row_no_metadata.id = uuid.uuid4()
    row_no_metadata.metadata_entries = []
    row_no_metadata.image = None
    row_no_metadata.author_id = uuid.uuid4()
    row_no_metadata.group_id = None
    row_no_metadata.featured = True
    row_no_metadata.status = PlanStatus.PUBLISHED

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.get_random_featured_published_series",
               return_value=([(row_no_metadata, 1, 0)], 1)), \
         patch("pecha_api.plans.series.series_service._group_summaries_for_series_rows",
               return_value={}):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc_info:
            get_random_featured_series(language="bo", limit=10)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def _featured_series_plan(
    *,
    display_order,
    start_date=None,
    item_count=0,
    language=LanguageCode.EN,
    status=PlanStatus.PUBLISHED,
):
    plan = MagicMock()
    plan.deleted_at = None
    plan.display_order = display_order
    plan.start_date = start_date
    plan.status = status
    plan.language = language
    plan.items = [MagicMock() for _ in range(item_count)]
    return plan


def _schedule_rows_for_series(series_id, *plans):
    from pecha_api.plans.series.series_repository import SeriesPlanScheduleRow

    return {
        series_id: [
            SeriesPlanScheduleRow(
                series_id=series_id,
                status=plan.status,
                language=plan.language,
                display_order=plan.display_order,
                start_date=plan.start_date,
                deleted_at=plan.deleted_at,
                total_days=len(plan.items or []),
            )
            for plan in plans
        ]
    }


def test_get_random_featured_series_includes_schedule_from_first_plan():
    series_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [_metadata_entry(title="Featured", language=LanguageCode.EN)]
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = None
    row.featured = True
    row.status = PlanStatus.PUBLISHED

    first_plan = _featured_series_plan(
        display_order=0,
        start_date=series_start,
        item_count=3,
    )
    second_plan = _featured_series_plan(
        display_order=1,
        start_date=datetime(2026, 6, 10, tzinfo=timezone.utc),
        item_count=2,
    )
    series_with_plans = _schedule_rows_for_series(row.id, second_plan, first_plan)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.get_random_featured_published_series",
               return_value=([(row, 2, 0)], 1)), \
         patch("pecha_api.plans.series.series_service.get_series_plan_schedule_by_series_ids",
               return_value=series_with_plans), \
         patch("pecha_api.plans.series.series_service._group_summaries_for_series_rows",
               return_value={}):
        _session_local_context(mock_session_local)

        result = get_random_featured_series(limit=10)

    assert result.series[0].start_date == series_start
    assert result.series[0].total_days == 5
    assert result.series[0].end_date == datetime(2026, 6, 11, tzinfo=timezone.utc)


def test_get_random_featured_series_omits_schedule_when_first_plan_has_no_start_date():
    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [_metadata_entry(title="Featured", language=LanguageCode.EN)]
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = None
    row.featured = True
    row.status = PlanStatus.PUBLISHED

    first_plan = _featured_series_plan(display_order=0, start_date=None, item_count=2)
    second_plan = _featured_series_plan(
        display_order=1,
        start_date=datetime(2026, 6, 10, tzinfo=timezone.utc),
        item_count=3,
    )
    series_with_plans = _schedule_rows_for_series(row.id, first_plan, second_plan)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.get_random_featured_published_series",
               return_value=([(row, 2, 0)], 1)), \
         patch("pecha_api.plans.series.series_service.get_series_plan_schedule_by_series_ids",
               return_value=series_with_plans), \
         patch("pecha_api.plans.series.series_service._group_summaries_for_series_rows",
               return_value={}):
        _session_local_context(mock_session_local)

        result = get_random_featured_series(limit=10)

    assert result.series[0].start_date is None
    assert result.series[0].end_date is None
    assert result.series[0].total_days == 5


def test_series_schedule_from_plans_uses_total_days_on_schedule_rows():
    from pecha_api.plans.series.series_repository import SeriesPlanScheduleRow

    series_id = uuid.uuid4()
    series_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    schedule_rows = [
        SeriesPlanScheduleRow(
            series_id=series_id,
            status=PlanStatus.PUBLISHED,
            language=LanguageCode.EN,
            display_order=0,
            start_date=series_start,
            deleted_at=None,
            total_days=4,
        )
    ]

    start_date, end_date, total_days = _series_schedule_from_plans(
        schedule_rows,
        published_only=True,
    )

    assert start_date == series_start
    assert end_date == series_start + timedelta(days=3)
    assert total_days == 4


def test_series_schedule_from_plans_returns_empty_when_no_plans():
    start_date, end_date, total_days = _series_schedule_from_plans([], published_only=True)

    assert start_date is None
    assert end_date is None
    assert total_days == 0


def test_series_schedule_from_plans_uses_start_date_when_series_has_no_days():
    series_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    plan = _featured_series_plan(display_order=0, start_date=series_start, item_count=0)

    start_date, end_date, total_days = _series_schedule_from_plans(
        [plan],
        published_only=True,
    )

    assert start_date == series_start
    assert end_date == series_start
    assert total_days == 0


def test_series_schedule_from_plans_excludes_unpublished_plans():
    series_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    draft_plan = _featured_series_plan(
        display_order=0,
        start_date=series_start,
        item_count=2,
        status=PlanStatus.DRAFT,
    )

    start_date, end_date, total_days = _series_schedule_from_plans(
        [draft_plan],
        published_only=True,
    )

    assert start_date is None
    assert end_date is None
    assert total_days == 0


def test_series_schedule_from_plans_end_date_from_last_published_plan():
    series_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    first_plan = _featured_series_plan(
        display_order=0,
        start_date=series_start,
        item_count=3,
    )
    last_plan = _featured_series_plan(
        display_order=1,
        start_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
        item_count=2,
    )

    start_date, end_date, total_days = _series_schedule_from_plans(
        [first_plan, last_plan],
        published_only=True,
    )

    assert start_date == series_start
    assert total_days == 5
    assert end_date == datetime(2026, 7, 11, tzinfo=timezone.utc)


def test_series_schedule_from_plans_uses_first_published_plan_when_earlier_plans_are_drafts():
    draft_plan = _featured_series_plan(
        display_order=0,
        start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        item_count=5,
        status=PlanStatus.DRAFT,
    )
    published_plan = _featured_series_plan(
        display_order=1,
        start_date=datetime(2026, 7, 15, tzinfo=timezone.utc),
        item_count=2,
    )

    start_date, end_date, total_days = _series_schedule_from_plans(
        [draft_plan, published_plan],
        published_only=True,
    )

    assert start_date == datetime(2026, 7, 15, tzinfo=timezone.utc)
    assert end_date == datetime(2026, 7, 16, tzinfo=timezone.utc)
    assert total_days == 2


def test_series_schedule_from_plans_filters_by_language():
    series_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    en_plan = _featured_series_plan(
        display_order=0,
        start_date=series_start,
        item_count=2,
        language=LanguageCode.EN,
    )
    bo_plan = _featured_series_plan(
        display_order=1,
        start_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
        item_count=5,
        language=LanguageCode.BO,
    )

    start_date, end_date, total_days = _series_schedule_from_plans(
        [en_plan, bo_plan],
        published_only=True,
        language="bo",
    )

    assert start_date == datetime(2026, 7, 10, tzinfo=timezone.utc)
    assert total_days == 5
    assert end_date == datetime(2026, 7, 14, tzinfo=timezone.utc)


def test_compute_user_series_progress_uses_completed_day_count_for_language():
    series_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    en_plan = _featured_series_plan(
        display_order=0,
        start_date=series_start,
        item_count=3,
        language=LanguageCode.EN,
    )
    bo_plan = _featured_series_plan(
        display_order=1,
        start_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
        item_count=5,
        language=LanguageCode.BO,
    )

    progress = compute_user_series_progress(
        plans=[en_plan, bo_plan],
        language="en",
        completed_day_count=2,
    )

    assert progress.total_day_count == 3
    assert progress.current_day_number == 2


def test_compute_user_series_progress_caps_completed_at_total_days():
    plan = _featured_series_plan(
        display_order=0,
        start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        item_count=4,
        language=LanguageCode.EN,
    )

    progress = compute_user_series_progress(
        plans=[plan],
        language="en",
        completed_day_count=9,
    )

    assert progress.total_day_count == 4
    assert progress.current_day_number == 4


def test_compute_user_series_progress_returns_none_when_no_start_date():
    plan = _featured_series_plan(
        display_order=0,
        start_date=None,
        item_count=4,
        language=LanguageCode.EN,
    )

    progress = compute_user_series_progress(
        plans=[plan],
        language="en",
        completed_day_count=0,
    )

    assert progress.total_day_count == 4
    assert progress.current_day_number is None


def test_compute_user_series_progress_returns_none_for_upcoming_series():
    future_start = datetime(2099, 1, 1, tzinfo=timezone.utc)
    plan = _featured_series_plan(
        display_order=0,
        start_date=future_start,
        item_count=4,
        language=LanguageCode.EN,
    )

    progress = compute_user_series_progress(
        plans=[plan],
        language="en",
        completed_day_count=0,
        reference_date=datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
    )

    assert progress.total_day_count == 4
    assert progress.current_day_number is None


def test_compute_user_series_progress_returns_zero_when_series_started_but_no_completions():
    past_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    plan = _featured_series_plan(
        display_order=0,
        start_date=past_start,
        item_count=4,
        language=LanguageCode.EN,
    )

    progress = compute_user_series_progress(
        plans=[plan],
        language="en",
        completed_day_count=0,
        reference_date=datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
    )

    assert progress.total_day_count == 4
    assert progress.current_day_number == 0


def test_compute_user_series_progress_returns_none_when_total_days_zero():
    progress = compute_user_series_progress(
        plans=[],
        language="en",
        completed_day_count=0,
    )

    assert progress.total_day_count == 0
    assert progress.current_day_number is None


def test_get_language_filtered_series_plan_ids_respects_language_fallback():
    en_plan = _featured_series_plan(
        display_order=0,
        start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        item_count=2,
        language=LanguageCode.EN,
    )
    bo_plan = _featured_series_plan(
        display_order=1,
        start_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
        item_count=5,
        language=LanguageCode.BO,
    )

    plan_ids = get_language_filtered_series_plan_ids(
        [en_plan, bo_plan],
        language="bo",
    )

    assert plan_ids == [bo_plan.id]


def test_plan_total_days_returns_zero_when_plan_has_no_items():
    plan = MagicMock()
    plan.items = None

    assert _plan_total_days(plan) == 0


def test_get_random_featured_series_schedule_respects_language_filter():
    series_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [_metadata_entry(title="བོད་", language=LanguageCode.BO)]
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = None
    row.featured = True
    row.status = PlanStatus.PUBLISHED

    en_plan = _featured_series_plan(
        display_order=0,
        start_date=series_start,
        item_count=4,
        language=LanguageCode.EN,
    )
    bo_plan = _featured_series_plan(
        display_order=1,
        start_date=datetime(2026, 6, 15, tzinfo=timezone.utc),
        item_count=2,
        language=LanguageCode.BO,
    )
    series_with_plans = _schedule_rows_for_series(row.id, en_plan, bo_plan)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.get_random_featured_published_series",
               return_value=([(row, 2, 0)], 1)), \
         patch("pecha_api.plans.series.series_service.get_series_plan_schedule_by_series_ids",
               return_value=series_with_plans), \
         patch("pecha_api.plans.series.series_service._group_summaries_for_series_rows",
               return_value={}):
        _session_local_context(mock_session_local)

        result = get_random_featured_series(language="bo", limit=10)

    assert result.series[0].start_date == datetime(2026, 6, 15, tzinfo=timezone.utc)
    assert result.series[0].total_days == 2
    assert result.series[0].end_date == datetime(2026, 6, 16, tzinfo=timezone.utc)


def test_get_cms_filtered_series_passes_language_to_repository():
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_author_group_ids", return_value=_MEMBER_GROUP_IDS), \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([], 0)) as mock_repo:
        _session_local_context(mock_session_local)

        get_cms_filtered_series(token="dummy", search=None, skip=0, limit=10, language="en")

    assert mock_repo.call_args.kwargs["language"] == "en"


def test_get_cms_filtered_series_admin_passes_status_featured_and_author_filters():
    admin_id = uuid.uuid4()
    filter_author_id = uuid.uuid4()
    mock_admin = _make_mock_author(admin_id, is_admin=True)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_admin), \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([], 0)) as mock_repo:
        _session_local_context(mock_session_local)

        get_cms_filtered_series(
            token="dummy",
            search=None,
            skip=0,
            limit=10,
            plan_status=PlanStatus.DRAFT,
            featured=False,
            filter_author_id=filter_author_id,
        )

    call_kwargs = mock_repo.call_args.kwargs
    assert call_kwargs["author_id"] == filter_author_id
    assert call_kwargs["status"] == PlanStatus.DRAFT
    assert call_kwargs["featured"] is False


def test_get_cms_filtered_series_non_admin_cannot_filter_by_other_author():
    author_id = uuid.uuid4()
    other_author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_author_group_ids", return_value=_MEMBER_GROUP_IDS), \
         patch("pecha_api.plans.series.series_service.get_series_paginated", return_value=([], 0)) as mock_repo:
        _session_local_context(mock_session_local)
        get_cms_filtered_series(
            token="dummy",
            search=None,
            skip=0,
            limit=10,
            filter_author_id=other_author_id,
        )

    assert mock_repo.call_args.kwargs["author_id"] is None
    assert mock_repo.call_args.kwargs["group_ids"] == _MEMBER_GROUP_IDS


# ---------------------------------------------------------------------------
# CMS GET endpoints — get_cms_series_detail
# ---------------------------------------------------------------------------

def test_get_cms_series_detail_returns_dto_when_owner():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    row = MagicMock()
    row.id = series_id
    row.name = {"en": "Mine"}
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.DRAFT
    row.plans = []

    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=row):
        _session_local_context(mock_session_local)

        dto = get_cms_series_detail(token="dummy", series_id=series_id)

    assert dto.id == series_id
    assert dto.author_id == author_id


def test_get_cms_series_detail_raises_404_when_not_found():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=None):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            get_cms_series_detail(token="dummy", series_id=series_id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert str(series_id) in exc.value.detail


def test_get_cms_series_detail_raises_403_when_non_admin_other_author():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    row = MagicMock()
    row.id = series_id
    row.author_id = other_author_id
    row.group_id = FIXTURE_GROUP_ID

    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.require_can_read_group_content", side_effect=_SERIES_FORBIDDEN), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=row):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            get_cms_series_detail(token="dummy", series_id=series_id)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_get_cms_series_detail_admin_can_view_other_author_series():
    series_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    row = MagicMock()
    row.id = series_id
    row.name = {"en": "Someone else's"}
    row.image = None
    row.author_id = other_author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.DRAFT
    row.plans = []

    mock_admin = _make_mock_author(admin_id, is_admin=True)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_admin), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=row):
        _session_local_context(mock_session_local)

        dto = get_cms_series_detail(token="dummy", series_id=series_id)

    assert dto.id == series_id
    assert dto.author_id == other_author_id


def test_get_cms_series_detail_filters_plans_by_language():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    plan_en = MagicMock()
    plan_en.deleted_at = None
    plan_en.display_order = 0
    plan_en.id = uuid.uuid4()
    plan_en.title = "English plan"
    plan_en.description = None
    plan_en.language = LanguageCode.EN
    plan_en.difficulty_level = None
    plan_en.image_url = None
    plan_en.tag_list = []
    plan_en.status = PlanStatus.DRAFT
    plan_en.featured = False
    plan_en.start_date = None
    plan_en.items = []
    plan_en.group_id = FIXTURE_GROUP_ID

    plan_bo = MagicMock()
    plan_bo.deleted_at = None
    plan_bo.display_order = 1
    plan_bo.id = uuid.uuid4()
    plan_bo.title = "Tibetan plan"
    plan_bo.description = None
    plan_bo.language = LanguageCode.BO
    plan_bo.difficulty_level = None
    plan_bo.image_url = None
    plan_bo.tag_list = []
    plan_bo.status = PlanStatus.DRAFT
    plan_bo.featured = False
    plan_bo.start_date = None
    plan_bo.items = []
    plan_bo.group_id = FIXTURE_GROUP_ID

    row = MagicMock()
    row.id = series_id
    row.metadata_entries = []
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.DRAFT
    row.plans = [plan_en, plan_bo]

    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=row):
        _session_local_context(mock_session_local)

        dto = get_cms_series_detail(token="dummy", series_id=series_id, language="bo")

    assert len(dto.plans) == 1
    assert dto.plans[0].id == plan_bo.id
    assert dto.plans[0].language == "BO"


def test_get_filtered_series_handles_plain_string_status_and_language():
    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = []
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.DRAFT.value
    row.plans = None

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_paginated",
        return_value=([(row, 0, 0)], 1),
    ):
        _session_local_context(mock_session_local)

        result = get_filtered_series(search=None, skip=0, limit=10)

    assert result.total == 1
    assert result.series[0].status == PlanStatus.DRAFT
    assert result.series[0].metadata == []


def test_get_filtered_series_metadata_uses_string_language():
    entry = MagicMock()
    entry.id = uuid.uuid4()
    entry.title = "Title"
    entry.description = None
    entry.language = "EN"

    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [entry]
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.DRAFT
    row.plans = None

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_paginated",
        return_value=([(row, 0, 0)], 1),
    ):
        _session_local_context(mock_session_local)

        result = get_filtered_series(search=None, skip=0, limit=10)

    assert result.series[0].metadata[0].language == "EN"


def test_validate_plan_ids_noop_when_empty():
    with patch("pecha_api.plans.series.series_service.get_plans_by_ids") as mock_get_plans:
        _validate_plan_ids(
            db=MagicMock(),
            plan_ids=[],
            series_group_id=FIXTURE_GROUP_ID,
        )
    mock_get_plans.assert_not_called()

# ---------------------------------------------------------------------------
# _build_plan_order_pairs: per-language display_order computation
# ---------------------------------------------------------------------------

def test_build_plan_order_pairs_none_returns_empty():
    assert _build_plan_order_pairs(None) == []


def test_build_plan_order_pairs_empty_dict_returns_empty():
    assert _build_plan_order_pairs({}) == []


def test_build_plan_order_pairs_single_language_indexes_from_zero():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    pairs = _build_plan_order_pairs({"EN": [a, b, c]})

    assert pairs == [(a, 0), (b, 1), (c, 2)]


def test_build_plan_order_pairs_each_language_numbered_independently():
    a, b, x, y = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    pairs = _build_plan_order_pairs({"EN": [a, b], "BO": [x, y]})

    assert pairs == [(a, 0), (b, 1), (x, 0), (y, 1)]


def test_build_plan_order_pairs_preserves_request_order_not_sorted():
    c, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    pairs = _build_plan_order_pairs({"EN": [c, a, b]})

    assert pairs == [(c, 0), (a, 1), (b, 2)]


def test_build_plan_order_pairs_dedupes_keeping_first_occurrence():
    a, b = uuid.uuid4(), uuid.uuid4()

    pairs = _build_plan_order_pairs({"EN": [a, a, b]})

    assert pairs == [(a, 0), (b, 1)]


def test_build_plan_order_pairs_handles_more_than_ten_plans():
    ids = [uuid.uuid4() for _ in range(15)]

    pairs = _build_plan_order_pairs({"EN": ids})

    # display_order is a plain counter; it scales past single digits.
    assert pairs == [(pid, idx) for idx, pid in enumerate(ids)]
    assert pairs[-1][1] == 14


def test_build_plan_order_pairs_skips_empty_language_list():
    a = uuid.uuid4()

    pairs = _build_plan_order_pairs({"EN": [a], "BO": []})

    assert pairs == [(a, 0)]


# ---------------------------------------------------------------------------
# PUT: pure reorder of already-attached plans (no add/remove)
# ---------------------------------------------------------------------------

def test_update_existing_series_pure_reorder_sends_all_plans_with_new_order():
    """Reordering already-attached plans (no additions, no removals) must still
    send every plan to the repository so their display_order is rewritten."""
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    plan_a_id = uuid.uuid4()
    plan_b_id = uuid.uuid4()
    plan_c_id = uuid.uuid4()

    existing_a = MagicMock()
    existing_a.id = plan_a_id
    existing_a.deleted_at = None
    existing_b = MagicMock()
    existing_b.id = plan_b_id
    existing_b.deleted_at = None
    existing_c = MagicMock()
    existing_c.id = plan_c_id
    existing_c.deleted_at = None

    existing = _make_existing_series(
        series_id, author_id, plans=[existing_a, existing_b, existing_c]
    )
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    fetched_a = MagicMock()
    fetched_a.id = plan_a_id
    fetched_a.deleted_at = None
    fetched_a.series_id = series_id
    fetched_a.author_id = author_id
    fetched_a.group_id = FIXTURE_GROUP_ID
    fetched_b = MagicMock()
    fetched_b.id = plan_b_id
    fetched_b.deleted_at = None
    fetched_b.series_id = series_id
    fetched_b.author_id = author_id
    fetched_b.group_id = FIXTURE_GROUP_ID
    fetched_c = MagicMock()
    fetched_c.id = plan_c_id
    fetched_c.deleted_at = None
    fetched_c.series_id = series_id
    fetched_c.author_id = author_id
    fetched_c.group_id = FIXTURE_GROUP_ID

    # Same three plans, reordered to C, A, B.
    request = UpdateSeriesRequest(plans={"EN": [plan_c_id, plan_a_id, plan_b_id]})

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[fetched_a, fetched_b, fetched_c]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["plans_to_attach"] == [
        (plan_c_id, 0),
        (plan_a_id, 1),
        (plan_b_id, 2),
    ]
    assert call_kwargs["plan_ids_to_detach"] == []


def test_update_existing_series_reorder_skips_group_check_for_attached_plans():
    """Reordering plans already in the series must not fail when plan.group_id
    differs from series.group_id — series membership implies same group."""
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    other_group_id = uuid.uuid4()

    plan_a_id = uuid.uuid4()
    plan_b_id = uuid.uuid4()

    existing_a = MagicMock()
    existing_a.id = plan_a_id
    existing_a.deleted_at = None
    existing_b = MagicMock()
    existing_b.id = plan_b_id
    existing_b.deleted_at = None

    existing = _make_existing_series(series_id, author_id, plans=[existing_a, existing_b])
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    fetched_a = MagicMock()
    fetched_a.id = plan_a_id
    fetched_a.deleted_at = None
    fetched_a.series_id = series_id
    fetched_a.author_id = author_id
    fetched_a.group_id = other_group_id
    fetched_b = MagicMock()
    fetched_b.id = plan_b_id
    fetched_b.deleted_at = None
    fetched_b.series_id = series_id
    fetched_b.author_id = author_id
    fetched_b.group_id = other_group_id

    request = UpdateSeriesRequest(plans={"EN": [plan_b_id, plan_a_id]})

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[fetched_a, fetched_b]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    mock_update.assert_called_once()


def test_update_existing_series_multi_language_independent_ordering():
    """Each language list is numbered independently from zero."""
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    en_1, en_2 = uuid.uuid4(), uuid.uuid4()
    bo_1, bo_2 = uuid.uuid4(), uuid.uuid4()

    existing = _make_existing_series(series_id, author_id, plans=[])
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    def _fetched(pid):
        m = MagicMock()
        m.id = pid
        m.deleted_at = None
        m.series_id = None
        m.author_id = author_id
        m.group_id = FIXTURE_GROUP_ID
        return m

    request = UpdateSeriesRequest(
        plans={"EN": [en_1, en_2], "BO": [bo_1, bo_2]}
    )

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.get_plans_by_ids", return_value=[_fetched(en_1), _fetched(en_2), _fetched(bo_1), _fetched(bo_2)]), \
         patch("pecha_api.plans.series.series_service.update_series_with_plans") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series(token="dummy", series_id=series_id, update_series_request=request)

    plans_to_attach = mock_update.call_args.kwargs["plans_to_attach"]
    assert plans_to_attach == [(en_1, 0), (en_2, 1), (bo_1, 0), (bo_2, 1)]


# ---------------------------------------------------------------------------
# DELETE: delete_existing_series
# ---------------------------------------------------------------------------

def test_delete_existing_series_soft_deletes_when_owner():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    mock_author = _make_mock_author(author_id, email="owner@pecha.org", is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.soft_delete_series_with_plan_detach") as mock_soft_delete:
        _session_local_context(mock_session_local)

        result = delete_existing_series(token="dummy", series_id=series_id)

    assert result is None
    mock_soft_delete.assert_called_once()
    call_kwargs = mock_soft_delete.call_args.kwargs
    assert call_kwargs["series"] is existing
    assert call_kwargs["deleted_by"] == "owner@pecha.org"


def test_delete_existing_series_returns_404_when_series_not_found():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=None), \
         patch("pecha_api.plans.series.series_service.soft_delete_series_with_plan_detach") as mock_soft_delete:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            delete_existing_series(token="dummy", series_id=series_id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert str(series_id) in exc.value.detail
    mock_soft_delete.assert_not_called()


def test_delete_existing_series_returns_403_when_non_admin_other_author():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, other_author_id)
    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.require_can_change_status", side_effect=_SERIES_FORBIDDEN), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.soft_delete_series_with_plan_detach") as mock_soft_delete:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            delete_existing_series(token="dummy", series_id=series_id)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_soft_delete.assert_not_called()


def test_delete_existing_series_admin_can_delete_other_author_series():
    series_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, other_author_id)
    mock_admin = _make_mock_author(admin_id, is_admin=True)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_admin), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.soft_delete_series_with_plan_detach") as mock_soft_delete:
        _session_local_context(mock_session_local)

        result = delete_existing_series(token="dummy", series_id=series_id)

    assert result is None
    mock_soft_delete.assert_called_once()


def test_delete_existing_series_integrity_error_raises_400():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    orig = Exception("foreign key violation")

    existing = _make_existing_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.soft_delete_series_with_plan_detach",
               side_effect=IntegrityError("statement", {}, orig)):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            delete_existing_series(token="dummy", series_id=series_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Database integrity error" in exc.value.detail

# ===========================================================================
# PATCH /status — update_existing_series_status
# ===========================================================================

def test_update_existing_series_status_updates_status_when_owner():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    refreshed = _make_refreshed_series(series_id, author_id)
    mock_author = _make_mock_author(author_id, email="owner@pecha.org")

    request = UpdateSeriesStatusRequest(status=PlanStatus.PUBLISHED)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_status") as mock_update:
        _session_local_context(mock_session_local)
        dto = update_existing_series_status(
            token="dummy", series_id=series_id, update_series_status_request=request
        )

    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["series"] is existing
    assert call_kwargs["status"] == PlanStatus.PUBLISHED
    assert call_kwargs["updated_by"] == "owner@pecha.org"
    assert isinstance(call_kwargs["updated_at"], datetime)
    assert call_kwargs["updated_at"].tzinfo is not None
    assert dto.id == series_id


def test_update_existing_series_status_returns_404_when_not_found():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesStatusRequest(status=PlanStatus.PUBLISHED)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=None), \
         patch("pecha_api.plans.series.series_service.update_series_status") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series_status(
                token="dummy", series_id=series_id, update_series_status_request=request
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert str(series_id) in exc.value.detail
    mock_update.assert_not_called()


def test_update_existing_series_status_returns_403_when_non_admin_other_author():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, other_author_id)
    mock_author = _make_mock_author(author_id, is_admin=False)

    request = UpdateSeriesStatusRequest(status=PlanStatus.PUBLISHED)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.require_can_change_status", side_effect=_SERIES_FORBIDDEN), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_status") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series_status(
                token="dummy", series_id=series_id, update_series_status_request=request
            )

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_update.assert_not_called()


def test_update_existing_series_status_admin_can_update_other_author_series():
    series_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, other_author_id)
    refreshed = _make_refreshed_series(series_id, other_author_id)
    mock_admin = _make_mock_author(admin_id, is_admin=True)

    request = UpdateSeriesStatusRequest(status=PlanStatus.PUBLISHED)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_admin), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", side_effect=[existing, refreshed]), \
         patch("pecha_api.plans.series.series_service.update_series_status") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series_status(
            token="dummy", series_id=series_id, update_series_status_request=request
        )

    mock_update.assert_called_once()


def test_update_existing_series_status_integrity_error_raises_400():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    orig = Exception("constraint violation")

    existing = _make_existing_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    request = UpdateSeriesStatusRequest(status=PlanStatus.PUBLISHED)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_status",
               side_effect=IntegrityError("statement", {}, orig)):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series_status(
                token="dummy", series_id=series_id, update_series_status_request=request
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Database integrity error" in exc.value.detail


# ===========================================================================
# PATCH /featured — update_existing_series_featured
# ===========================================================================

def test_update_existing_series_featured_toggles_false_to_true():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    existing.featured = False
    mock_author = _make_mock_author(author_id, email="owner@pecha.org")

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_featured") as mock_update:
        _session_local_context(mock_session_local)
        result = update_existing_series_featured(token="dummy", series_id=series_id)

    assert result is None
    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["series"] is existing
    assert call_kwargs["featured"] is True
    assert call_kwargs["updated_by"] == "owner@pecha.org"
    assert isinstance(call_kwargs["updated_at"], datetime)
    assert call_kwargs["updated_at"].tzinfo is not None


def test_update_existing_series_featured_toggles_true_to_false():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, author_id)
    existing.featured = True
    mock_author = _make_mock_author(author_id)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_featured") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series_featured(token="dummy", series_id=series_id)

    assert mock_update.call_args.kwargs["featured"] is False


def test_update_existing_series_featured_returns_404_when_not_found():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=None), \
         patch("pecha_api.plans.series.series_service.update_series_featured") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series_featured(token="dummy", series_id=series_id)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert str(series_id) in exc.value.detail
    mock_update.assert_not_called()


def test_update_existing_series_featured_returns_403_when_non_admin_other_author():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, other_author_id)
    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.require_can_change_status", side_effect=_SERIES_FORBIDDEN), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_featured") as mock_update:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series_featured(token="dummy", series_id=series_id)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN
    mock_update.assert_not_called()


def test_update_existing_series_featured_admin_can_update_other_author_series():
    series_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    other_author_id = uuid.uuid4()

    existing = _make_existing_series(series_id, other_author_id)
    existing.featured = False
    mock_admin = _make_mock_author(admin_id, is_admin=True)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_admin), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_featured") as mock_update:
        _session_local_context(mock_session_local)
        update_existing_series_featured(token="dummy", series_id=series_id)

    mock_update.assert_called_once()


def test_update_existing_series_featured_integrity_error_raises_400():
    series_id = uuid.uuid4()
    author_id = uuid.uuid4()
    orig = Exception("constraint violation")

    existing = _make_existing_series(series_id, author_id)
    mock_author = _make_mock_author(author_id)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_series_by_id", return_value=existing), \
         patch("pecha_api.plans.series.series_service.update_series_featured",
               side_effect=IntegrityError("statement", {}, orig)):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            update_existing_series_featured(token="dummy", series_id=series_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Database integrity error" in exc.value.detail


# ---------------------------------------------------------------------------
# plan_count published_only: get_filtered_series vs get_cms_filtered_series
# ---------------------------------------------------------------------------

def test_get_filtered_series_passes_published_only_true_to_repository():
    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_paginated",
        return_value=([], 0),
    ) as mock_repo:
        _session_local_context(mock_session_local)

        get_filtered_series(search=None, skip=0, limit=10)

    assert mock_repo.call_args.kwargs["published_only"] is True


def test_get_filtered_series_published_count_maps_to_plan_count():
    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [_metadata_entry(title="Published count")]
    row.image = None
    row.author_id = uuid.uuid4()
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.PUBLISHED
    row.plans = None

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_paginated",
        return_value=([(row, 4, 0)], 1),
    ):
        _session_local_context(mock_session_local)

        result = get_filtered_series(search=None, skip=0, limit=10)

    assert result.series[0].plan_count == 4


def test_get_cms_filtered_series_does_not_pass_published_only():
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_author_group_ids", return_value=_MEMBER_GROUP_IDS), \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([], 0)) as mock_repo:
        _session_local_context(mock_session_local)

        get_cms_filtered_series(token="dummy", search=None, skip=0, limit=10)

    assert mock_repo.call_args.kwargs.get("published_only", False) is False


def test_get_cms_filtered_series_count_maps_to_plan_count():
    author_id = uuid.uuid4()
    row = MagicMock()
    row.id = uuid.uuid4()
    row.metadata_entries = [_metadata_entry(title="All-status count")]
    row.image = None
    row.author_id = author_id
    row.group_id = FIXTURE_GROUP_ID
    row.featured = False
    row.status = PlanStatus.DRAFT
    row.plans = None

    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_author_group_ids", return_value=_MEMBER_GROUP_IDS), \
         patch("pecha_api.plans.series.series_service.get_series_paginated",
               return_value=([(row, 9, 0)], 1)):
        _session_local_context(mock_session_local)

        result = get_cms_filtered_series(token="dummy", search=None, skip=0, limit=10)

    assert result.series[0].plan_count == 9


def _make_series_plan(language=LanguageCode.EN):
    plan = MagicMock()
    plan.id = uuid.uuid4()
    plan.deleted_at = None
    plan.language = language
    plan.title = "Plan"
    plan.description = None
    plan.difficulty_level = DifficultyLevel.BEGINNER
    plan.image_url = None
    plan.tag_list = []
    plan.status = PlanStatus.DRAFT
    plan.featured = False
    plan.display_order = 0
    plan.start_date = None
    plan.items = []
    plan.group_id = FIXTURE_GROUP_ID
    return plan


def test_clone_series_plans_for_language_clones_and_returns_dto():
    series_id = uuid.uuid4()
    row = MagicMock()
    row.id = series_id
    row.group_id = FIXTURE_GROUP_ID
    row.status = PlanStatus.DRAFT
    row.plans = [_make_series_plan(LanguageCode.EN)]
    row.metadata_entries = [_metadata_entry()]
    row.image = None
    row.author_id = uuid.uuid4()
    row.featured = False

    cloned_plan = MagicMock()
    cloned_plan.id = uuid.uuid4()
    mock_author = _make_mock_author(row.author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ), patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ), patch(
        "pecha_api.plans.series.series_service.require_can_edit_content",
    ), patch(
        "pecha_api.plans.series.series_service.clone_series_language_plans",
        return_value=[cloned_plan],
    ) as mock_clone, patch(
        "pecha_api.plans.series.series_service.get_enrolled_count_map_by_series_ids",
        return_value={},
    ), patch(
        "pecha_api.plans.series.series_service._group_summary_for_series",
        return_value=None,
    ):
        _session_local_context(mock_session_local)

        dto = clone_series_plans_for_language(
            token="dummy",
            series_id=series_id,
            clone_request=CloneSeriesPlansRequest(
                source_language=LanguageCode.EN,
                target_language=LanguageCode.BO,
            ),
        )

    mock_clone.assert_called_once()
    assert dto.id == series_id


def test_clone_series_plans_for_language_rejects_when_target_has_plans():
    series_id = uuid.uuid4()
    row = MagicMock()
    row.id = series_id
    row.group_id = FIXTURE_GROUP_ID
    row.status = PlanStatus.DRAFT
    row.plans = [
        _make_series_plan(LanguageCode.EN),
        _make_series_plan(LanguageCode.BO),
    ]

    mock_author = _make_mock_author(uuid.uuid4(), is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ), patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ), patch(
        "pecha_api.plans.series.series_service.require_can_edit_content",
    ), patch(
        "pecha_api.plans.series.series_service.clone_series_language_plans",
    ) as mock_clone:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            clone_series_plans_for_language(
                token="dummy",
                series_id=series_id,
                clone_request=CloneSeriesPlansRequest(
                    source_language=LanguageCode.EN,
                    target_language=LanguageCode.BO,
                ),
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_clone.assert_not_called()


def test_series_schedule_from_plans_returns_total_days_without_published_schedule():
    draft_plan = _featured_series_plan(
        display_order=0,
        start_date=datetime(2026, 7, 1, tzinfo=timezone.utc),
        item_count=4,
        status=PlanStatus.DRAFT,
    )

    start_date, end_date, total_days = _series_schedule_from_plans(
        [draft_plan],
        published_only=False,
    )

    assert start_date is None
    assert end_date is None
    assert total_days == 4


def test_series_schedule_from_plans_returns_start_without_end_when_last_plan_has_no_start_date():
    series_start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    first_plan = _featured_series_plan(
        display_order=0,
        start_date=series_start,
        item_count=2,
    )
    last_plan = _featured_series_plan(
        display_order=1,
        start_date=None,
        item_count=3,
    )

    start_date, end_date, total_days = _series_schedule_from_plans(
        [first_plan, last_plan],
        published_only=True,
    )

    assert start_date == series_start
    assert end_date is None
    assert total_days == 5


def test_active_plan_ids_excludes_soft_deleted_plans():
    active_plan = MagicMock()
    active_plan.id = uuid.uuid4()
    active_plan.deleted_at = None
    deleted_plan = MagicMock()
    deleted_plan.id = uuid.uuid4()
    deleted_plan.deleted_at = datetime.now(timezone.utc)

    series = MagicMock()
    series.plans = [active_plan, deleted_plan]

    assert _active_plan_ids(series) == [active_plan.id]


def test_group_summary_for_series_returns_none_without_group_id():
    series = MagicMock()
    series.group_id = None

    assert _group_summary_for_series(MagicMock(), series) is None


def test_get_cms_filtered_series_returns_empty_when_author_has_no_groups():
    author_id = uuid.uuid4()
    mock_author = _make_mock_author(author_id, is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.series.series_service.validate_cms_author_details", return_value=mock_author), \
         patch("pecha_api.plans.series.series_service.get_author_group_ids", return_value=[]), \
         patch("pecha_api.plans.series.series_service.get_series_paginated") as mock_repo:
        _session_local_context(mock_session_local)

        result = get_cms_filtered_series(token="dummy", search=None, skip=0, limit=10)

    mock_repo.assert_not_called()
    assert result.series == []
    assert result.total == 0
    assert result.skip == 0
    assert result.limit == 10


def test_clone_series_integrity_error_raises_400():
    parent_id = uuid.uuid4()
    target_group_id = uuid.uuid4()
    request = CreateSeriesRequest(
        group_id=target_group_id,
        parent_series_id=parent_id,
    )
    parent = MagicMock()
    parent.id = parent_id
    parent.group_id = FIXTURE_GROUP_ID
    mock_author = MagicMock()
    mock_author.id = uuid.uuid4()
    mock_author.email = "cloner@example.com"
    orig = Exception("constraint violation")

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.get_series_for_clone",
        return_value=parent,
    ), patch(
        "pecha_api.plans.series.series_service.require_can_read_group_content",
    ), patch(
        "pecha_api.plans.series.series_service.require_can_create_content",
    ), patch(
        "pecha_api.plans.series.series_service.clone_series_with_plans",
        side_effect=IntegrityError("statement", {}, orig),
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            create_new_series(token="dummy", create_series_request=request)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Database integrity error" in exc.value.detail


def test_clone_series_plans_for_language_raises_404_when_series_missing():
    series_id = uuid.uuid4()
    mock_author = _make_mock_author(uuid.uuid4(), is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ), patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=None,
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            clone_series_plans_for_language(
                token="dummy",
                series_id=series_id,
                clone_request=CloneSeriesPlansRequest(
                    source_language=LanguageCode.EN,
                    target_language=LanguageCode.BO,
                ),
            )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_clone_series_plans_for_language_raises_400_when_no_source_plans():
    series_id = uuid.uuid4()
    row = MagicMock()
    row.id = series_id
    row.group_id = FIXTURE_GROUP_ID
    row.status = PlanStatus.DRAFT
    row.plans = [_make_series_plan(LanguageCode.BO)]

    mock_author = _make_mock_author(uuid.uuid4(), is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ), patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ), patch(
        "pecha_api.plans.series.series_service.require_can_edit_content",
    ), patch(
        "pecha_api.plans.series.series_service.clone_series_language_plans",
    ) as mock_clone:
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            clone_series_plans_for_language(
                token="dummy",
                series_id=series_id,
                clone_request=CloneSeriesPlansRequest(
                    source_language=LanguageCode.EN,
                    target_language=LanguageCode.BO,
                ),
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "No plans found in language" in exc.value.detail
    mock_clone.assert_not_called()


def test_clone_series_plans_for_language_raises_400_when_clone_returns_empty():
    series_id = uuid.uuid4()
    row = MagicMock()
    row.id = series_id
    row.group_id = FIXTURE_GROUP_ID
    row.status = PlanStatus.DRAFT
    row.plans = [_make_series_plan(LanguageCode.EN)]

    mock_author = _make_mock_author(uuid.uuid4(), is_admin=False)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ), patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ), patch(
        "pecha_api.plans.series.series_service.require_can_edit_content",
    ), patch(
        "pecha_api.plans.series.series_service.clone_series_language_plans",
        return_value=[],
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            clone_series_plans_for_language(
                token="dummy",
                series_id=series_id,
                clone_request=CloneSeriesPlansRequest(
                    source_language=LanguageCode.EN,
                    target_language=LanguageCode.BO,
                ),
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Could not clone plans" in exc.value.detail


def test_clone_series_plans_for_language_integrity_error_raises_400():
    series_id = uuid.uuid4()
    row = MagicMock()
    row.id = series_id
    row.group_id = FIXTURE_GROUP_ID
    row.status = PlanStatus.DRAFT
    row.plans = [_make_series_plan(LanguageCode.EN)]
    mock_author = _make_mock_author(uuid.uuid4(), is_admin=False)
    orig = Exception("constraint violation")

    with patch("pecha_api.plans.series.series_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ), patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=row,
    ), patch(
        "pecha_api.plans.series.series_service.require_can_edit_content",
    ), patch(
        "pecha_api.plans.series.series_service.clone_series_language_plans",
        side_effect=IntegrityError("statement", {}, orig),
    ):
        _session_local_context(mock_session_local)

        with pytest.raises(HTTPException) as exc:
            clone_series_plans_for_language(
                token="dummy",
                series_id=series_id,
                clone_request=CloneSeriesPlansRequest(
                    source_language=LanguageCode.EN,
                    target_language=LanguageCode.BO,
                ),
            )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Database integrity error" in exc.value.detail


# --- Series partner CMS service ---

from pecha_api.plans.series.series_service import (
    add_series_partner,
    remove_series_partner,
    list_series_partners_for_cms,
)
from pecha_api.plans.series.series_response_models import AddSeriesPartnerRequest


def _series_row(series_id, group_id):
    row = MagicMock()
    row.id = series_id
    row.group_id = group_id
    return row


def test_add_series_partner_404_when_series_missing():
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id", return_value=None
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        with pytest.raises(HTTPException) as exc:
            add_series_partner(
                token="dummy",
                series_id=uuid.uuid4(),
                add_request=AddSeriesPartnerRequest(group_id=uuid.uuid4()),
            )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_add_series_partner_404_when_group_missing():
    series_id, owner_group = uuid.uuid4(), uuid.uuid4()
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_change_status"
    ), patch(
        "pecha_api.plans.groups.groups_repository.get_group_by_id", return_value=None
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        with pytest.raises(HTTPException) as exc:
            add_series_partner(
                token="dummy",
                series_id=series_id,
                add_request=AddSeriesPartnerRequest(group_id=uuid.uuid4()),
            )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_add_series_partner_enforces_permission():
    series_id, owner_group = uuid.uuid4(), uuid.uuid4()
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_change_status",
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN"),
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        with pytest.raises(HTTPException) as exc:
            add_series_partner(
                token="dummy",
                series_id=series_id,
                add_request=AddSeriesPartnerRequest(group_id=uuid.uuid4()),
            )
    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_add_series_partner_success_returns_item():
    series_id, owner_group, partner_group = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    partner_row = MagicMock()
    partner_row.id = uuid.uuid4()

    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_change_status"
    ), patch(
        "pecha_api.plans.groups.groups_repository.get_group_by_id",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.ensure_series_partner",
        return_value=partner_row,
    ) as mock_ensure, patch(
        "pecha_api.plans.groups.groups_service.get_group_summaries_by_ids",
        return_value={},
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        result = add_series_partner(
            token="dummy",
            series_id=series_id,
            add_request=AddSeriesPartnerRequest(group_id=partner_group),
        )

    assert result.id == partner_row.id
    assert result.group_id == partner_group
    assert result.is_owner is False
    mock_ensure.assert_called_once()


def test_add_series_partner_maps_integrity_error_to_400():
    series_id, owner_group, partner_group = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_change_status"
    ), patch(
        "pecha_api.plans.groups.groups_repository.get_group_by_id",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.ensure_series_partner",
        side_effect=IntegrityError("stmt", {}, Exception("duplicate key")),
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        with pytest.raises(HTTPException) as exc:
            add_series_partner(
                token="dummy",
                series_id=series_id,
                add_request=AddSeriesPartnerRequest(group_id=partner_group),
            )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Database integrity error" in exc.value.detail


def test_remove_series_partner_rejects_owner_group():
    series_id, owner_group = uuid.uuid4(), uuid.uuid4()
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_change_status"
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        with pytest.raises(HTTPException) as exc:
            remove_series_partner(token="dummy", series_id=series_id, group_id=owner_group)
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


def test_remove_series_partner_404_when_series_missing():
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id", return_value=None
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        with pytest.raises(HTTPException) as exc:
            remove_series_partner(token="dummy", series_id=uuid.uuid4(), group_id=uuid.uuid4())
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_remove_series_partner_404_when_not_a_partner():
    series_id, owner_group, other_group = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_change_status"
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.soft_delete_series_partner",
        return_value=None,
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        with pytest.raises(HTTPException) as exc:
            remove_series_partner(token="dummy", series_id=series_id, group_id=other_group)
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_remove_series_partner_success_soft_deletes():
    series_id, owner_group, other_group = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_change_status"
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.soft_delete_series_partner",
        return_value=MagicMock(),
    ) as mock_del, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        db = _session_local_context(msl)
        remove_series_partner(token="dummy", series_id=series_id, group_id=other_group)
    mock_del.assert_called_once()
    db.commit.assert_called_once()


# --- _group_display_name ---

from pecha_api.plans.series.series_service import (
    _group_display_name,
    build_series_partner_dto,
)


def _group_summary(title, language="en", avatar_url=None):
    """Minimal AuthorGroupSummaryDTO-like stub for display-name resolution."""
    group = MagicMock()
    meta = MagicMock()
    meta.title = title
    meta.language = language
    group.metadata = [meta]
    group.avatar_url = avatar_url
    return group


def test_group_display_name_returns_default_when_metadata_none():
    group = MagicMock()
    group.metadata = None
    assert _group_display_name(group) == "Group"


def test_group_display_name_returns_default_for_empty_list():
    group = MagicMock()
    group.metadata = []
    assert _group_display_name(group) == "Group"


def test_group_display_name_picks_language_matched_title():
    group = _group_summary("Kadam Group", language="en")
    with patch(
        "pecha_api.plans.series.series_service.filter_by_language_with_fallback",
        return_value=[group.metadata[0]],
    ):
        assert _group_display_name(group, language="en") == "Kadam Group"


def test_group_display_name_falls_back_to_first_entry_when_no_match():
    group = _group_summary("First Title", language="bo")
    with patch(
        "pecha_api.plans.series.series_service.filter_by_language_with_fallback",
        return_value=[],
    ):
        assert _group_display_name(group, language="en") == "First Title"


def test_group_display_name_handles_single_metadata_object():
    group = MagicMock()
    meta = MagicMock()
    meta.title = "Solo Title"
    group.metadata = meta  # not a list
    assert _group_display_name(group) == "Solo Title"


# --- build_series_partner_dto ---


def test_build_series_partner_dto_returns_none_when_group_missing():
    assert build_series_partner_dto(group=None) is None


def test_build_series_partner_dto_builds_from_group():
    group = _group_summary("Partner Group", avatar_url="http://img/a.png")
    with patch(
        "pecha_api.plans.series.series_service.filter_by_language_with_fallback",
        return_value=[group.metadata[0]],
    ):
        dto = build_series_partner_dto(group=group)
    assert dto.group_name == "Partner Group"
    assert dto.group_image == "http://img/a.png"


# --- list_series_partners_for_cms ---


def test_list_series_partners_for_cms_404_when_series_missing():
    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id", return_value=None
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ):
        _session_local_context(msl)
        with pytest.raises(HTTPException) as exc:
            list_series_partners_for_cms(token="dummy", series_id=uuid.uuid4())
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_list_series_partners_for_cms_returns_partners_with_owner_flag():
    series_id, owner_group, partner_group = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    owner_partner_id, other_partner_id = uuid.uuid4(), uuid.uuid4()

    owner_row = MagicMock(id=owner_partner_id, group_id=owner_group)
    partner_row = MagicMock(id=other_partner_id, group_id=partner_group)

    owner_summary = _group_summary("Owner Group", avatar_url="http://img/owner.png")
    partner_summary = _group_summary("Partner Group", avatar_url="http://img/partner.png")

    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_read_group_content"
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.list_active_series_partners",
        return_value=[owner_row, partner_row],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_summaries_by_ids",
        return_value={owner_group: owner_summary, partner_group: partner_summary},
    ), patch(
        "pecha_api.plans.series.series_service.filter_by_language_with_fallback",
        side_effect=lambda entries, **_: entries,
    ):
        _session_local_context(msl)
        result = list_series_partners_for_cms(token="dummy", series_id=series_id)

    assert len(result.partners) == 2
    by_id = {p.id: p for p in result.partners}
    assert by_id[owner_partner_id].is_owner is True
    assert by_id[owner_partner_id].group_name == "Owner Group"
    assert by_id[other_partner_id].is_owner is False
    assert by_id[other_partner_id].group_image == "http://img/partner.png"


def test_list_series_partners_for_cms_uses_default_name_when_summary_missing():
    series_id, owner_group = uuid.uuid4(), uuid.uuid4()
    row = MagicMock(id=uuid.uuid4(), group_id=owner_group)

    with patch("pecha_api.plans.series.series_service.SessionLocal") as msl, patch(
        "pecha_api.plans.series.series_service.get_series_by_id",
        return_value=_series_row(series_id, owner_group),
    ), patch(
        "pecha_api.plans.series.series_service.require_can_read_group_content"
    ), patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.plans.users.plan_user_series_repository.list_active_series_partners",
        return_value=[row],
    ), patch(
        "pecha_api.plans.groups.groups_service.get_group_summaries_by_ids",
        return_value={},  # no summary for the group
    ):
        _session_local_context(msl)
        result = list_series_partners_for_cms(token="dummy", series_id=series_id)

    assert len(result.partners) == 1
    assert result.partners[0].group_name == "Group"
    assert result.partners[0].group_image is None
