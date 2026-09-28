import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.group_accumulator.group_accumulator_response_models import (
    GroupAccumulatorDTO,
    GroupAccumulatorDetailDTO,
    GroupAccumulatorsResponse,
    GroupAccumulatorHistoryResponse,
    GroupAccumulatorHistoryItemDTO,
    SubmitGroupCountRequest,
)

client = TestClient(api)


class TestDataFactory:
    """Factory for creating test data objects."""

    @staticmethod
    def create_group_accumulator_dto(
        id=None,
        group_id=None,
        accumulator_id=None,
        text_id=None,
        mantra_id=None,
        target_count=108000,
    ) -> GroupAccumulatorDTO:
        return GroupAccumulatorDTO(
            id=id or uuid4(),
            preset_accumulator_id=accumulator_id,
            text_id=text_id,
            mantra_id=mantra_id,
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
    def create_history_item(
        history_id=None,
        user_id=None,
        count=100,
    ) -> GroupAccumulatorHistoryItemDTO:
        return GroupAccumulatorHistoryItemDTO(
            id=history_id or uuid4(),
            user_id=user_id or uuid4(),
            count=count,
            created_at=datetime.utcnow(),
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

    @staticmethod
    def create_history_response(
        accumulator_detail=None,
        history_items=None,
        total=0,
    ) -> GroupAccumulatorHistoryResponse:
        return GroupAccumulatorHistoryResponse(
            group_accumulator=accumulator_detail or TestDataFactory.create_group_accumulator_detail(),
            history=history_items or [],
            total=total,
            skip=0,
            limit=20,
        )


class TestGetGroupAccumulators:
    """Test cases for GET /group-accumulators/{group_id}/accumulators endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulators_service_cached', new_callable=AsyncMock)
    def test_get_group_accumulators_success(self, mock_service):
        """Test successful retrieval of group accumulators."""
        group_id = uuid4()
        text_id = str(uuid4())
        mantra_id = uuid4()
        accumulators = [
            TestDataFactory.create_group_accumulator_dto(
                group_id=group_id,
                text_id=text_id,
            ),
            TestDataFactory.create_group_accumulator_dto(
                group_id=group_id,
                mantra_id=mantra_id,
            ),
        ]
        mock_service.return_value = TestDataFactory.create_accumulators_response(
            accumulators=accumulators,
            total=2,
        )

        response = client.get(f"/group-accumulators/{group_id}/accumulators")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["accumulators"]) == 2
        assert data["total"] == 2
        assert data["skip"] == 0
        assert data["limit"] == 20
        assert data["accumulators"][0]["text_id"] == str(text_id)
        assert data["accumulators"][0]["mantra_id"] is None
        assert data["accumulators"][1]["text_id"] is None
        assert data["accumulators"][1]["mantra_id"] == str(mantra_id)
        mock_service.assert_called_once_with(group_id=group_id, skip=0, limit=20, token=None, timezone_name=None, language=None)

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulators_service_cached', new_callable=AsyncMock)
    def test_get_group_accumulators_with_pagination(self, mock_service):
        """Test get group accumulators with custom pagination."""
        group_id = uuid4()
        mock_service.return_value = TestDataFactory.create_accumulators_response(
            accumulators=[TestDataFactory.create_group_accumulator_dto()],
            total=10,
        )

        response = client.get(
            f"/group-accumulators/{group_id}/accumulators",
            params={"skip": 5, "limit": 5}
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(group_id=group_id, skip=5, limit=5, token=None, timezone_name=None, language=None)

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulators_service_cached', new_callable=AsyncMock)
    def test_get_group_accumulators_empty(self, mock_service):
        """Test get group accumulators when no accumulators exist."""
        group_id = uuid4()
        mock_service.return_value = TestDataFactory.create_accumulators_response(
            accumulators=[],
            total=0,
        )

        response = client.get(f"/group-accumulators/{group_id}/accumulators")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["accumulators"]) == 0
        assert data["total"] == 0

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulators_service_cached', new_callable=AsyncMock)
    def test_get_group_accumulators_group_not_found(self, mock_service):
        """Test get group accumulators when group doesn't exist."""
        from fastapi import HTTPException
        group_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group not found"}
        )

        response = client.get(f"/group-accumulators/{group_id}/accumulators")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["error"] == "NOT_FOUND"


class TestGetGroupAccumulator:
    """Test cases for GET /group-accumulators/{group_accumulator_id} endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_service_cached', new_callable=AsyncMock)
    def test_get_group_accumulator_success(self, mock_service):
        """Test successful retrieval of group accumulator details."""
        group_accumulator_id = uuid4()
        mock_service.return_value = TestDataFactory.create_group_accumulator_detail(
            id=group_accumulator_id,
            total_count=5000,
        )

        response = client.get(f"/group-accumulators/{group_accumulator_id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(group_accumulator_id)
        assert data["total_count"] == 5000
        mock_service.assert_called_once_with(
            group_accumulator_id=group_accumulator_id,
            timezone_name=None,
            token=None,
            language=None,
        )

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_service_cached', new_callable=AsyncMock)
    def test_get_group_accumulator_not_found(self, mock_service):
        """Test get group accumulator when accumulator doesn't exist."""
        from fastapi import HTTPException
        accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
        )

        response = client.get(f"/group-accumulators/{accumulator_id}")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["error"] == "NOT_FOUND"


