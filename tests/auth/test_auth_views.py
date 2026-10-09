from fastapi import HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch

from pecha_api.app import api  # Assuming your FastAPI app is in main.py

client = TestClient(api)


def test_register_user_email():
    with patch("pecha_api.auth.auth_views.register_user_with_source") as mock_register_user_with_source:
        mock_register_user_with_source.return_value = {"user": {"name": "tenzin samten", "avatar_url": ""},
                                                       "auth": {
                                                           "access_token": "test_token",
                                                           "refresh_token": "test_refresh_token",
                                                           "token_type": "Bearer"
                                                       }
                                                       }
        response = client.post("/auth/register", json={"email": "testuser@example.com", "firstname": "testfirstname",
                                                       "lastname": "testlastname", "password": "testpass"})

        assert response.status_code == 201
        assert response.json()["auth"]["access_token"] == "test_token"
        assert response.json()["auth"]["refresh_token"] == "test_refresh_token"
        assert response.json()["auth"]["token_type"] == "Bearer"


def test_register_user_social():
    with patch("pecha_api.auth.auth_views.create_user") as mock_create_user:
        mock_create_user.return_value = {"user": {"name": "tenzin samten", "avatar_url": ""},
                                                       "auth": {
                                                           "access_token": "test_token",
                                                           "refresh_token": "test_refresh_token",
                                                           "token_type": "Bearer"
                                                       }
                                                       }
        response = client.post("/auth/social_register",
                               json={"create_user_request": {"email": "testuser@example.com", "firstname": "testfirstname",
                                     "lastname": "testlastname", "password": "testpass"},"platform":"google-oauth2" })

        assert response.status_code == 201
        assert response.json()["auth"]["access_token"] == "test_token"
        assert response.json()["auth"]["refresh_token"] == "test_refresh_token"
        assert response.json()["auth"]["token_type"] == "Bearer"


def test_register_user_social_keeps_auth0_picture():
    with patch("pecha_api.auth.auth_views.create_user") as mock_create_user:
        mock_create_user.return_value = {
            "user": {"name": "tenzin samten", "avatar_url": ""},
            "auth": {
                "access_token": "test_token",
                "refresh_token": "test_refresh_token",
                "token_type": "Bearer",
            },
        }
        response = client.post(
            "/auth/social_register",
            json={
                "create_user_request": {
                    "email": "testuser@example.com",
                    "firstname": "testfirstname",
                    "lastname": "testlastname",
                    "avatar_url": "https://lh3.googleusercontent.com/a/photo",
                },
                "platform": "google-oauth2",
            },
        )

    assert response.status_code == 201
    request = mock_create_user.call_args.kwargs["create_user_request"]
    assert request.avatar_url == "https://lh3.googleusercontent.com/a/photo"


def test_register_user_social_stores_picture_when_account_exists():
    with patch("pecha_api.auth.auth_views.create_user") as mock_create_user, patch(
        "pecha_api.auth.auth_views.remember_social_avatar"
    ) as mock_remember, patch(
        "pecha_api.auth.auth_service.get", return_value="action-secret"
    ):
        mock_create_user.side_effect = HTTPException(status_code=409, detail="exists")
        response = client.post(
            "/auth/social_register",
            json={
                "create_user_request": {
                    "email": "testuser@example.com",
                    "firstname": "testfirstname",
                    "lastname": "testlastname",
                    "avatar_url": "https://lh3.googleusercontent.com/a/photo",
                },
                "platform": "google-oauth2",
            },
            headers={"X-Social-Register-Token": "action-secret"},
        )

    assert response.status_code == 409
    mock_remember.assert_called_once()


def test_register_user_social_ignores_picture_without_the_shared_secret():
    """A public caller cannot repaint an existing account's avatar."""
    with patch("pecha_api.auth.auth_views.create_user") as mock_create_user, patch(
        "pecha_api.auth.auth_views.remember_social_avatar"
    ) as mock_remember, patch(
        "pecha_api.auth.auth_service.get", return_value="action-secret"
    ):
        mock_create_user.side_effect = HTTPException(status_code=409, detail="exists")
        response = client.post(
            "/auth/social_register",
            json={
                "create_user_request": {
                    "email": "victim@example.com",
                    "firstname": "testfirstname",
                    "lastname": "testlastname",
                    "avatar_url": "https://lh3.googleusercontent.com/a/attacker",
                },
                "platform": "google-oauth2",
            },
        )

    assert response.status_code == 409
    mock_remember.assert_not_called()


