"""Simple tests for user metadata without database dependency."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from uuid import uuid4

from pecha_api.app import api
from pecha_api.users.users_models import Users
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.users.user_metadata_response_models import UserMetadataDTO

client = TestClient(api)


class TestUserMetadataAPI:
    """Test user metadata API endpoints."""

    def test_update_language_success(self):
        """Test updating user language successfully."""
        mock_response = UserMetadataDTO(language=LanguageCode.BO, timezone="Asia/Kathmandu")
        with patch("pecha_api.users.users_views.update_user_language") as mock_update:
            mock_update.return_value = mock_response
            response = client.put(
                "/users/me/language",
                json={"language": "BO"},
                headers={"Authorization": "Bearer testtoken"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["language"] == "BO"
            assert data["timezone"] == "Asia/Kathmandu"

    def test_update_language_invalid_language(self):
        """Test updating user language with invalid language returns 422."""
        response = client.put(
            "/users/me/language",
            json={"language": "INVALID"},
            headers={"Authorization": "Bearer testtoken"}
        )
        
        assert response.status_code == 422

    def test_update_language_unauthenticated(self):
        """Test updating language without authentication returns 403."""
        response = client.put(
            "/users/me/language",
            json={"language": "BO"}
        )
        
        assert response.status_code == 403


class TestVerseOfDayTimezoneSync:
    """Test verse of day endpoint timezone sync."""

    def test_verse_of_day_anonymous_request(self):
        """Test anonymous request to verse of day does not create metadata."""
        with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service") as mock_service:
            mock_service.return_value = {"verse_of_day": None}
            response = client.get("/verse-of-day/today")
            
            assert response.status_code == 200

    def test_verse_of_day_authenticated_with_valid_timezone(self):
        """Test authenticated request with valid X-Timezone syncs metadata."""
        with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service") as mock_service, \
             patch("pecha_api.verse_of_day.verse_of_day_views.validate_and_extract_user_details") as mock_validate, \
             patch("pecha_api.users.user_metadata_service.sync_user_timezone") as mock_sync:
            
            mock_service.return_value = {"verse_of_day": None}
            mock_user = Users(id=uuid4(), email="test@example.com", firstname="Test", lastname="User", registration_source="EMAIL")
            mock_validate.return_value = mock_user
            
            headers = {"Authorization": "Bearer testtoken", "X-Timezone": "America/New_York"}
            response = client.get("/verse-of-day/today", headers=headers)
            
            assert response.status_code == 200
            mock_sync.assert_called_once_with(mock_user.id, "America/New_York")

    def test_verse_of_day_authenticated_without_timezone_header(self):
        """Test authenticated request without X-Timezone header does not sync."""
        with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service") as mock_service, \
             patch("pecha_api.users.user_metadata_service.sync_user_timezone") as mock_sync:
            
            mock_service.return_value = {"verse_of_day": None}
            
            headers = {"Authorization": "Bearer testtoken"}
            response = client.get("/verse-of-day/today", headers=headers)
            
            assert response.status_code == 200
            mock_sync.assert_not_called()

    def test_verse_of_day_authenticated_with_invalid_timezone(self):
        """Test authenticated request with invalid X-Timezone still returns verse."""
        with patch("pecha_api.verse_of_day.verse_of_day_views.get_verse_of_day_today_service") as mock_service, \
             patch("pecha_api.verse_of_day.verse_of_day_views.validate_and_extract_user_details") as mock_validate, \
             patch("pecha_api.users.user_metadata_service.sync_user_timezone") as mock_sync:
            
            mock_service.return_value = {"verse_of_day": None}
            mock_user = Users(id=uuid4(), email="test@example.com", firstname="Test", lastname="User", registration_source="EMAIL")
            mock_validate.return_value = mock_user
            mock_sync.side_effect = Exception("Invalid timezone")
            
            headers = {"Authorization": "Bearer testtoken", "X-Timezone": "Invalid/Timezone"}
            response = client.get("/verse-of-day/today", headers=headers)
            
            # Should still return verse (error is silently caught)
            assert response.status_code == 200


def test_user_metadata_is_removed_with_its_user() -> None:
    """Regression: the relationship carried no cascade, so deleting a user made
    the ORM NULL out user_metadata.user_id - which the NOT NULL column rejects,
    so the delete failed and the FK's ON DELETE CASCADE never ran."""
    from sqlalchemy import inspect

    relationship = inspect(Users).relationships["user_metadata"]

    assert "delete-orphan" in relationship.cascade
    assert relationship.passive_deletes is True
