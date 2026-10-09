"""Route-level tests: the handlers themselves, through the ASGI app.

These cover the thin view layer (status codes, form/query binding, the 204
Response) that service-level tests never touch.
"""
import io
from datetime import datetime, timezone as tz
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.group_assets.response_models import (
    GroupAssetDTO,
    GroupAssetsResponse,
)

VIEWS = "pecha_api.group_assets.views"
AUTH = {"Authorization": "Bearer token"}


@pytest.fixture
def client():
    return TestClient(api)


def _asset_dto(title="Heart Sutra"):
    return GroupAssetDTO(
        id=uuid4(),
        group_id=uuid4(),
        asset_type="AUDIO",
        title=title,
        file_name=f"{title}.mp3",
        asset_url="https://presigned",
        mime_type="audio/mpeg",
        file_size_bytes=2947188,
        duration_ms=184000,
        created_at=datetime.now(tz.utc).isoformat(),
    )


class TestUploadRoute:
    @patch(f"{VIEWS}.upload_group_asset_service")
    def test_upload_returns_201_and_the_dto(self, mock_service, client):
        mock_service.return_value = _asset_dto()

        response = client.post(
            f"/cms/author/groups/{uuid4()}/assets",
            headers=AUTH,
            files={"file": ("chant.mp3", io.BytesIO(b"audio"), "audio/mpeg")},
            data={"asset_type": "AUDIO", "title": "Heart Sutra"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Heart Sutra"
        assert body["asset_url"] == "https://presigned"
        # The raw key must never reach a client.
        assert "s3_key" not in body

    @patch(f"{VIEWS}.upload_group_asset_service")
    def test_upload_passes_optional_form_fields(self, mock_service, client):
        mock_service.return_value = _asset_dto()

        client.post(
            f"/cms/author/groups/{uuid4()}/assets",
            headers=AUTH,
            files={"file": ("chant.mp3", io.BytesIO(b"audio"), "audio/mpeg")},
            data={"asset_type": "AUDIO", "duration_ms": "184000"},
        )

        assert mock_service.call_args.kwargs["duration_ms"] == 184000
        assert mock_service.call_args.kwargs["title"] is None

    def test_upload_without_a_file_is_422(self, client):
        response = client.post(
            f"/cms/author/groups/{uuid4()}/assets",
            headers=AUTH,
            data={"asset_type": "AUDIO"},
        )
        assert response.status_code == 422


class TestListRoute:
    @patch(f"{VIEWS}.list_group_assets_service")
    def test_list_returns_200_with_pagination(self, mock_service, client):
        mock_service.return_value = GroupAssetsResponse(
            assets=[_asset_dto("slow"), _asset_dto("fast")],
            skip=0,
            limit=20,
            total=2,
        )

        response = client.get(
            f"/cms/author/groups/{uuid4()}/assets", headers=AUTH
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert [a["title"] for a in body["assets"]] == ["slow", "fast"]

    @patch(f"{VIEWS}.list_group_assets_service")
    def test_list_forwards_the_picker_filters(self, mock_service, client):
        mock_service.return_value = GroupAssetsResponse(
            assets=[], skip=10, limit=50, total=0
        )

        client.get(
            f"/cms/author/groups/{uuid4()}/assets"
            "?asset_type=AUDIO&search=sutra&skip=10&limit=50",
            headers=AUTH,
        )

        kwargs = mock_service.call_args.kwargs
        assert kwargs["search"] == "sutra"
        assert kwargs["skip"] == 10
        assert kwargs["limit"] == 50
        assert kwargs["asset_type"].value == "AUDIO"

    def test_limit_above_the_maximum_is_rejected(self, client):
        response = client.get(
            f"/cms/author/groups/{uuid4()}/assets?limit=500", headers=AUTH
        )
        assert response.status_code == 422


class TestUpdateRoute:
    @patch(f"{VIEWS}.update_group_asset_service")
    def test_rename_returns_200(self, mock_service, client):
        mock_service.return_value = _asset_dto("Renamed")

        response = client.patch(
            f"/cms/author/groups/{uuid4()}/assets/{uuid4()}",
            headers=AUTH,
            json={"title": "Renamed"},
        )

        assert response.status_code == 200
        assert response.json()["title"] == "Renamed"


class TestDeleteRoute:
    @patch(f"{VIEWS}.delete_group_asset_service")
    def test_delete_returns_204_with_no_body(self, mock_service, client):
        response = client.delete(
            f"/cms/author/groups/{uuid4()}/assets/{uuid4()}", headers=AUTH
        )

        assert response.status_code == 204
        assert response.content == b""

    @patch(f"{VIEWS}.delete_group_asset_service")
    def test_force_flag_is_forwarded(self, mock_service, client):
        client.delete(
            f"/cms/author/groups/{uuid4()}/assets/{uuid4()}?force=true",
            headers=AUTH,
        )
        assert mock_service.call_args.kwargs["force"] is True

    @patch(f"{VIEWS}.delete_group_asset_service")
    def test_force_defaults_to_false(self, mock_service, client):
        client.delete(
            f"/cms/author/groups/{uuid4()}/assets/{uuid4()}", headers=AUTH
        )
        assert mock_service.call_args.kwargs["force"] is False


class TestAuthIsRequired:
    @pytest.mark.parametrize(
        "method,suffix",
        [
            ("get", ""),
            ("post", ""),
            ("patch", "/{aid}"),
            ("delete", "/{aid}"),
        ],
    )
    def test_missing_bearer_token_is_rejected(self, client, method, suffix):
        path = f"/cms/author/groups/{uuid4()}/assets" + suffix.format(aid=uuid4())
        response = getattr(client, method)(path)
        assert response.status_code == 403
