from fastapi import APIRouter, Depends, File, Header, Query, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Annotated, Optional
from uuid import UUID
from starlette import status

from pecha_api.plans.language_constants import language_query_description
from pecha_api.plans.media.media_response_models import PlanUploadResponse
from .mantra_response_models import CMSMantraDTO, CreateMantraRequest, MantraResponse, UpdateMantraRequest
from .mantra_service import create_mantra_service, get_mantras_service, update_mantra_service, upload_mantra_image

oauth2_scheme = HTTPBearer()

mantra_router = APIRouter(
    prefix="/mantra",
    tags=["Mantra"]
)

cms_mantra_router = APIRouter(
    prefix="/cms/mantras",
    tags=["CMS Mantras"],
)


@mantra_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=MantraResponse
)
def get_mantras_endpoint(
    language: Annotated[Optional[str], Query(description=language_query_description("Filter by language code", lowercase_example=True))] = None,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted mantras are hidden for Chinese timezones."),
    ] = None,
):

    return get_mantras_service(language=language, timezone_name=x_timezone)


@cms_mantra_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CMSMantraDTO,
)
def create_mantra_endpoint(
    create_mantra_request: CreateMantraRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> CMSMantraDTO:
    return create_mantra_service(
        token=authentication_credential.credentials,
        request=create_mantra_request,
    )


@cms_mantra_router.patch(
    "/{mantra_id}",
    status_code=status.HTTP_200_OK,
    response_model=CMSMantraDTO,
)
def update_mantra_endpoint(
    mantra_id: UUID,
    update_mantra_request: UpdateMantraRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> CMSMantraDTO:
    return update_mantra_service(
        token=authentication_credential.credentials,
        mantra_id=mantra_id,
        request=update_mantra_request,
    )


@cms_mantra_router.post(
    "/image",
    status_code=status.HTTP_201_CREATED,
    response_model=PlanUploadResponse,
)
def upload_mantra_image_endpoint(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    mantra_id: UUID = Query(...),
    file: UploadFile = File(...),
) -> PlanUploadResponse:
    return upload_mantra_image(
        token=authentication_credential.credentials,
        mantra_id=mantra_id,
        file=file,
    )