class TestSubmitGroupCount:
    """Test cases for POST /group-accumulators/{group_accumulator_id}/count endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_views.submit_group_count_service')
    def test_submit_group_count_success(self, mock_service):
        """Test successful submission of group count."""
        accumulator_id = uuid4()
        user_id = uuid4()
        mock_service.return_value = (
            TestDataFactory.create_history_item(
                user_id=user_id,
                count=100,
            ),
            True,  # is_created
        )

        payload = {"current_count": 100}
        response = client.post(
            f"/group-accumulators/{accumulator_id}",
            json=payload,
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["count"] == 100
        assert data["user_id"] == str(user_id)
        mock_service.assert_called_once()

    @patch('pecha_api.group_accumulator.group_accumulator_views.submit_group_count_service')
    def test_submit_group_count_unauthorized(self, mock_service):
        """Test submit group count without authorization."""
        accumulator_id = uuid4()
        payload = {"current_count": 100}

        response = client.post(
            f"/group-accumulators/{accumulator_id}",
            json=payload,
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_service.assert_not_called()

    @patch('pecha_api.group_accumulator.group_accumulator_views.submit_group_count_service')
    def test_submit_group_count_invalid_payload(self, mock_service):
        """Test submit group count with invalid payload."""
        accumulator_id = uuid4()
        payload = {"current_count": -10}

        response = client.post(
            f"/group-accumulators/{accumulator_id}",
            json=payload,
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_service.assert_not_called()

    @patch('pecha_api.group_accumulator.group_accumulator_views.submit_group_count_service')
    def test_submit_group_count_zero_delta(self, mock_service):
        """Test submit group count when delta is zero (no change) returns 200 OK."""
        accumulator_id = uuid4()
        user_id = uuid4()
        mock_service.return_value = (
            TestDataFactory.create_history_item(
                user_id=user_id,
                count=0,
            ),
            False,  # is_created = False for no-op
        )

        payload = {"current_count": 50}
        response = client.post(
            f"/group-accumulators/{accumulator_id}",
            json=payload,
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_200_OK  # 200 for no-op, not 201
        data = response.json()
        assert data["count"] == 0

    @patch('pecha_api.group_accumulator.group_accumulator_views.submit_group_count_service')
    def test_submit_group_count_not_member(self, mock_service):
        """Test submit group count when user is not a group member."""
        from fastapi import HTTPException
        accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "You must be a member of this group"}
        )

        payload = {"current_count": 100}
        response = client.post(
            f"/group-accumulators/{accumulator_id}",
            json=payload,
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "member" in response.json()["detail"]["message"]


class TestGetGroupAccumulatorHistory:
    """Test cases for GET /group-accumulators/{group_accumulator_id}/count endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_history_service')
    def test_get_history_success(self, mock_service):
        """Test successful retrieval of group accumulator history."""
        accumulator_id = uuid4()
        history_items = [
            TestDataFactory.create_history_item(count=100),
            TestDataFactory.create_history_item(count=50),
        ]
        mock_service.return_value = TestDataFactory.create_history_response(
            history_items=history_items,
            total=2,
        )

        response = client.get(f"/group-accumulators/{accumulator_id}/history")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["history"]) == 2
        assert data["total"] == 2
        assert data["skip"] == 0
        assert data["limit"] == 20
        mock_service.assert_called_once_with(
            group_accumulator_id=accumulator_id,
            skip=0,
            limit=20,
            today_only=False,
            timezone_name=None,
        )

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_history_service')
    def test_get_history_with_pagination(self, mock_service):
        """Test get history with custom pagination parameters."""
        accumulator_id = uuid4()
        mock_service.return_value = TestDataFactory.create_history_response(
            history_items=[TestDataFactory.create_history_item()],
            total=10,
        )

        response = client.get(
            f"/group-accumulators/{accumulator_id}/history",
            params={"skip": 5, "limit": 5}
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once_with(
            group_accumulator_id=accumulator_id,
            skip=5,
            limit=5,
            today_only=False,
            timezone_name=None,
        )

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_history_service')
    def test_get_history_empty(self, mock_service):
        """Test get history when no history exists."""
        accumulator_id = uuid4()
        mock_service.return_value = TestDataFactory.create_history_response(
            history_items=[],
            total=0,
        )

        response = client.get(f"/group-accumulators/{accumulator_id}/history")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["history"]) == 0
        assert data["total"] == 0

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_history_service')
    def test_get_history_not_found(self, mock_service):
        """Test get history when accumulator doesn't exist."""
        from fastapi import HTTPException
        accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
        )

        response = client.get(f"/group-accumulators/{accumulator_id}/history")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteGroupAccumulator:
    """Test cases for DELETE /group-accumulators/{group_accumulator_id} endpoint."""

    @patch('pecha_api.group_accumulator.group_accumulator_views.delete_group_accumulator_user_service')
    def test_delete_group_accumulator_success(self, mock_service):
        """Test successful reset of user's active participation session."""
        group_accumulator_id = uuid4()
        mock_service.return_value = None

        response = client.delete(
            f"/group-accumulators/{group_accumulator_id}",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_service.assert_called_once_with(
            token="valid_token",
            group_accumulator_id=group_accumulator_id,
        )

    @patch('pecha_api.group_accumulator.group_accumulator_views.delete_group_accumulator_user_service')
    def test_delete_group_accumulator_unauthorized(self, mock_service):
        """Test delete group accumulator without authorization."""
        group_accumulator_id = uuid4()

        response = client.delete(
            f"/group-accumulators/{group_accumulator_id}"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_service.assert_not_called()

    @patch('pecha_api.group_accumulator.group_accumulator_views.delete_group_accumulator_user_service')
    def test_delete_group_accumulator_not_member(self, mock_service):
        """Test delete group accumulator when user is not a group member."""
        from fastapi import HTTPException
        group_accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "You must be a member of this group"}
        )

        response = client.delete(
            f"/group-accumulators/{group_accumulator_id}",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"]["message"] == "You must be a member of this group"

    @patch('pecha_api.group_accumulator.group_accumulator_views.delete_group_accumulator_user_service')
    def test_delete_group_accumulator_not_found(self, mock_service):
        """Test delete group accumulator when it doesn't exist."""
        from fastapi import HTTPException
        group_accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NOT_FOUND", "message": "Group accumulator not found"}
        )

        response = client.delete(
            f"/group-accumulators/{group_accumulator_id}",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"]["error"] == "NOT_FOUND"

    @patch('pecha_api.group_accumulator.group_accumulator_views.delete_group_accumulator_user_service')
    def test_delete_group_accumulator_wrong_group(self, mock_service):
        """Test delete group accumulator when it belongs to different group."""
        from fastapi import HTTPException
        group_accumulator_id = uuid4()
        mock_service.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "FORBIDDEN", "message": "Group accumulator does not belong to this group"}
        )

        response = client.delete(
            f"/group-accumulators/{group_accumulator_id}",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"]["error"] == "FORBIDDEN"


class TestJoinGroupAccumulatorView:
    @patch('pecha_api.group_accumulator.group_accumulator_views.join_group_accumulator_service')
    def test_join_success(self, mock_service):
        group_accumulator_id = uuid4()
        response = client.post(
            f"/group-accumulators/{group_accumulator_id}/join",
            headers={"Authorization": "Bearer valid_token"},
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_service.assert_called_once_with(
            token="valid_token",
            group_accumulator_id=group_accumulator_id,
        )


class TestGetGroupAccumulatorMembersView:
    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_members_service')
    def test_get_members_success(self, mock_service):
        from pecha_api.group_accumulator.group_accumulator_response_models import (
            GroupAccumulatorMembersResponse,
            GroupAccumulatorMemberDTO,
        )

        group_accumulator_id = uuid4()
        mock_service.return_value = GroupAccumulatorMembersResponse(
            members=[
                GroupAccumulatorMemberDTO(
                    user_id=uuid4(),
                    username="testuser",
                    fullname="Test User",
                    avatar_url=None,
                    joined_at=datetime.utcnow(),
                    total_count=500,
                    today_count=108,
                )
            ],
            member_count=1,
            total=1,
            skip=0,
            limit=20,
        )

        response = client.get(f"/group-accumulators/{group_accumulator_id}/members")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["member_count"] == 1
        assert response.json()["total"] == 1
        assert response.json()["members"][0]["total_count"] == 500
        assert response.json()["members"][0]["today_count"] == 108
        assert len(response.json()["members"]) == 1
        mock_service.assert_called_once()
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["sort_by"].value == "total"

    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_members_service')
    def test_get_members_sort_by_today(self, mock_service):
        from pecha_api.group_accumulator.group_accumulator_response_models import (
            GroupAccumulatorMembersResponse,
        )

        group_accumulator_id = uuid4()
        mock_service.return_value = GroupAccumulatorMembersResponse(
            members=[],
            member_count=0,
            total=0,
            skip=0,
            limit=20,
        )

        response = client.get(
            f"/group-accumulators/{group_accumulator_id}/members?sort_by=today",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_service.assert_called_once()
        assert mock_service.call_args.kwargs["sort_by"].value == "today"


class TestJoinGroupAccumulatorView:
    @patch('pecha_api.group_accumulator.group_accumulator_views.join_group_accumulator_service')
    def test_join_success(self, mock_service):
        group_accumulator_id = uuid4()
        response = client.post(
            f"/group-accumulators/{group_accumulator_id}/join",
            headers={"Authorization": "Bearer valid_token"},
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_service.assert_called_once_with(
            token="valid_token",
            group_accumulator_id=group_accumulator_id,
        )


class TestGetGroupAccumulatorUserSessionsView:
    @patch('pecha_api.group_accumulator.group_accumulator_views.get_group_accumulator_user_sessions_service')
    def test_get_user_sessions_success(self, mock_service):
        from pecha_api.group_accumulator.group_accumulator_response_models import (
            GroupAccumulatorUserSessionsResponse,
            GroupAccumulatorUserSessionDTO,
            GroupAccumulatorContributionDTO,
            GroupAccumulatorDTO,
        )

        group_accumulator_id = uuid4()
        group_id = uuid4()
        session_id = uuid4()
        created_at = datetime.utcnow()
        mock_service.return_value = GroupAccumulatorUserSessionsResponse(
            group_accumulator=GroupAccumulatorDTO(
                id=group_accumulator_id,
                group_id=group_id,
                preset_accumulator_id=None,
                title="Group Practice",
                image=None,
                image_key=None,
                target_count=100000,
                start_date=None,
                end_date=None,
                is_joined=None,
                created_at=created_at,
                updated_at=None,
            ),
            sessions=[
                GroupAccumulatorUserSessionDTO(
                    id=session_id,
                    is_active=True,
                    total_counted=108,
                    created_at=created_at,
                    deleted_at=None,
                    contributions=[
                        GroupAccumulatorContributionDTO(
                            id=uuid4(),
                            count=108,
                            created_at=created_at,
                        )
                    ],
                )
            ],
            total=1,
            skip=0,
            limit=20,
        )

        response = client.get(
            f"/group-accumulators/{group_accumulator_id}/user-sessions",
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1
        assert response.json()["sessions"][0]["is_active"] is True
        assert response.json()["sessions"][0]["total_counted"] == 108
        mock_service.assert_called_once_with(
            token="valid_token",
            group_accumulator_id=group_accumulator_id,
            skip=0,
            limit=20,
        )

    def test_get_user_sessions_unauthorized(self):
        response = client.get(f"/group-accumulators/{uuid4()}/user-sessions")
        assert response.status_code == status.HTTP_403_FORBIDDEN
