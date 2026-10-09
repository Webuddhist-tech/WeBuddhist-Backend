import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.plans.plans_enums import PlanStatus, LanguageCode, DifficultyLevel
from pecha_api.plans.media.media_response_models import ImageUrlModel
from pecha_api.plans.series.series_response_models import (
    SeriesDTO,
    SeriesListItemDTO,
    SeriesListResponse,
    SeriesPlanDTO,
    SeriesMetadataDTO,
)


client = TestClient(api)


def _metadata(title: str, language: str = "EN") -> SeriesMetadataDTO:
    return SeriesMetadataDTO(
        id=uuid.uuid4(),
        title=title,
        description=None,
        language=language,
    )


def sample_series_dto_factory() -> SeriesDTO:
    return SeriesDTO(
        id=uuid.uuid4(),
        metadata=[_metadata("Foundations of Meditation")],
        image=None,
        image_key=None,
        author_id=uuid.uuid4(),
        featured=False,
        status=PlanStatus.DRAFT,
        total_days=0,
    )


@pytest.fixture
def sample_series_dto():
    return SeriesDTO(
        id=uuid.uuid4(),
        metadata=[
            _metadata("Foundations of Meditation", "EN"),
            _metadata("སྒོམ་", "BO"),
        ],
        image=ImageUrlModel(
            thumbnail="https://example.com/presigned/series-thumb.jpg",
            medium="https://example.com/presigned/series-medium.jpg",
            original="https://example.com/presigned/series.jpg",
        ),
        image_key="images/series_images/sid/uuid/original/cover.jpg",
        author_id=uuid.uuid4(),
        featured=True,
        status=PlanStatus.DRAFT,
        total_days=0,
    )


@pytest.fixture
def sample_series_list_response(sample_series_dto):
    list_item = SeriesListItemDTO(
        id=sample_series_dto.id,
        metadata=sample_series_dto.metadata,
        image=sample_series_dto.image,
        image_key=sample_series_dto.image_key,
        author_id=sample_series_dto.author_id,
        featured=sample_series_dto.featured,
        status=sample_series_dto.status,
        plan_count=2,
        total_days=0,
    )
    return SeriesListResponse(
        series=[list_item],
        skip=0,
        limit=10,
        total=1,
    )


def test_get_series_list_success(sample_series_list_response):
    with patch(
        "pecha_api.plans.series.public_series_view.get_filtered_series_cached",
        new_callable=AsyncMock,
        return_value=sample_series_list_response,
    ) as mock_service:
        response = client.get("/series")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        mock_service.assert_called_once_with(search=None, skip=0, limit=10, language=None, group_id=None, token=None, timezone_name=None)

        assert "series" in data
        assert data["skip"] == 0
        assert data["limit"] == 10
        assert data["total"] == 1
        assert len(data["series"]) == 1

        item = data["series"][0]
        assert item["metadata"] == [
            entry.model_dump(mode="json") for entry in sample_series_list_response.series[0].metadata
        ]
        assert item["author_id"] == str(sample_series_list_response.series[0].author_id)
        assert item["featured"] is True
        assert item["status"] == PlanStatus.DRAFT.value
        assert item["image"] == sample_series_list_response.series[0].image.model_dump()
        assert item["image_key"] == sample_series_list_response.series[0].image_key


def test_get_featured_series_success(sample_series_list_response):
    featured_item = sample_series_list_response.series[0]
    with patch(
        "pecha_api.plans.series.public_series_view.get_random_featured_series_cached",
        new_callable=AsyncMock,
        return_value=sample_series_list_response,
    ) as mock_service:
        response = client.get("/series/featured")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        mock_service.assert_called_once_with(language="en", limit=10, token=None)
        assert len(data["series"]) == 1
        item = data["series"][0]
        assert item["id"] == str(featured_item.id)
        assert item["featured"] is True
        assert "plans" not in item
        assert item["plan_count"] == featured_item.plan_count
        assert item["start_date"] is None
        assert item["end_date"] is None
        assert item["total_days"] == featured_item.total_days
        assert data["skip"] == 0
        assert data["limit"] == 10
        assert data["total"] == 1


