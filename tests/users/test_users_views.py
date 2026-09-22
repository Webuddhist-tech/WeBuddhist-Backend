from unittest.mock import patch
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pecha_api.app import api
from pecha_api.error_contants import ErrorConstants
from pecha_api.users.user_response_models import (
    UserInfoResponse,
    UpdateUsernameResponse,
    OnboardingStatusResponse,
)
from fastapi import HTTPException
client = TestClient(api)


def test_get_user_information():
    user_info_response = UserInfoResponse(
        id=uuid4(),
        firstname="John",
        lastname="Doe",
        username="john.does",
        email="john.doe@gmail.com",
        title="",
        organization="",
        educations=[],
        avatar_url="",
        about_me="",
        followers=0,
        following=0,
        social_profiles=[]
    )
    with patch("pecha_api.users.users_views.get_user_info") as mock_get_user_info:
        mock_get_user_info.return_value = user_info_response
        response = client.get("/users/info", headers={"Authorization": "Bearer testtoken"})
        assert response.status_code == 200


def test_update_user_information():
    user_info_request = {
        "firstname": "John",
        "lastname": "Doe",
        "title": "Software Engineer",
        "organization": "Tech Corp",
        "educations": [
            "Bachelor's in Computer Science",
            "Master's in Data Science"
        ],
        "avatar_url": "https://example.com/avatar.jpg",
        "about_me": "Passionate about technology and solving complex problems.",
        "social_profiles": []
    }
    with patch("pecha_api.users.users_views.update_user_info") as mock_update_user_info:
        mock_update_user_info.return_value = None
        response = client.post("/users/info", json=user_info_request, headers={"Authorization": "Bearer testtoken"})
        assert response.status_code == 201

def test_upload_user_avatar_image():
    with patch("pecha_api.users.users_views.upload_user_image") as mock_upload_user_image:
        mock_upload_user_image.return_value = {"message": "Image uploaded successfully"}
        with open("tests/test_image_200kb.jpg", "rb") as image_file:
            response = client.post(
                "/users/upload",
                files={"file": ("test_image_200kb.jpg", image_file, "image/jpeg")},
                headers={"Authorization": "Bearer testtoken"}
            )
        assert response.status_code == 201
        assert response.json() == {"message": "Image uploaded successfully"}

def test_upload_non_image_file():
    with patch("pecha_api.users.users_views.upload_user_image",
               side_effect=HTTPException(status_code=400, detail="Only image files are allowed.")):
        with open("tests/test_file.txt", "rb") as non_image_file:
            response = client.post(
                "/users/upload",
                files={"file": ("test_file.txt", non_image_file, "text/plain")},
                headers={"Authorization": "Bearer testtoken"}
            )
        assert response.status_code == 400
        assert response.json() == {"detail": "Only image files are allowed."}


def test_upload_large_file():
    with patch("pecha_api.users.users_views.upload_user_image",
               side_effect=HTTPException(status_code=413, detail="File size exceeds 2 MB limit")):
        with open("tests/test_image_2mb.jpg", "rb") as large_file:
            response = client.post(
                "/users/upload",
                files={"file": ("test_large_image.jpg", large_file, "image/jpeg")},
                headers={"Authorization": "Bearer testtoken"}
            )
        assert response.status_code == 413
        assert response.json() == {"detail": "File size exceeds 2 MB limit"}


def test_get_user_detail_by_username_success():
    user_info_response = UserInfoResponse(
        id=uuid4(),
        firstname="Jane",
        lastname="Smith",
        username="jane.smith",
        email="jane.smith@example.com",
        title="Senior Developer",
        organization="Tech Solutions Inc",
        location="San Francisco",
        educations=["Computer Science", "Software Engineering"],
        avatar_url="https://example.com/avatar.jpg",
        about_me="Experienced software developer with passion for clean code.",
        followers=150,
        following=75,
        social_profiles=[]
    )
    
    with patch("pecha_api.users.users_views.get_user_info_by_username") as mock_get_user_info:
        mock_get_user_info.return_value = user_info_response
        
        response = client.get("/users/jane.smith")
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["username"] == "jane.smith"
        assert response_data["firstname"] == "Jane"
        assert response_data["lastname"] == "Smith"
        assert response_data["email"] == "jane.smith@example.com"
        assert response_data["title"] == "Senior Developer"
        assert response_data["organization"] == "Tech Solutions Inc"
        assert response_data["location"] == "San Francisco"
        assert response_data["about_me"] == "Experienced software developer with passion for clean code."
        assert response_data["followers"] == 150
        assert response_data["following"] == 75
        assert response_data["educations"] == ["Computer Science", "Software Engineering"]
        mock_get_user_info.assert_called_once_with("jane.smith")


def test_get_user_detail_by_username_not_found():
    with patch("pecha_api.users.users_views.get_user_info_by_username") as mock_get_user_info:
        mock_get_user_info.side_effect = HTTPException(status_code=404, detail="User not found")
        
        response = client.get("/users/nonexistent.user")
        
        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"
        
        mock_get_user_info.assert_called_once_with("nonexistent.user")


