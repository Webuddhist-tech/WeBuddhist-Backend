import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.plans.tags.tag_response_models import TagDTO, TagsListResponse

client = TestClient(api)


def _sample_tag_dto() -> TagDTO:
    from pecha_api.plans.tags.tag_response_models import TagMetadataDTO
    
    return TagDTO(
        id=uuid.uuid4(),
        name="Meditation",
        image="https://example.com/signed.jpg",
        image_key="images/tags/cover.jpg",
        description="Mindfulness tag",
        plan_ids=[],
        segment_ids=[],
        featured=False,
        display_order=None,
        metadata=[TagMetadataDTO(
            id=uuid.uuid4(),
            language="EN",
            name="Meditation",
            description="Mindfulness tag"
        )],
    )


@pytest.fixture
def sample_tag_dto():
    return _sample_tag_dto()


@pytest.fixture
def sample_tags_list_response(sample_tag_dto):
    return TagsListResponse(tags=[sample_tag_dto], skip=0, limit=10, total=1)


def test_create_tag_success(sample_tag_dto):
    payload = {
        "metadata": [
            {
                "language": "EN",
                "name": "Meditation",
                "description": "Mindfulness tag"
            }
        ],
        "image_key": "images/tags/cover.jpg",
    }

    with patch(
        "pecha_api.plans.tags.tag_views.create_new_tag",
        return_value=sample_tag_dto,
    ) as mock_create:
        response = client.post(
            "/api/v1/cms/tags",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["token"] == "dummy"
    assert len(mock_create.call_args.kwargs["create_tag_request"].metadata) == 1
    assert mock_create.call_args.kwargs["create_tag_request"].metadata[0].name == "Meditation"
    assert data["id"] == str(sample_tag_dto.id)
    assert data["name"] == sample_tag_dto.name
    assert data["image_key"] == sample_tag_dto.image_key


def test_create_tag_validation_error_missing_metadata():
    response = client.post(
        "/api/v1/cms/tags",
        json={"image_key": "test.jpg"},
        headers={"Authorization": "Bearer dummy"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_list_tags_success(sample_tags_list_response):
    with patch(
        "pecha_api.plans.tags.tag_views.get_cms_tags_list",
        return_value=sample_tags_list_response,
    ) as mock_list:
        response = client.get(
            "/api/v1/cms/tags",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    mock_list.assert_called_once_with(token="dummy", search=None, language="EN", skip=0, limit=10)
    assert data["total"] == 1
    assert len(data["tags"]) == 1
    assert data["tags"][0]["name"] == "Meditation"


def test_list_tags_passes_query_params(sample_tag_dto):
    empty = TagsListResponse(tags=[], skip=2, limit=5, total=0)
    with patch(
        "pecha_api.plans.tags.tag_views.get_cms_tags_list",
        return_value=empty,
    ) as mock_list:
        response = client.get(
            "/api/v1/cms/tags",
            params={"search": "med", "language": "BO", "skip": 2, "limit": 5},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_list.assert_called_once_with(token="dummy", search="med", language="BO", skip=2, limit=5)


def test_get_tag_by_id_success(sample_tag_dto):
    tag_id = sample_tag_dto.id
    with patch(
        "pecha_api.plans.tags.tag_views.get_cms_tag_detail",
        return_value=sample_tag_dto,
    ) as mock_detail:
        response = client.get(
            f"/api/v1/cms/tags/{tag_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_detail.assert_called_once_with(token="dummy", tag_id=tag_id, language="EN")
    assert response.json()["id"] == str(tag_id)


def test_get_tag_by_id_not_found():
    tag_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.tags.tag_views.get_cms_tag_detail",
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag with id '{tag_id}' not found",
        ),
    ):
        response = client.get(
            f"/api/v1/cms/tags/{tag_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_update_tag_success(sample_tag_dto):
    tag_id = sample_tag_dto.id
    payload = {
        "metadata": [
            {
                "language": "EN",
                "name": "Updated",
                "description": "New desc"
            }
        ]
    }

    with patch(
        "pecha_api.plans.tags.tag_views.update_existing_tag",
        return_value=sample_tag_dto,
    ) as mock_update:
        response = client.put(
            f"/api/v1/cms/tags/{tag_id}",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_update.assert_called_once()
    assert mock_update.call_args.kwargs["tag_id"] == tag_id
    assert len(mock_update.call_args.kwargs["update_tag_request"].metadata) == 1
    assert mock_update.call_args.kwargs["update_tag_request"].metadata[0].name == "Updated"


def test_update_tag_accepts_empty_body(sample_tag_dto):
    tag_id = sample_tag_dto.id
    with patch(
        "pecha_api.plans.tags.tag_views.update_existing_tag",
        return_value=sample_tag_dto,
    ) as mock_update:
        response = client.put(
            f"/api/v1/cms/tags/{tag_id}",
            json={},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_update.assert_called_once()


def test_delete_tag_success():
    tag_id = uuid.uuid4()
    with patch("pecha_api.plans.tags.tag_views.delete_tag") as mock_delete:
        response = client.delete(
            f"/api/v1/cms/tags/{tag_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_delete.assert_called_once_with(token="dummy", tag_id=tag_id)


def test_delete_tag_not_found():
    tag_id = uuid.uuid4()
    with patch(
        "pecha_api.plans.tags.tag_views.delete_tag",
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag with id '{tag_id}' not found",
        ),
    ):
        response = client.delete(
            f"/api/v1/cms/tags/{tag_id}",
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_create_tag_with_plan_ids(sample_tag_dto):
    plan_id = uuid.uuid4()
    payload = {
        "metadata": [{"language": "EN", "name": "Sleep"}],
        "plan_ids": [str(plan_id)]
    }

    with patch(
        "pecha_api.plans.tags.tag_views.create_new_tag",
        return_value=sample_tag_dto,
    ) as mock_create:
        response = client.post(
            "/api/v1/cms/tags",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert mock_create.call_args.kwargs["create_tag_request"].plan_ids == [plan_id]


def test_create_tag_with_segment_ids(sample_tag_dto):
    segment_id = "06gCCWizfl2OLp0ehIpwB"
    payload = {
        "metadata": [{"language": "EN", "name": "Segments"}],
        "segment_ids": [segment_id]
    }

    with patch(
        "pecha_api.plans.tags.tag_views.create_new_tag",
        return_value=sample_tag_dto,
    ) as mock_create:
        response = client.post(
            "/api/v1/cms/tags",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert mock_create.call_args.kwargs["create_tag_request"].segment_ids == [segment_id]