def test_get_featured_series_includes_schedule_fields():
    series_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    series_end = datetime(2026, 6, 5, tzinfo=timezone.utc)
    list_item = SeriesListItemDTO(
        id=uuid.uuid4(),
        metadata=[_metadata("Featured Series")],
        author_id=uuid.uuid4(),
        featured=True,
        status=PlanStatus.PUBLISHED,
        plan_count=2,
        total_days=5,
        start_date=series_start,
        end_date=series_end,
    )
    featured_response = SeriesListResponse(
        series=[list_item],
        skip=0,
        limit=10,
        total=1,
    )

    with patch(
        "pecha_api.plans.series.public_series_view.get_random_featured_series_cached",
        new_callable=AsyncMock,
        return_value=featured_response,
    ):
        response = client.get("/series/featured")

    assert response.status_code == status.HTTP_200_OK
    item = response.json()["series"][0]
    assert item["start_date"] == "2026-06-01T00:00:00Z"
    assert item["end_date"] == "2026-06-05T00:00:00Z"
    assert item["total_days"] == 5


def test_get_featured_series_with_language(sample_series_list_response):
    with patch(
        "pecha_api.plans.series.public_series_view.get_random_featured_series_cached",
        new_callable=AsyncMock,
        return_value=sample_series_list_response,
    ) as mock_service:
        response = client.get("/series/featured", params={"language": "en"})

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(language="en", limit=10, token=None)


def test_get_featured_series_not_found():
    with patch(
        "pecha_api.plans.series.public_series_view.get_random_featured_series_cached",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No featured series found",
        ),
    ):
        response = client.get("/series/featured")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "No featured series found"


def test_get_series_list_with_search_pagination(sample_series_dto):
    empty_list = SeriesListResponse(series=[], skip=2, limit=5, total=0)
    with patch(
        "pecha_api.plans.series.public_series_view.get_filtered_series_cached",
        new_callable=AsyncMock,
        return_value=empty_list,
    ) as mock_service:
        response = client.get("/series", params={"search": "meditation", "skip": 2, "limit": 5})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        mock_service.assert_called_once_with(search="meditation", skip=2, limit=5, language=None, group_id=None, token=None, timezone_name=None)

        assert data["series"] == []
        assert data["skip"] == 2
        assert data["limit"] == 5
        assert data["total"] == 0