def test_get_user_detail_by_username_with_special_characters():
    user_info_response = UserInfoResponse(
        id=uuid4(),
        firstname="Test",
        lastname="User",
        username="test.user-123",
        email="test.user@example.com",
        title="",
        organization="",
        location="",
        educations=[],
        avatar_url="",
        about_me="",
        followers=0,
        following=0,
        social_profiles=[]
    )
    
    with patch("pecha_api.users.users_views.get_user_info_by_username") as mock_get_user_info:
        mock_get_user_info.return_value = user_info_response
        
        response = client.get("/users/test.user-123")
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["username"] == "test.user-123"
        mock_get_user_info.assert_called_once_with("test.user-123")


def test_patch_username_success():
    expected = UpdateUsernameResponse(
        message="Username updated successfully",
        username="brandnew"
    )
    with patch("pecha_api.users.users_views.update_username", return_value=expected):
        response = client.patch(
            "/users/username",
            json={"username": "brandnew"},
            headers={"Authorization": "Bearer testtoken"}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Username updated successfully"
    assert data["username"] == "brandnew"


def test_patch_username_conflict_409():
    with patch("pecha_api.users.users_views.update_username",
               side_effect=HTTPException(
                   status_code=409,
                   detail={
                       "message": ErrorConstants.USER_ALREADY_EXISTS,
                       "suggestions": ["taken1234", "taken5678", "taken9012"]
                   }
               )):
        response = client.patch(
            "/users/username",
            json={"username": "taken"},
            headers={"Authorization": "Bearer testtoken"}
        )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"] == ErrorConstants.USER_ALREADY_EXISTS
    assert len(detail["suggestions"]) == 3


def test_patch_username_unauthorized_401():
    with patch("pecha_api.users.users_views.update_username",
               side_effect=HTTPException(status_code=401, detail="Invalid or no token found")):
        response = client.patch(
            "/users/username",
            json={"username": "anyuser"},
            headers={"Authorization": "Bearer badtoken"}
        )
    assert response.status_code == 401


def test_patch_username_missing_auth_header():
    response = client.patch("/users/username", json={"username": "anyuser"})
    assert response.status_code == 403


def test_patch_username_validation_too_short():
    with patch("pecha_api.users.users_views.update_username") as mock_fn:
        response = client.patch(
            "/users/username",
            json={"username": "ab"},
            headers={"Authorization": "Bearer testtoken"}
        )
    assert response.status_code == 422
    mock_fn.assert_not_called()


def test_delete_user_information_success():
    with patch("pecha_api.users.users_views.delete_user_account") as mock_delete:
        mock_delete.return_value = None
        response = client.delete("/users/info", headers={"Authorization": "Bearer testtoken"})
        assert response.status_code == 204
        mock_delete.assert_called_once_with(token="testtoken")


def test_delete_user_information_no_auth_token():
    response = client.delete("/users/info")
    assert response.status_code == 403


def test_delete_user_information_invalid_token():
    with patch("pecha_api.users.users_views.delete_user_account",
               side_effect=HTTPException(status_code=401, detail="Invalid or no token found")):
        response = client.delete("/users/info", headers={"Authorization": "Bearer badtoken"})
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid or no token found"


def test_delete_user_information_server_error():
    with patch("pecha_api.users.users_views.delete_user_account",
               side_effect=HTTPException(status_code=500, detail="Failed to delete user account")):
        response = client.delete("/users/info", headers={"Authorization": "Bearer testtoken"})
        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to delete user account"


def test_get_user_onboarding_status():
    with patch("pecha_api.users.users_views.get_onboarding_status") as mock_get_status:
        mock_get_status.return_value = OnboardingStatusResponse(has_seen_onboarding=False)
        response = client.get(
            "/users/me/onboarding",
            headers={"Authorization": "Bearer testtoken"},
        )
        assert response.status_code == 200
        assert response.json() == {"has_seen_onboarding": False}
        mock_get_status.assert_called_once_with(token="testtoken")


def test_get_user_onboarding_status_unauthenticated():
    response = client.get("/users/me/onboarding")
    assert response.status_code == 403


def test_update_user_onboarding_status():
    with patch("pecha_api.users.users_views.update_onboarding_status") as mock_update_status:
        mock_update_status.return_value = OnboardingStatusResponse(has_seen_onboarding=True)
        response = client.put(
            "/users/me/onboarding",
            json={"has_seen_onboarding": True},
            headers={"Authorization": "Bearer testtoken"},
        )
        assert response.status_code == 200
        assert response.json() == {"has_seen_onboarding": True}
        mock_update_status.assert_called_once()


def test_update_user_onboarding_status_unauthenticated():
    response = client.put(
        "/users/me/onboarding",
        json={"has_seen_onboarding": True},
    )
    assert response.status_code == 403



def test_patch_username_validation_reserved_name():
    with patch("pecha_api.users.users_views.update_username") as mock_fn:
        response = client.patch(
            "/users/username",
            json={"username": "dalailama"},
            headers={"Authorization": "Bearer testtoken"}
        )
    assert response.status_code == 422
    assert "reserved" in response.text
    mock_fn.assert_not_called()
