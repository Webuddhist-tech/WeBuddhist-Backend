import io
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.mantra.mantra_response_models import CMSMantraDTO
from pecha_api.plans.media.media_response_models import ImageUrlModel, PlanUploadResponse

client = TestClient(api)


def _sample_cms_mantra_dto() -> CMSMantraDTO:
    return CMSMantraDTO(
        id=uuid.uuid4(),
        audio_url="mantras/medicine-buddha.mp3",
        deity_image_key="images/mantra_images/abc/original/x.webp",
        metadata=[],
    )


def test_create_mantra_success():
    payload = {
        "audio_url": "mantras/medicine-buddha.mp3",
        "metadata": [
            {
                "language": "EN",
                "title": "Medicine Buddha Mantra",
                "pronunciation": "tayatha om bekandze...",
                "mantra": "Tayatha om bekandze bekandze maha bekandze radza samudgate soha",
            },
            {
                "language": "BO",
                "title": "སྨན་བླའི་སྔགས།",
                "mantra": "ཨོཾ་བེ་ཀཱནྜེ་བེ་ཀཱནྜེ་མ་ཧཱ་བེ་ཀཱནྜེ་རཱ་ཇ་ས་མུདྒ་ཏེ་སྭཱ་ཧཱ།",
            },
        ],
    }
    sample_dto = _sample_cms_mantra_dto()

    with patch(
        "pecha_api.mantra.mantra_views.create_mantra_service",
        return_value=sample_dto,
    ) as mock_create:
        response = client.post(
            "/api/v1/cms/mantras",
            json=payload,
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 201
    assert response.json()["audio_url"] == sample_dto.audio_url
    assert response.json()["deity_image_key"] == sample_dto.deity_image_key
    mock_create.assert_called_once()


def test_create_mantra_requires_auth():
    response = client.post(
        "/api/v1/cms/mantras",
        json={
            "metadata": [
                {
                    "language": "EN",
                    "mantra": "Om mani padme hum",
                }
            ]
        },
    )

    assert response.status_code == 403


def test_create_mantra_rejects_empty_metadata():
    response = client.post(
        "/api/v1/cms/mantras",
        json={"metadata": []},
        headers={"Authorization": "Bearer dummy"},
    )

    assert response.status_code == 422


def test_create_mantra_rejects_duplicate_languages():
    response = client.post(
        "/api/v1/cms/mantras",
        json={
            "metadata": [
                {"language": "EN", "mantra": "First"},
                {"language": "EN", "mantra": "Second"},
            ]
        },
        headers={"Authorization": "Bearer dummy"},
    )

    assert response.status_code == 422


def test_update_mantra_success():
    mantra_id = uuid.uuid4()
    sample_dto = _sample_cms_mantra_dto()

    with patch(
        "pecha_api.mantra.mantra_views.update_mantra_service",
        return_value=sample_dto,
    ) as mock_update:
        response = client.patch(
            f"/api/v1/cms/mantras/{mantra_id}",
            json={"deity_image_key": "images/mantra_images/abc/original/x.webp"},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    assert response.json()["deity_image_key"] == sample_dto.deity_image_key
    mock_update.assert_called_once()
    _, kwargs = mock_update.call_args
    assert kwargs["mantra_id"] == mantra_id
    assert kwargs["request"].deity_image_key == "images/mantra_images/abc/original/x.webp"


def test_update_mantra_clears_key_with_null():
    mantra_id = uuid.uuid4()
    sample_dto = CMSMantraDTO(id=uuid.uuid4(), metadata=[], deity_image_key=None)

    with patch(
        "pecha_api.mantra.mantra_views.update_mantra_service",
        return_value=sample_dto,
    ) as mock_update:
        response = client.patch(
            f"/api/v1/cms/mantras/{mantra_id}",
            json={"deity_image_key": None},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 200
    _, kwargs = mock_update.call_args
    assert kwargs["request"].deity_image_key is None


def test_update_mantra_requires_auth():
    response = client.patch(
        f"/api/v1/cms/mantras/{uuid.uuid4()}",
        json={"deity_image_key": "some-key"},
    )

    assert response.status_code == 403


def test_upload_mantra_image_success():
    mantra_id = uuid.uuid4()
    sample_response = PlanUploadResponse(
        image=ImageUrlModel(thumbnail="t", medium="m", original="o"),
        key="images/mantra_images/abc/original/x.webp",
        path=f"images/mantra_images/{mantra_id}/some-uuid",
    )

    with patch(
        "pecha_api.mantra.mantra_views.upload_mantra_image",
        return_value=sample_response,
    ) as mock_upload:
        response = client.post(
            f"/api/v1/cms/mantras/image?mantra_id={mantra_id}",
            files={"file": ("deity.webp", io.BytesIO(b"fake-image-bytes"), "image/webp")},
            headers={"Authorization": "Bearer dummy"},
        )

    assert response.status_code == 201
    assert response.json()["key"] == sample_response.key
    mock_upload.assert_called_once()
    _, kwargs = mock_upload.call_args
    assert kwargs["mantra_id"] == mantra_id


def test_upload_mantra_image_requires_auth():
    response = client.post(
        f"/api/v1/cms/mantras/image?mantra_id={uuid.uuid4()}",
        files={"file": ("deity.webp", io.BytesIO(b"fake-image-bytes"), "image/webp")},
    )

    assert response.status_code == 403
