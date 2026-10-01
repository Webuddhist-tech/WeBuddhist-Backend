from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from .cms_service import (
    cms_create_prayer_intention_service,
    cms_list_prayer_intentions_service,
    cms_patch_prayer_intention_service,
)
from .prayer_intention_response_models import (
    CreatePrayerIntentionRequest,
    PatchPrayerIntentionRequest,
    PrayerIntentionCMSDTO,
    PrayerIntentionsCMSListResponse,
)

oauth2_scheme = HTTPBearer()

cms_prayer_intentions_router = APIRouter(
    prefix="/cms/intentions",
    tags=["CMS Prayer intentions"],
)


@cms_prayer_intentions_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=PrayerIntentionsCMSListResponse,
)
def cms_list_prayer_intentions(
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
) -> PrayerIntentionsCMSListResponse:
    return cms_list_prayer_intentions_service(
        token=authentication_credential.credentials,
    )


@cms_prayer_intentions_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PrayerIntentionCMSDTO,
)
def cms_create_prayer_intention(
    request: CreatePrayerIntentionRequest,
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
) -> PrayerIntentionCMSDTO:
    return cms_create_prayer_intention_service(
        token=authentication_credential.credentials,
        request=request,
    )


@cms_prayer_intentions_router.patch(
    "/{intention_id}",
    status_code=status.HTTP_200_OK,
    response_model=PrayerIntentionCMSDTO,
)
def cms_patch_prayer_intention(
    intention_id: UUID,
    request: PatchPrayerIntentionRequest,
    authentication_credential: Annotated[
        HTTPAuthorizationCredentials, Depends(oauth2_scheme)
    ],
) -> PrayerIntentionCMSDTO:
    return cms_patch_prayer_intention_service(
        token=authentication_credential.credentials,
        intention_id=intention_id,
        request=request,
    )
