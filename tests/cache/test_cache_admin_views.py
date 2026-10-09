from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api

client = TestClient(api)

ENDPOINT = "/cms/admin/cache"
AUTH = {"Authorization": "Bearer admin-token"}


def test_flush_cache_requires_a_token():
    response = client.delete(ENDPOINT)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_flush_cache_rejects_a_non_super_admin():
    with patch(
        "pecha_api.cache.cache_admin_views._require_super_admin_caller",
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"),
    ):
        response = client.delete(ENDPOINT, headers=AUTH)
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_flush_cache_removes_everything_for_a_super_admin():
    with patch("pecha_api.cache.cache_admin_views._require_super_admin_caller"), patch(
        "pecha_api.cache.cache_admin_views.flush_response_cache",
        new_callable=AsyncMock,
        return_value=42,
    ) as mock_flush:
        response = client.delete(ENDPOINT, headers=AUTH)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"keys_deleted": 42, "scope": "all"}
    mock_flush.assert_awaited_once()


def test_flush_cache_evicts_a_single_key_when_given_one():
    with patch("pecha_api.cache.cache_admin_views._require_super_admin_caller"), patch(
        "pecha_api.cache.cache_admin_views.flush_cache_key",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_flush_key, patch(
        "pecha_api.cache.cache_admin_views.flush_response_cache", new_callable=AsyncMock
    ) as mock_flush_all:
        response = client.delete(f"{ENDPOINT}?hash_key=abc123", headers=AUTH)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"keys_deleted": 1, "scope": "key:abc123"}
    mock_flush_key.assert_awaited_once_with(hash_key="abc123")
    mock_flush_all.assert_not_awaited()


def test_flush_cache_can_be_scoped_to_one_namespace():
    with patch("pecha_api.cache.cache_admin_views._require_super_admin_caller"), patch(
        "pecha_api.cache.cache_admin_views.flush_response_cache",
        new_callable=AsyncMock,
        return_value=7,
    ) as mock_flush:
        response = client.delete(f"{ENDPOINT}?cache_type=series_list", headers=AUTH)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"keys_deleted": 7, "scope": "series_list"}
    assert mock_flush.await_args.kwargs["cache_type"].value == "series_list"


def test_flush_cache_rejects_an_unknown_namespace():
    with patch("pecha_api.cache.cache_admin_views._require_super_admin_caller"):
        response = client.delete(f"{ENDPOINT}?cache_type=not_a_namespace", headers=AUTH)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
