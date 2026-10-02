from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.prayer_pdf.prayer_pdf_response_models import (
    PrayerPdfSettingsDTO,
    PrayerPdfSettingsSource,
)
from pecha_api.prayer_pdf.prayer_pdf_service import PrayerPdfFile

client = TestClient(api)

_AUTH = {"Authorization": "Bearer dummy"}
_VIEWS = "pecha_api.prayer_pdf.prayer_pdf_views"


def _dto(**overrides) -> PrayerPdfSettingsDTO:
    values = dict(
        group_id=uuid4(),
        source=PrayerPdfSettingsSource.GROUP,
        title="Zabtik Drolchok",
    )
    values.update(overrides)
    return PrayerPdfSettingsDTO(**values)


def test_settings_require_auth():
    response = client.get(f"/cms/prayer-pdf/groups/{uuid4()}")
    assert response.status_code == 403


def test_get_group_settings():
    group_id = uuid4()
    with patch(f"{_VIEWS}.get_group_prayer_pdf_settings_service", return_value=_dto(group_id=group_id)) as mock_get:
        response = client.get(f"/cms/prayer-pdf/groups/{group_id}", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["title"] == "Zabtik Drolchok"
    assert response.json()["source"] == "GROUP"
    mock_get.assert_called_once_with(token="dummy", group_id=group_id)


def test_put_event_settings_passes_validated_body():
    event_id = uuid4()
    with patch(f"{_VIEWS}.update_event_prayer_pdf_settings_service", return_value=_dto(event_id=event_id)) as mock_put:
        response = client.put(
            f"/cms/prayer-pdf/events/{event_id}",
            headers=_AUTH,
            json={"title": "  Morning puja  ", "columns": 4, "page_size": "A4", "day_one": "2026-09-25"},
        )

    assert response.status_code == 200
    request = mock_put.call_args.kwargs["request"]
    assert request.title == "Morning puja"
    assert request.columns == 4
    assert request.page_size == "A4"
    assert str(request.day_one) == "2026-09-25"


def test_put_rejects_bad_values():
    group_id = uuid4()
    for body in (
        {"columns": 9},
        {"columns": 1},
        {"page_size": "LETTER"},
        {"primary_color": "red"},
        {"secondary_color": "#12345"},
        {"timezone": "Mars/Base"},
        {"day_one": "someday"},
    ):
        response = client.put(f"/cms/prayer-pdf/groups/{group_id}", headers=_AUTH, json=body)
        assert response.status_code == 422, body


def test_delete_resets_settings():
    event_id = uuid4()
    with patch(
        f"{_VIEWS}.reset_event_prayer_pdf_settings_service",
        return_value=_dto(event_id=event_id, source=PrayerPdfSettingsSource.DEFAULT, title=None),
    ) as mock_reset:
        response = client.delete(f"/cms/prayer-pdf/events/{event_id}", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["source"] == "DEFAULT"
    mock_reset.assert_called_once_with(token="dummy", event_id=event_id)


def test_download_group_pdf():
    group_id = uuid4()
    pdf = PrayerPdfFile(content=b"%PDF-1.7 fake", filename="Prayer_Requests_x_2026-10-01_A3.pdf", prayer_count=5)
    with patch(f"{_VIEWS}.build_group_prayer_pdf_service", new=AsyncMock(return_value=pdf)) as mock_build:
        response = client.get(
            f"/cms/prayer-pdf/groups/{group_id}/download", headers=_AUTH, params={"date": "2026-10-01"}
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="Prayer_Requests_x_2026-10-01_A3.pdf"' in response.headers["content-disposition"]
    assert response.headers["x-prayer-count"] == "5"
    assert response.content == b"%PDF-1.7 fake"
    assert str(mock_build.call_args.kwargs["day"]) == "2026-10-01"


def test_download_event_pdf_defaults_day_to_none():
    event_id = uuid4()
    pdf = PrayerPdfFile(content=b"%PDF", filename="a.pdf", prayer_count=1)
    with patch(f"{_VIEWS}.build_event_prayer_pdf_service", new=AsyncMock(return_value=pdf)) as mock_build:
        response = client.get(f"/cms/prayer-pdf/events/{event_id}/download", headers=_AUTH)

    assert response.status_code == 200
    assert mock_build.call_args.kwargs["day"] is None


def test_download_with_no_prayers_is_404():
    with patch(
        f"{_VIEWS}.build_event_prayer_pdf_service",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="NO_PRAYER_REQUESTS")),
    ):
        response = client.get(f"/cms/prayer-pdf/events/{uuid4()}/download", headers=_AUTH)

    assert response.status_code == 404
    assert response.json()["detail"] == "NO_PRAYER_REQUESTS"


def test_download_rejects_bad_date():
    response = client.get(
        f"/cms/prayer-pdf/groups/{uuid4()}/download", headers=_AUTH, params={"date": "yesterday"}
    )
    assert response.status_code == 422


def test_preview_group_passes_settings_and_day():
    from pecha_api.prayer_pdf.prayer_pdf_response_models import PrayerPdfPreviewResponse

    group_id = uuid4()
    preview = PrayerPdfPreviewResponse(html="<html></html>", day="2026-10-01", prayer_count=0, is_sample=True)
    with patch(f"{_VIEWS}.preview_group_prayer_pdf_service", return_value=preview) as mock_preview:
        response = client.post(
            f"/cms/prayer-pdf/groups/{group_id}/preview",
            headers=_AUTH,
            params={"date": "2026-10-01"},
            json={"title": "  Prayer Requests ", "columns": 3},
        )

    assert response.status_code == 200
    assert response.json() == {"html": "<html></html>", "day": "2026-10-01", "prayer_count": 0, "is_sample": True}
    kwargs = mock_preview.call_args.kwargs
    assert kwargs["request"].title == "Prayer Requests"
    assert kwargs["request"].columns == 3
    assert str(kwargs["day"]) == "2026-10-01"


def test_preview_event_rejects_bad_settings():
    response = client.post(f"/cms/prayer-pdf/events/{uuid4()}/preview", headers=_AUTH, json={"primary_color": "red"})
    assert response.status_code == 422


def test_font_route_is_public_and_cached():
    response = client.get("/cms/prayer-pdf/fonts/EBGaramond.ttf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "font/ttf"
    assert "max-age" in response.headers["cache-control"]
    assert len(response.content) > 100_000


def test_font_route_refuses_other_files():
    assert client.get("/cms/prayer-pdf/fonts/bo.ttf").status_code == 404
    assert client.get("/cms/prayer-pdf/fonts/..%2F..%2Fconfig.py").status_code == 404