def test_register_user_social_ignores_picture_when_the_secret_is_unset():
    """No configured secret means no caller can be trusted with the write."""
    with patch("pecha_api.auth.auth_views.create_user") as mock_create_user, patch(
        "pecha_api.auth.auth_views.remember_social_avatar"
    ) as mock_remember, patch("pecha_api.auth.auth_service.get", return_value=""):
        mock_create_user.side_effect = HTTPException(status_code=409, detail="exists")
        response = client.post(
            "/auth/social_register",
            json={
                "create_user_request": {
                    "email": "victim@example.com",
                    "firstname": "testfirstname",
                    "lastname": "testlastname",
                    "avatar_url": "https://lh3.googleusercontent.com/a/attacker",
                },
                "platform": "google-oauth2",
            },
            headers={"X-Social-Register-Token": "anything"},
        )

    assert response.status_code == 409
    mock_remember.assert_not_called()


def test_login_user():
    with patch("pecha_api.auth.auth_views.authenticate_and_generate_tokens") as mock_authenticate:
        mock_authenticate.return_value = {"user": {"name": "tenzin samten", "avatar_url": ""},
                                          "auth": {
                                              "access_token": "test_token",
                                              "refresh_token": "test_refresh_token",
                                              "token_type": "Bearer"
                                          }
                                          }
        response = client.post("/auth/login", json={"email": "testuser@example.com", "password": "testpass"})

        assert response.status_code == 200
        assert response.json()["auth"]["access_token"] == "test_token"
        assert response.json()["auth"]["refresh_token"] == "test_refresh_token"
        assert response.json()["auth"]["token_type"] == "Bearer"


def test_refresh_token():
    with patch("pecha_api.auth.auth_views.refresh_access_token") as mock_refresh:
        mock_refresh.return_value = {"access_token": "new_fake_access_token", "refresh_token": "new_fake_refresh_token",
                                     "token_type": "Bearer"}
        response = client.post("/auth/refresh-token", json={"token": "refresh_token"})

        assert response.status_code == 200
        assert "access_token" in response.json()


def test_request_reset_password():
    with patch("pecha_api.auth.auth_views.request_reset_password") as mock_request_reset_password:
        mock_request_reset_password.return_value = None
        response = client.post("/auth/request-reset-password", json={"email": "testuser@example.com"})

        assert response.status_code == 202


def test_reset_password():
    with patch("pecha_api.auth.auth_views.update_password") as mock_update_password:
        mock_update_password.return_value = None
        response = client.post("/auth/reset-password", json={"password": "newpassword"},
                               headers={"Authorization": "Bearer test_token"})

        assert response.status_code == 200


def test_phone_exchange_passes_verified_token_and_names():
    user_id = "123e4567-e89b-12d3-a456-426614174000"
    expected = {
        "user_id": user_id,
        "phone_number": "+14155552671",
        "message": "Authentication successful",
        "user": {"name": "Tashi Dolma", "avatar_url": None},
        "auth": {
            "access_token": "access",
            "refresh_token": "refresh",
            "token_type": "Bearer",
        },
    }
    with patch(
        "pecha_api.auth.auth_views.exchange_phone_token",
        return_value=expected,
    ) as exchange:
        response = client.post(
            "/auth/phone/exchange",
            json={
                "auth0_token": "auth0-token",
                "first_name": "Tashi",
                "last_name": "Dolma",
            },
        )

    assert response.status_code == 200
    assert response.json()["user_id"] == user_id
    assert exchange.call_args.args[0].auth0_token == "auth0-token"


def test_phone_link_requires_backend_bearer_and_passes_both_tokens():
    expected = {
        "user_id": "123e4567-e89b-12d3-a456-426614174000",
        "phone_number": "+14155552671",
        "message": "Phone identity linked",
    }
    with patch(
        "pecha_api.auth.auth_views.link_phone_identity",
        return_value=expected,
    ) as link:
        response = client.post(
            "/auth/phone/link",
            json={"auth0_token": "auth0-token"},
            headers={"Authorization": "Bearer backend-token"},
        )

    assert response.status_code == 200
    link.assert_called_once_with(
        backend_token="backend-token",
        auth0_token="auth0-token",
    )


def test_phone_link_without_backend_token_is_forbidden():
    response = client.post(
        "/auth/phone/link",
        json={"auth0_token": "auth0-token"},
    )
    assert response.status_code == 403
