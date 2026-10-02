from datetime import date
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from .prayer_pdf_response_models import (
    PrayerPdfSettingsDTO,
    UpdatePrayerPdfSettingsRequest,
)
from .prayer_pdf_service import (
    PrayerPdfFile,
    build_event_prayer_pdf_service,
    build_group_prayer_pdf_service,
    get_event_prayer_pdf_settings_service,
    get_group_prayer_pdf_settings_service,
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


# ----------------------------------------------------------------- groups


@cms_prayer_pdf_router.get("/groups/{group_id}", status_code=status.HTTP_200_OK, response_model=PrayerPdfSettingsDTO)
def get_group_prayer_pdf_settings(group_id: UUID, credentials: Credentials) -> PrayerPdfSettingsDTO:
    return get_group_prayer_pdf_settings_service(token=credentials.credentials, group_id=group_id)


@cms_prayer_pdf_router.put("/groups/{group_id}", status_code=status.HTTP_200_OK, response_model=PrayerPdfSettingsDTO)
def update_group_prayer_pdf_settings(
    group_id: UUID, request: UpdatePrayerPdfSettingsRequest, credentials: Credentials
) -> PrayerPdfSettingsDTO:
    return update_group_prayer_pdf_settings_service(
        token=credentials.credentials, group_id=group_id, request=request
    )


@cms_prayer_pdf_router.delete("/groups/{group_id}", status_code=status.HTTP_200_OK, response_model=PrayerPdfSettingsDTO)
def reset_group_prayer_pdf_settings(group_id: UUID, credentials: Credentials) -> PrayerPdfSettingsDTO:
    return reset_group_prayer_pdf_settings_service(token=credentials.credentials, group_id=group_id)


@cms_prayer_pdf_router.get("/groups/{group_id}/download", responses=_PDF_RESPONSES, response_class=Response)
async def download_group_prayer_pdf(group_id: UUID, credentials: Credentials, day: DayQuery = None) -> Response:
    pdf = await build_group_prayer_pdf_service(token=credentials.credentials, group_id=group_id, day=day)
    return _pdf_response(pdf)


# ----------------------------------------------------------------- events


@cms_prayer_pdf_router.get("/events/{event_id}", status_code=status.HTTP_200_OK, response_model=PrayerPdfSettingsDTO)
def get_event_prayer_pdf_settings(event_id: UUID, credentials: Credentials) -> PrayerPdfSettingsDTO:
    return get_event_prayer_pdf_settings_service(token=credentials.credentials, event_id=event_id)


@cms_prayer_pdf_router.put("/events/{event_id}", status_code=status.HTTP_200_OK, response_model=PrayerPdfSettingsDTO)
def update_event_prayer_pdf_settings(
    event_id: UUID, request: UpdatePrayerPdfSettingsRequest, credentials: Credentials
) -> PrayerPdfSettingsDTO:
    return update_event_prayer_pdf_settings_service(
        token=credentials.credentials, event_id=event_id, request=request
    )


@cms_prayer_pdf_router.delete("/events/{event_id}", status_code=status.HTTP_200_OK, response_model=PrayerPdfSettingsDTO)
def reset_event_prayer_pdf_settings(event_id: UUID, credentials: Credentials) -> PrayerPdfSettingsDTO:
    return reset_event_prayer_pdf_settings_service(token=credentials.credentials, event_id=event_id)


@cms_prayer_pdf_router.get("/events/{event_id}/download", responses=_PDF_RESPONSES, response_class=Response)
async def download_event_prayer_pdf(event_id: UUID, credentials: Credentials, day: DayQuery = None) -> Response:
    pdf = await build_event_prayer_pdf_service(token=credentials.credentials, event_id=event_id, day=day)
    return _pdf_response(pdf)
