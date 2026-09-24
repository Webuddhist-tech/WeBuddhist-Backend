import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.group_accumulator.group_accumulator_response_models import (
    GroupAccumulatorDTO,
    GroupAccumulatorsResponse,
    GroupAccumulatorDetailDTO,
    CreateGroupAccumulatorRequest,
    UpdateGroupAccumulatorRequest,
)

client = TestClient(api)


class TestDataFactory:
    """Factory for creating test data objects."""

    @staticmethod
    def create_group_accumulator_dto(
        id=None,
        group_id=None,
        accumulator_id=None,
        target_count=108000,
    ) -> GroupAccumulatorDTO:
        return GroupAccumulatorDTO(
            id=id or uuid4(),
            preset_accumulator_id=accumulator_id,
            group_id=group_id or uuid4(),
            target_count=target_count,
            start_date=datetime.utcnow(),
            end_date=None,
            created_at=datetime.utcnow(),
            updated_at=None,
        )

    @staticmethod
    def create_group_accumulator_detail(
        id=None,
        group_id=None,
        accumulator_id=None,
        target_count=108000,
        total_count=5000,
    ) -> GroupAccumulatorDetailDTO:
        return GroupAccumulatorDetailDTO(
            id=id or uuid4(),
            preset_accumulator_id=accumulator_id,
            group_id=group_id or uuid4(),
            target_count=target_count,
            start_date=datetime.utcnow(),
            end_date=None,
            total_count=total_count,
            created_at=datetime.utcnow(),
            updated_at=None,
        )

    @staticmethod
    def create_accumulators_response(
        accumulators=None,
        total=0,
    ) -> GroupAccumulatorsResponse:
        return GroupAccumulatorsResponse(
            accumulators=accumulators or [],
            total=total,
            skip=0,
            limit=20,
        )