def test_create_series_success(sample_series_dto):
    author_id = uuid.uuid4()
    payload = {
        "group_id": str(uuid.uuid4()),
        "metadata": [{"title": "New Series", "language": "EN"}],
        "image_key": "series/uploads/key.jpg",
        "featured": False,
    }

    mock_author = MagicMock()
    mock_author.id = author_id

    with patch(
        "pecha_api.plans.series.series_view.create_new_series",
        return_value=sample_series_dto,
    ) as mock_create, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        response = client.post(
            "/cms/series",
            json=payload,
            headers={"Authorization": "Bearer dummy"}
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["token"] == "dummy"
        assert call_kwargs["create_series_request"].metadata[0].title == payload["metadata"][0]["title"]
        assert call_kwargs["create_series_request"].image_key == payload["image_key"]
        assert call_kwargs["create_series_request"].featured is False

        assert data["id"] == str(sample_series_dto.id)
        assert len(data["metadata"]) == len(sample_series_dto.metadata)
        assert data["status"] == sample_series_dto.status.value


def test_create_series_defaults_optional_featured(sample_series_dto):
    author_id = uuid.uuid4()
    payload = {
        "group_id": str(uuid.uuid4()),
        "metadata": [{"title": "Minimal", "language": "EN"}],
    }

    mock_author = MagicMock()
    mock_author.id = author_id

    with patch(
        "pecha_api.plans.series.series_view.create_new_series",
        return_value=sample_series_dto,
    ) as mock_create, patch(
        "pecha_api.plans.series.series_service.validate_cms_author_details",
        return_value=mock_author,
    ):
        response = client.post(
            "/cms/series",
            json=payload,
            headers={"Authorization": "Bearer dummy"}
        )

        assert response.status_code == status.HTTP_201_CREATED
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["create_series_request"].featured is False


def test_create_series_validation_error_missing_required_fields():
    response = client.post(
        "/cms/series",
        json={},
        headers={"Authorization": "Bearer dummy"}
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_get_series_by_id_success(sample_series_dto):
    series_id = sample_series_dto.id
    with patch(
        "pecha_api.plans.series.public_series_view.get_series_detail_cached",
        new_callable=AsyncMock,
        return_value=sample_series_dto,
    ) as mock_detail:
        response = client.get(f"/series/{series_id}")

        assert response.status_code == status.HTTP_200_OK
        mock_detail.assert_called_once_with(series_id=series_id, language=None, token=None, timezone_name=None)

        data = response.json()
        assert data["id"] == str(sample_series_dto.id)
        assert len(data["metadata"]) == len(sample_series_dto.metadata)
        assert data["status"] == sample_series_dto.status.value


def test_get_series_by_id_not_found():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.public_series_view.get_series_detail_cached",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Series with id '{series_id}' not found",
        ),
    ):
        response = client.get(f"/series/{series_id}")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_get_series_by_id_includes_total_days_in_response():
    series_id = uuid.uuid4()
    plan_1_id = uuid.uuid4()
    plan_2_id = uuid.uuid4()

    plan_1 = SeriesPlanDTO(
        id=plan_1_id,
        title="Plan 1",
        description="First plan",
        language=LanguageCode.EN.value,
        difficulty_level=DifficultyLevel.BEGINNER,
        image=None,
        image_key=None,
        tags=[],
        status=PlanStatus.DRAFT,
        featured=False,
        display_order=1,
        start_date=None,
        total_days=5,
    )

    plan_2 = SeriesPlanDTO(
        id=plan_2_id,
        title="Plan 2",
        description="Second plan",
        language=LanguageCode.EN.value,
        difficulty_level=DifficultyLevel.INTERMEDIATE,
        image=None,
        image_key=None,
        tags=[],
        status=PlanStatus.PUBLISHED,
        featured=False,
        display_order=2,
        start_date=None,
        total_days=3,
    )

    series_dto = SeriesDTO(
        id=series_id,
        metadata=[_metadata("Series with plans")],
        image=None,
        image_key=None,
        author_id=uuid.uuid4(),
        featured=False,
        status=PlanStatus.DRAFT,
        plans=[plan_1, plan_2],
        total_days=8,
    )

    with patch(
        "pecha_api.plans.series.public_series_view.get_series_detail_cached",
        new_callable=AsyncMock,
        return_value=series_dto,
    ) as mock_detail:
        response = client.get(f"/series/{series_id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        mock_detail.assert_called_once_with(series_id=series_id, language=None, token=None, timezone_name=None)

        assert data["total_days"] == 8
        assert len(data["plans"]) == 2
        assert data["plans"][0]["id"] == str(plan_1_id)
        assert data["plans"][0]["total_days"] == 5
        assert data["plans"][1]["id"] == str(plan_2_id)
        assert data["plans"][1]["total_days"] == 3


def test_get_series_list_returns_plan_count_not_plans():
    series_id = uuid.uuid4()
    list_item = SeriesListItemDTO(
        id=series_id,
        metadata=[_metadata("Series without plans")],
        image=None,
        image_key=None,
        author_id=uuid.uuid4(),
        featured=False,
        status=PlanStatus.DRAFT,
        plan_count=0,
        total_days=0,
    )

    series_list_response = SeriesListResponse(
        series=[list_item],
        skip=0,
        limit=10,
        total=1,
    )

    with patch(
        "pecha_api.plans.series.public_series_view.get_filtered_series_cached",
        new_callable=AsyncMock,
        return_value=series_list_response,
    ) as mock_service:
        response = client.get("/series")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        mock_service.assert_called_once_with(search=None, skip=0, limit=10, language=None, group_id=None, token=None, timezone_name=None)

        assert len(data["series"]) == 1
        assert data["series"][0]["plan_count"] == 0
        assert data["series"][0]["total_days"] == 0
        assert "plans" not in data["series"][0]


def test_get_series_list_with_group_filter():
    series_list_response = SeriesListResponse(series=[], skip=0, limit=10, total=0)
    group_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.public_series_view.get_filtered_series_cached",
        new_callable=AsyncMock,
        return_value=series_list_response,
    ) as mock_service:
        response = client.get("/series", params={"group_id": str(group_id)})

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(search=None, skip=0, limit=10, language=None, group_id=group_id, token=None, timezone_name=None)


