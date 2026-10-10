from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette import status

from .mappings_response_models import TextMappingRequest
from ..segments.segments_response_models import SegmentResponse

# Mappings were written to MongoDB segments, which are gone; OpenPecha's
# related segments are read-only. Kept, deprecated, until callers are removed.
MAPPINGS_UNAVAILABLE_MESSAGE = "Segment mappings are no longer supported"

oauth2_scheme = HTTPBearer()

mapping_router = APIRouter(
    prefix="/mappings",
    tags=["Text Mapping"]
)


@mapping_router.post("", status_code=status.HTTP_201_CREATED, deprecated=True)
async def create_text_mapping(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                              text_mapping_request: TextMappingRequest) -> SegmentResponse:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=MAPPINGS_UNAVAILABLE_MESSAGE)


@mapping_router.delete("", status_code=status.HTTP_204_NO_CONTENT, deprecated=True)
async def delete_text_mapping(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                              text_mapping_request: TextMappingRequest) -> None:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=MAPPINGS_UNAVAILABLE_MESSAGE)