class TestCreateGroupAccumulator:
    """Test cases for POST /cms/groups/{group_id}/accumulators endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.create_group_accumulator_cms_service')
    def test_create_group_accumulator_success(self, mock_service):
        """Test successful creation of group accumulator."""
        group_id = uuid4()
        accumulator_id = uuid4()
        group_accumulator_id = uuid4()
        
        mock_service.return_value = TestDataFactory.create_group_accumulator_dto(
            id=group_accumulator_id,
            group_id=group_id,
            accumulator_id=accumulator_id,
            target_count=108000,
        )

        payload = {
            "accumulator_id": str(accumulator_id),
            "target_count": 108000,
            "start_date": datetime.utcnow().isoformat(),
            "end_date": None,
        }

        response = client.post(
            f"/cms/groups/{group_id}/accumulators",
            json=payload,
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["id"] == str(group_accumulator_id)
        assert data["group_id"] == str(group_id)
        assert data["preset_accumulator_id"] == str(accumulator_id)
        assert data["target_count"] == 108000
        mock_service.assert_called_once()

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.create_group_accumulator_cms_service')
    def test_create_group_accumulator_unauthorized(self, mock_service):
        """Test create group accumulator without authorization."""
        group_id = uuid4()
        payload = {
            "target_count": 108000,
        }

        response = client.post(
            f"/cms/groups/{group_id}/accumulators",
            json=payload,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_service.assert_not_called()

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.create_group_accumulator_cms_service')
    def test_create_group_accumulator_group_not_found(self, mock_service):
        """Test create group accumulator when group doesn't exist."""
        from fastapi import HTTPException
        group_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group not found"}
        )

        payload = {
            "target_count": 108000,
        }

        response = client.post(
            f"/cms/groups/{group_id}/accumulators",
            json=payload,
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["error"] == "NOT_FOUND"

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.create_group_accumulator_cms_service')
    def test_create_group_accumulator_invalid_target_count(self, mock_service):
        """Test create group accumulator with invalid target count."""
        group_id = uuid4()
        payload = {
            "target_count": 0,
        }

        response = client.post(
            f"/cms/groups/{group_id}/accumulators",
            json=payload,
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_service.assert_not_called()


class TestGetGroupAccumulators:
    """Test cases for GET /cms/groups/{group_id}/accumulators endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.get_group_accumulators_cms_service')
    def test_get_group_accumulators_success(self, mock_service):
        """Test successful retrieval of group accumulators."""
        group_id = uuid4()
        accumulators = [
            TestDataFactory.create_group_accumulator_dto(group_id=group_id),
            TestDataFactory.create_group_accumulator_dto(group_id=group_id),
        ]
        mock_service.return_value = TestDataFactory.create_accumulators_response(
            accumulators=accumulators,
            total=2,
        )

        response = client.get(
            f"/cms/groups/{group_id}/accumulators",
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["accumulators"]) == 2
        assert data["total"] == 2
        assert data["skip"] == 0
        assert data["limit"] == 20
        mock_service.assert_called_once_with(token="admin_token", group_id=group_id, skip=0, limit=20, search=None)

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.get_group_accumulators_cms_service')
    def test_get_group_accumulators_with_pagination(self, mock_service):
        """Test get group accumulators with custom pagination."""
        group_id = uuid4()
        mock_service.return_value = TestDataFactory.create_accumulators_response(
            accumulators=[TestDataFactory.create_group_accumulator_dto()],
            total=10,
        )

        response = client.get(
            f"/cms/groups/{group_id}/accumulators",
            params={"skip": 5, "limit": 5},
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(token="admin_token", group_id=group_id, skip=5, limit=5, search=None)

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.get_group_accumulators_cms_service')
    def test_get_group_accumulators_empty(self, mock_service):
        """Test get group accumulators when no accumulators exist."""
        group_id = uuid4()
        mock_service.return_value = TestDataFactory.create_accumulators_response(
            accumulators=[],
            total=0,
        )

        response = client.get(
            f"/cms/groups/{group_id}/accumulators",
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["accumulators"]) == 0
        assert data["total"] == 0

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.get_group_accumulators_cms_service')
    def test_get_group_accumulators_unauthorized(self, mock_service):
        """Test get group accumulators without authorization."""
        group_id = uuid4()

        response = client.get(f"/cms/groups/{group_id}/accumulators")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_service.assert_not_called()


class TestGetSingleGroupAccumulator:
    """Test cases for GET /cms/groups/{group_id}/accumulators/{group_accumulator_id} endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.get_group_accumulator_cms_service')
    def test_get_single_group_accumulator_success(self, mock_service):
        """Test successful retrieval of single group accumulator."""
        group_id = uuid4()
        group_accumulator_id = uuid4()
        mock_service.return_value = TestDataFactory.create_group_accumulator_detail(
            id=group_accumulator_id,
            group_id=group_id,
            total_count=5000,
        )

        response = client.get(
            f"/cms/groups/{group_id}/accumulators/{group_accumulator_id}",
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(group_accumulator_id)
        assert data["group_id"] == str(group_id)
        assert data["total_count"] == 5000
        mock_service.assert_called_once_with(token="admin_token", group_id=group_id, group_accumulator_id=group_accumulator_id)

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.get_group_accumulator_cms_service')
    def test_get_single_group_accumulator_not_found(self, mock_service):
        """Test get single group accumulator when it doesn't exist."""
        from fastapi import HTTPException
        group_id = uuid4()
        accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
        )

        response = client.get(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}",
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["error"] == "NOT_FOUND"

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.get_group_accumulator_cms_service')
    def test_get_single_group_accumulator_unauthorized(self, mock_service):
        """Test get single group accumulator without authorization."""
        group_id = uuid4()
        accumulator_id = uuid4()

        response = client.get(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_service.assert_not_called()


class TestUpdateGroupAccumulator:
    """Test cases for PUT /cms/groups/{group_id}/accumulators/{group_accumulator_id} endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.update_group_accumulator_cms_service')
    def test_update_group_accumulator_success(self, mock_service):
        """Test successful update of group accumulator."""
        group_id = uuid4()
        group_accumulator_id = uuid4()
        mock_service.return_value = TestDataFactory.create_group_accumulator_dto(
            id=group_accumulator_id,
            group_id=group_id,
            target_count=216000,
        )

        payload = {
            "target_count": 216000,
        }

        response = client.put(
            f"/cms/groups/{group_id}/accumulators/{group_accumulator_id}",
            json=payload,
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(group_accumulator_id)
        assert data["target_count"] == 216000
        mock_service.assert_called_once()

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.update_group_accumulator_cms_service')
    def test_update_group_accumulator_not_found(self, mock_service):
        """Test update group accumulator when it doesn't exist."""
        from fastapi import HTTPException
        group_id = uuid4()
        accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
        )

        payload = {
            "target_count": 216000,
        }

        response = client.put(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}",
            json=payload,
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["error"] == "NOT_FOUND"

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.update_group_accumulator_cms_service')
    def test_update_group_accumulator_wrong_group(self, mock_service):
        """Test update group accumulator when it belongs to different group."""
        from fastapi import HTTPException
        group_id = uuid4()
        accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "Group accumulator does not belong to this group"}
        )

        payload = {
            "target_count": 216000,
        }

        response = client.put(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}",
            json=payload,
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"]["error"] == "FORBIDDEN"

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.update_group_accumulator_cms_service')
    def test_update_group_accumulator_unauthorized(self, mock_service):
        """Test update group accumulator without authorization."""
        group_id = uuid4()
        accumulator_id = uuid4()
        payload = {
            "target_count": 216000,
        }

        response = client.put(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}",
            json=payload,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_service.assert_not_called()

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.update_group_accumulator_cms_service')
    def test_update_group_accumulator_partial_update(self, mock_service):
        """Test partial update of group accumulator."""
        group_id = uuid4()
        group_accumulator_id = uuid4()
        accumulator_id = uuid4()
        mock_service.return_value = TestDataFactory.create_group_accumulator_dto(
            id=group_accumulator_id,
            group_id=group_id,
            accumulator_id=accumulator_id,
        )

        payload = {
            "accumulator_id": str(accumulator_id),
        }

        response = client.put(
            f"/cms/groups/{group_id}/accumulators/{group_accumulator_id}",
            json=payload,
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["preset_accumulator_id"] == str(accumulator_id)


class TestDeleteGroupAccumulator:
    """Test cases for DELETE /cms/groups/{group_id}/accumulators/{group_accumulator_id} endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.delete_group_accumulator_cms_service')
    def test_delete_group_accumulator_success(self, mock_service):
        """Test successful deletion of group accumulator."""
        group_id = uuid4()
        accumulator_id = uuid4()
        mock_service.return_value = None

        response = client.delete(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}",
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_service.assert_called_once_with(
            token="admin_token",
            group_id=group_id,
            group_accumulator_id=accumulator_id,
        )

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.delete_group_accumulator_cms_service')
    def test_delete_group_accumulator_not_found(self, mock_service):
        """Test delete group accumulator when it doesn't exist."""
        from fastapi import HTTPException
        group_id = uuid4()
        accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
        )

        response = client.delete(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}",
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["error"] == "NOT_FOUND"

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.delete_group_accumulator_cms_service')
    def test_delete_group_accumulator_wrong_group(self, mock_service):
        """Test delete group accumulator when it belongs to different group."""
        from fastapi import HTTPException
        group_id = uuid4()
        accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "Group accumulator does not belong to this group"}
        )

        response = client.delete(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}",
            headers={"Authorization": "Bearer admin_token"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"]["error"] == "FORBIDDEN"

    @patch('pecha_api.group_accumulator.group_accumulator_cms_views.delete_group_accumulator_cms_service')
    def test_delete_group_accumulator_unauthorized(self, mock_service):
        """Test delete group accumulator without authorization."""
        group_id = uuid4()
        accumulator_id = uuid4()

        response = client.delete(
            f"/cms/groups/{group_id}/accumulators/{accumulator_id}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_service.assert_not_called()
