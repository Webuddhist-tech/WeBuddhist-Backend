from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from .sheets_enum import SortBy, SortOrder
from .sheets_response_models import (
    CreateSheetRequest,
    SheetDetailDTO,
    SheetDTOResponse,
    SheetIdResponse,
)
from .sheets_service import upload_sheet_image_request

# Sheets were stored in MongoDB, which is gone. The routes stay, deprecated,
# answering as an empty sheets store would, until their callers are removed.
SHEETS_UNAVAILABLE_MESSAGE = "Sheets are no longer supported"

oauth2_scheme = HTTPBearer()
sheets_router = APIRouter(
    prefix="/sheets",
    tags=["Sheets"]
)


def _sheets_unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_410_GONE, detail=SHEETS_UNAVAILABLE_MESSAGE)


@sheets_router.get("", status_code=status.HTTP_200_OK, deprecated=True)
async def get_sheets(
    authentication_credential: Annotated[Optional[HTTPAuthorizationCredentials], Depends(HTTPBearer(auto_error=False))],
    language: Optional[str] = Query(default=None),
    email: Optional[str] = Query(default=None),
    sort_by: Optional[SortBy] = Query(default=None),
    sort_order: Optional[SortOrder] = Query(default=None),
    skip: int = Query(default=0),
    limit: int = Query(default=10)
) -> SheetDTOResponse:
    return SheetDTOResponse(sheets=[], skip=skip, limit=limit, total=0)


@sheets_router.get("/{sheet_id}", status_code=status.HTTP_200_OK, deprecated=True)
async def get_sheet(
    sheet_id: str,
    skip: int = Query(default=0),
    limit: int = Query(default=10)
) -> SheetDetailDTO:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sheet not found")


@sheets_router.post("", status_code=status.HTTP_201_CREATED, deprecated=True)
async def create_sheet(
    create_sheet_request: CreateSheetRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> SheetIdResponse:
    raise _sheets_unavailable()


@sheets_router.put("/{sheet_id}", status_code=status.HTTP_200_OK, deprecated=True)
async def update_sheet(
    sheet_id: str,
    update_sheet_request: CreateSheetRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> SheetIdResponse:
    raise _sheets_unavailable()


@sheets_router.delete("/{sheet_id}", status_code=status.HTTP_204_NO_CONTENT, deprecated=True)
async def delete_sheet(
    sheet_id: str,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sheet not found")


@sheets_router.post("/upload", status_code=status.HTTP_201_CREATED, deprecated=True)
def upload_sheet_image(sheet_id: Optional[str] = None, file: UploadFile = File(...)):
    return upload_sheet_image_request(sheet_id=sheet_id, file=file)