def test_update_series_accepts_empty_body():
    series_id = uuid.uuid4()

    with patch(
        "pecha_api.plans.series.series_view.update_existing_series",
        return_value=sample_series_dto_factory(),
    ) as mock_update:
        response = client.put(
            f"/cms/series/{series_id}",
            json={},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_update.assert_called_once()


def test_update_series_rejects_invalid_language_key_in_plans():
    series_id = uuid.uuid4()
    payload = {"plans": {"FOO": [str(uuid.uuid4())]}}
    response = client.put(
        f"/cms/series/{series_id}",
        json=payload,
        headers={"Authorization": "Bearer dummy"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_update_series_accepts_multi_language_plans_payload():
    series_id = uuid.uuid4()
    payload = {
        "plans": {
            "EN": [str(uuid.uuid4()), str(uuid.uuid4())],
            "BO": [str(uuid.uuid4())],
        }
    }

    with patch(
        "pecha_api.plans.series.series_view.update_existing_series",
        return_value=sample_series_dto_factory(),
    ) as mock_update:
        response = client.put(
            f"/cms/series/{series_id}",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_update.assert_called_once()
    request = mock_update.call_args.kwargs["update_series_request"]
    assert set(request.plans.keys()) == {"EN", "BO"}
    assert len(request.plans["EN"]) == 2
    assert len(request.plans["BO"]) == 1


def test_create_series_rejects_invalid_language_key_in_plans():
    payload = {
        "metadata": [{"title": "Test", "language": "EN"}],
        "plans": {"BAD": [str(uuid.uuid4())]},
    }
    response = client.post(
        "/cms/series",
        json=payload,
        headers={"Authorization": "Bearer dummy"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_get_cms_series_list_success(sample_series_list_response):
    with patch(
        "pecha_api.plans.series.series_view.get_cms_filtered_series",
        return_value=sample_series_list_response,
    ) as mock_service:
        response = client.get(
            "/cms/series",
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        mock_service.assert_called_once_with(
            token="dummy",
            search=None,
            skip=0,
            limit=10,
            language=None,
            plan_status=None,
            featured=None,
            filter_author_id=None,
        )

        assert data["total"] == 1
        assert len(data["series"]) == 1


def test_get_cms_series_list_passes_query_params(sample_series_dto):
    empty_list = SeriesListResponse(series=[], skip=2, limit=5, total=0)
    with patch(
        "pecha_api.plans.series.series_view.get_cms_filtered_series",
        return_value=empty_list,
    ) as mock_service:
        response = client.get(
            "/cms/series",
            params={"search": "meditation", "skip": 2, "limit": 5},
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(
            token="dummy",
            search="meditation",
            skip=2,
            limit=5,
            language=None,
            plan_status=None,
            featured=None,
            filter_author_id=None,
        )


def test_get_cms_series_by_id_success(sample_series_dto):
    series_id = sample_series_dto.id
    with patch(
        "pecha_api.plans.series.series_view.get_cms_series_detail",
        return_value=sample_series_dto,
    ) as mock_detail:
        response = client.get(
            f"/cms/series/{series_id}",
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_detail.assert_called_once_with(
            token="dummy", series_id=series_id, language=None
        )

        data = response.json()
        assert data["id"] == str(sample_series_dto.id)


def test_get_cms_series_by_id_not_found():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.get_cms_series_detail",
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Series with id '{series_id}' not found",
        ),
    ):
        response = client.get(
            f"/cms/series/{series_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_get_cms_series_by_id_forbidden():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.get_cms_series_detail",
        side_effect=HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this series",
        ),
    ):
        response = client.get(
            f"/cms/series/{series_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_get_series_by_id_passes_language_param(sample_series_dto):
    series_id = sample_series_dto.id
    with patch(
        "pecha_api.plans.series.public_series_view.get_series_detail_cached",
        new_callable=AsyncMock,
        return_value=sample_series_dto,
    ) as mock_detail:
        response = client.get(f"/series/{series_id}", params={"language": "bo"})

        assert response.status_code == status.HTTP_200_OK
        mock_detail.assert_called_once_with(series_id=series_id, language="bo", token=None, timezone_name=None)


def test_get_cms_series_by_id_passes_language_param(sample_series_dto):
    series_id = sample_series_dto.id
    with patch(
        "pecha_api.plans.series.series_view.get_cms_series_detail",
        return_value=sample_series_dto,
    ) as mock_detail:
        response = client.get(
            f"/cms/series/{series_id}",
            params={"language": "bo"},
            headers={"Authorization": "Bearer dummy"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_detail.assert_called_once_with(
            token="dummy", series_id=series_id, language="bo"
        )


def test_delete_series_success():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.delete_existing_series",
        return_value=None,
    ) as mock_delete:
        response = client.delete(
            f"/cms/series/{series_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert response.content == b""
    mock_delete.assert_called_once_with(token="dummy", series_id=series_id)


def test_delete_series_not_found():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.delete_existing_series",
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Series with id '{series_id}' not found",
        ),
    ):
        response = client.delete(
            f"/cms/series/{series_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_series_forbidden():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.delete_existing_series",
        side_effect=HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this series",
        ),
    ):
        response = client.delete(
            f"/cms/series/{series_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN

# ===========================================================================
# PATCH /cms/series/{series_id}/status
# ===========================================================================

def test_update_series_status_success(sample_series_dto):
    series_id = uuid.uuid4()
    payload = {"status": "PUBLISHED"}

    with patch(
        "pecha_api.plans.series.series_view.update_existing_series_status",
        return_value=sample_series_dto,
    ) as mock_update:
        response = client.patch(
            f"/cms/series/{series_id}/status",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["token"] == "dummy"
    assert call_kwargs["series_id"] == series_id
    assert call_kwargs["update_series_status_request"].status == PlanStatus.PUBLISHED

    data = response.json()
    assert data["id"] == str(sample_series_dto.id)


def test_update_series_status_rejects_invalid_status_value():
    series_id = uuid.uuid4()
    response = client.patch(
        f"/cms/series/{series_id}/status",
        json={"status": "NOT_A_REAL_STATUS"},
        headers={"Authorization": "Bearer dummy"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_update_series_status_rejects_missing_status_field():
    series_id = uuid.uuid4()
    response = client.patch(
        f"/cms/series/{series_id}/status",
        json={},
        headers={"Authorization": "Bearer dummy"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_update_series_status_not_found():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.update_existing_series_status",
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Series with id '{series_id}' not found",
        ),
    ):
        response = client.patch(
            f"/cms/series/{series_id}/status",
            json={"status": "PUBLISHED"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_update_series_status_forbidden():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.update_existing_series_status",
        side_effect=HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this series",
        ),
    ):
        response = client.patch(
            f"/cms/series/{series_id}/status",
            json={"status": "PUBLISHED"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# PATCH /cms/series/{series_id}/featured
# ===========================================================================

def test_update_series_featured_success():
    series_id = uuid.uuid4()

    with patch(
        "pecha_api.plans.series.series_view.update_existing_series_featured",
        return_value=None,
    ) as mock_update:
        response = client.patch(
            f"/cms/series/{series_id}/featured",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert response.content == b""
    mock_update.assert_called_once_with(token="dummy", series_id=series_id)


def test_update_series_featured_not_found():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.update_existing_series_featured",
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Series with id '{series_id}' not found",
        ),
    ):
        response = client.patch(
            f"/cms/series/{series_id}/featured",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_update_series_featured_forbidden():
    series_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.series.series_view.update_existing_series_featured",
        side_effect=HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this series",
        ),
    ):
        response = client.patch(
            f"/cms/series/{series_id}/featured",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_clone_series_plans_success(sample_series_dto):
    series_id = uuid.uuid4()
    payload = {
        "source_language": "EN",
        "target_language": "BO",
    }

    with patch(
        "pecha_api.plans.series.series_view.clone_series_plans_for_language",
        return_value=sample_series_dto,
    ) as mock_clone:
        response = client.post(
            f"/cms/series/{series_id}/clone-plans",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_clone.assert_called_once_with(
        token="dummy",
        series_id=series_id,
        clone_request=mock_clone.call_args.kwargs["clone_request"],
    )
    assert response.json()["id"] == str(sample_series_dto.id)

# --- Series partner CMS endpoints ---

def _partner_item(is_owner: bool = False):
    from pecha_api.plans.series.series_response_models import SeriesPartnerItemDTO
    return SeriesPartnerItemDTO(
        id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        group_name="Partner Group",
        group_image=None,
        is_owner=is_owner,
    )


def test_list_series_partners_success():
    from pecha_api.plans.series.series_response_models import SeriesPartnerListResponse

    series_id = uuid.uuid4()
    owner = _partner_item(is_owner=True)
    added = _partner_item(is_owner=False)
    response_model = SeriesPartnerListResponse(partners=[owner, added])

    with patch(
        "pecha_api.plans.series.series_view.list_series_partners_for_cms",
        return_value=response_model,
    ) as mock_list:
        response = client.get(
            f"/cms/series/{series_id}/partners",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data["partners"]) == 2
    assert data["partners"][0]["is_owner"] is True
    mock_list.assert_called_once()
    assert mock_list.call_args.kwargs["token"] == "dummy"
    assert mock_list.call_args.kwargs["series_id"] == series_id


def test_add_series_partner_success():
    series_id = uuid.uuid4()
    group_id = uuid.uuid4()
    item = _partner_item(is_owner=False)

    with patch(
        "pecha_api.plans.series.series_view.add_series_partner",
        return_value=item,
    ) as mock_add:
        response = client.post(
            f"/cms/series/{series_id}/partners",
            json={"group_id": str(group_id)},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["id"] == str(item.id)
    mock_add.assert_called_once()
    call_kwargs = mock_add.call_args.kwargs
    assert call_kwargs["token"] == "dummy"
    assert call_kwargs["series_id"] == series_id
    assert call_kwargs["add_request"].group_id == group_id


def test_add_series_partner_validation_error_missing_group_id():
    series_id = uuid.uuid4()
    response = client.post(
        f"/cms/series/{series_id}/partners",
        json={},
        headers={"Authorization": "Bearer dummy"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_delete_series_partner_success():
    series_id = uuid.uuid4()
    group_id = uuid.uuid4()

    with patch(
        "pecha_api.plans.series.series_view.remove_series_partner",
        return_value=None,
    ) as mock_remove:
        response = client.delete(
            f"/cms/series/{series_id}/partners/{group_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_remove.assert_called_once_with(
        token="dummy",
        series_id=series_id,
        group_id=group_id,
    )


def test_delete_series_partner_owner_rejected():
    series_id = uuid.uuid4()
    group_id = uuid.uuid4()

    with patch(
        "pecha_api.plans.series.series_view.remove_series_partner",
        side_effect=HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The series' owning group cannot be removed as a partner",
        ),
    ):
        response = client.delete(
            f"/cms/series/{series_id}/partners/{group_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
