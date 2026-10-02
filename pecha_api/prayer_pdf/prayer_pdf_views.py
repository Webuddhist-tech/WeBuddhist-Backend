from datetime import date
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from .prayer_pdf_renderer import font_path
from .prayer_pdf_response_models import (
    PrayerPdfPreviewResponse,
    PrayerPdfSettingsDTO,
    UpdatePrayerPdfSettingsRequest,
)
from .prayer_pdf_service import (
    PrayerPdfFile,
    build_event_prayer_pdf_service,
    build_group_prayer_pdf_service,
    get_event_prayer_pdf_settings_service,
    get_group_prayer_pdf_settings_service,
    preview_event_prayer_pdf_service,
    preview_group_prayer_pdf_service,
    reset_event_prayer_pdf_settings_service,
    reset_group_prayer_pdf_settings_service,
    update_event_prayer_pdf_settings_service,
    update_group_prayer_pdf_settings_service,
)

oauth2_scheme = HTTPBearer()

cms_prayer_pdf_router = APIRouter(
    prefix="/cms/prayer-pdf",
    tags=["CMS Prayer request PDF"],
)

Credentials = Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
DayQuery = Annotated[
    Optional[date],
    Query(
        alias="date",
        description="Day to export (YYYY-MM-DD) in the settings' timezone. Defaults to today there.",
    ),
]

_PDF_RESPONSES = {
    200: {"content": {"application/pdf": {}}, "description": "The PDF, as an attachment."},
    404: {"description": "Not found, or NO_PRAYER_REQUESTS on that day."},
}


def _pdf_response(pdf: PrayerPdfFile) -> Response:
    return Response(
        content=pdf.content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{pdf.filename}"',
            "X-Prayer-Count": str(pdf.prayer_count),
            "Cache-Control": "no-store",
        },
    )


# ------------------------------------------------------------------ fonts


@cms_prayer_pdf_router.get("/fonts/{name}", response_class=FileResponse, include_in_schema=False)
def get_prayer_pdf_font(name: str) -> FileResponse:
    """The PDF's fonts, for the Studio preview. Open-licensed and the same
    for everyone, so no token; cached for a week."""
    path = font_path(name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Font not found")
    return FileResponse(
        path,
        media_type="font/ttf",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


# ----------------------------------------------------------------- groups


@cms_prayer_pdf_router.get("/groups/{group_id}", status_code=status.HTTP_200_OK)
def get_group_prayer_pdf_settings(group_id: UUID, credentials: Credentials) -> PrayerPdfSettingsDTO:
    return get_group_prayer_pdf_settings_service(token=credentials.credentials, group_id=group_id)


@cms_prayer_pdf_router.put("/groups/{group_id}", status_code=status.HTTP_200_OK)
def update_group_prayer_pdf_settings(
    group_id: UUID, request: UpdatePrayerPdfSettingsRequest, credentials: Credentials
) -> PrayerPdfSettingsDTO:
    return update_group_prayer_pdf_settings_service(
        token=credentials.credentials, group_id=group_id, request=request
    )


@cms_prayer_pdf_router.delete("/groups/{group_id}", status_code=status.HTTP_200_OK)
def reset_group_prayer_pdf_settings(group_id: UUID, credentials: Credentials) -> PrayerPdfSettingsDTO:
    return reset_group_prayer_pdf_settings_service(token=credentials.credentials, group_id=group_id)


@cms_prayer_pdf_router.get("/groups/{group_id}/download", responses=_PDF_RESPONSES, response_class=Response)
async def download_group_prayer_pdf(group_id: UUID, credentials: Credentials, day: DayQuery = None) -> Response:
    pdf = await build_group_prayer_pdf_service(token=credentials.credentials, group_id=group_id, day=day)
    return _pdf_response(pdf)


@cms_prayer_pdf_router.post("/groups/{group_id}/preview", status_code=status.HTTP_200_OK)
def preview_group_prayer_pdf(
    group_id: UUID, request: UpdatePrayerPdfSettingsRequest, credentials: Credentials, day: DayQuery = None
) -> PrayerPdfPreviewResponse:
    return preview_group_prayer_pdf_service(
        token=credentials.credentials, group_id=group_id, request=request, day=day
    )


# ----------------------------------------------------------------- events


@cms_prayer_pdf_router.get("/events/{event_id}", status_code=status.HTTP_200_OK)
def get_event_prayer_pdf_settings(event_id: UUID, credentials: Credentials) -> PrayerPdfSettingsDTO:
    return get_event_prayer_pdf_settings_service(token=credentials.credentials, event_id=event_id)


@cms_prayer_pdf_router.put("/events/{event_id}", status_code=status.HTTP_200_OK)
def update_event_prayer_pdf_settings(
    event_id: UUID, request: UpdatePrayerPdfSettingsRequest, credentials: Credentials
) -> PrayerPdfSettingsDTO:
    return update_event_prayer_pdf_settings_service(
        token=credentials.credentials, event_id=event_id, request=request
    )


@cms_prayer_pdf_router.delete("/events/{event_id}", status_code=status.HTTP_200_OK)
def reset_event_prayer_pdf_settings(event_id: UUID, credentials: Credentials) -> PrayerPdfSettingsDTO:
    return reset_event_prayer_pdf_settings_service(token=credentials.credentials, event_id=event_id)


@cms_prayer_pdf_router.get("/events/{event_id}/download", responses=_PDF_RESPONSES, response_class=Response)
async def download_event_prayer_pdf(event_id: UUID, credentials: Credentials, day: DayQuery = None) -> Response:
    pdf = await build_event_prayer_pdf_service(token=credentials.credentials, event_id=event_id, day=day)
    return _pdf_response(pdf)


@cms_prayer_pdf_router.post("/events/{event_id}/preview", status_code=status.HTTP_200_OK)
def preview_event_prayer_pdf(
    event_id: UUID, request: UpdatePrayerPdfSettingsRequest, credentials: Credentials, day: DayQuery = None
) -> PrayerPdfPreviewResponse:
    return preview_event_prayer_pdf_service(
        token=credentials.credentials, event_id=event_id, request=request, day=day
    )
