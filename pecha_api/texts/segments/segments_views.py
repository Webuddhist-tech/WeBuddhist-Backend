from fastapi.security import HTTPBearer
from fastapi import APIRouter
from starlette import status

from .segments_openpecha_service import search_segments_by_content_service
from .segments_response_models import (
    SegmentResponse,
    SegmentSearchRequest,
)

oauth2_scheme = HTTPBearer()
segment_router = APIRouter(
    prefix="/segments",
    tags=["Segments"]
)


@segment_router.post("/search", status_code=status.HTTP_200_OK, deprecated=True)
async def search_segments(
    segment_search_request: SegmentSearchRequest,
) -> SegmentResponse:
    return await search_segments_by_content_service(
        segment_search_request=segment_search_request,
    )
