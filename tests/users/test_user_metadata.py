import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from uuid import uuid4

from pecha_api.app import api
from pecha_api.auth.auth_enums import RegistrationSource
from pecha_api.users.users_models import Base, Users
from pecha_api.users.user_metadata_model import UserMetadata
from pecha_api.users.user_metadata_repository import (
    get_user_metadata_by_user_id,
    upsert_user_timezone,
    upsert_user_language,
)
from pecha_api.plans.plans_enums import LanguageCode
from tests.postgres_integration import postgres_integration_url

DATABASE_URL = postgres_integration_url()
if not DATABASE_URL:
    pytest.skip(
        "Set TEST_DATABASE_URL to a reachable PostgreSQL database to run these tests.",
        allow_module_level=True,
    )

engine = create_engine(DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
client = TestClient(api)


@pytest.fixture(scope="module")
def db():
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Users.__table__,
            UserMetadata.__table__,
        ],
    )
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(
        bind=engine,
        tables=[
            Users.__table__,
            UserMetadata.__table__,
        ],
    )


@pytest.fixture
def test_user(db):
    user = Users(
        email="testuser@example.com",
        firstname="Test",
        lastname="User",
        password="password",
        registration_source=RegistrationSource.EMAIL.name
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    yield user
    db.delete(user)
    db.commit()


class TestUserMetadataRepository:
    """Test user metadata repository functions."""

    def test_get_user_metadata_by_user_id_not_found(self, db):
        """Test getting metadata for non-existent user returns None."""
        user_id = uuid4()
        metadata = get_user_metadata_by_user_id(db, user_id)
        assert metadata is None

    def test_upsert_user_timezone_creates_new_record(self, db, test_user):
        """Test upserting timezone creates new metadata record with defaults."""
        timezone = "America/New_York"
        metadata = upsert_user_timezone(db, test_user.id, timezone)
        
        assert metadata is not None
        assert metadata.user_id == test_user.id
        assert metadata.timezone == timezone
        assert metadata.language == LanguageCode.EN
        assert metadata.created_at is not None
        assert metadata.updated_at is not None

    def test_upsert_user_timezone_updates_existing_record(self, db, test_user):
        """Test upserting timezone updates existing metadata record."""
        # Create initial metadata
        initial_metadata = upsert_user_timezone(db, test_user.id, "Asia/Kathmandu")
        initial_updated_at = initial_metadata.updated_at
        
        # Update timezone
        new_timezone = "Europe/London"
        updated_metadata = upsert_user_timezone(db, test_user.id, new_timezone)
        
        assert updated_metadata.id == initial_metadata.id
        assert updated_metadata.timezone == new_timezone
        assert updated_metadata.language == LanguageCode.EN
        assert updated_metadata.updated_at > initial_updated_at

    def test_upsert_user_language_creates_new_record(self, db, test_user):
        """Test upserting language creates new metadata record with defaults."""
        language = LanguageCode.BO
        metadata = upsert_user_language(db, test_user.id, language)
        
        assert metadata is not None
        assert metadata.user_id == test_user.id
        assert metadata.language == language
        assert metadata.timezone == "Asia/Kathmandu"
        assert metadata.created_at is not None
        assert metadata.updated_at is not None

    def test_upsert_user_language_updates_existing_record(self, db, test_user):
        """Test upserting language updates existing metadata record."""
        # Create initial metadata
        initial_metadata = upsert_user_language(db, test_user.id, LanguageCode.EN)
        initial_updated_at = initial_metadata.updated_at
        
        # Update language
        new_language = LanguageCode.ZH
        updated_metadata = upsert_user_language(db, test_user.id, new_language)
        
        assert updated_metadata.id == initial_metadata.id
        assert updated_metadata.language == new_language
        assert updated_metadata.timezone == "Asia/Kathmandu"
        assert updated_metadata.updated_at > initial_updated_at

    def test_metadata_cascade_delete(self, db, test_user):
        """Test that metadata is deleted when user is deleted."""
        # Create metadata
        upsert_user_timezone(db, test_user.id, "UTC")
        
        # Verify metadata exists
        metadata = get_user_metadata_by_user_id(db, test_user.id)
        assert metadata is not None
        
        # Delete user
        db.delete(test_user)
        db.commit()
        
        # Verify metadata is deleted
        metadata = db.query(UserMetadata).filter(
            UserMetadata.user_id == test_user.id
        ).first()
        assert metadata is None


class TestUserMetadataAPI:
    """Test user metadata API endpoints."""

    def test_update_language_success(self):
        """Test updating user language successfully."""
        from pecha_api.users.user_metadata_response_models import UserMetadataDTO
        
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
