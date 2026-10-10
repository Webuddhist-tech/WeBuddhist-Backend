from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from starlette import status

from pecha_api.plans.auth.cms_auth_deps import get_cms_author_token
from pecha_api.text_requests.text_request_enums import TextRequestStatus
from pecha_api.text_requests.text_request_response_models import (
    TextRequestDTO,
    TextRequestsResponse,
    UpdateTextRequestRequest,
)
from pecha_api.text_requests.text_request_service import (
    create_text_request_service,
    get_text_request_service,
    list_my_text_requests_service,
    list_text_requests_service,
    update_text_request_service,
)

cms_author_text_requests_router = APIRouter(
    prefix="/cms/author/text-requests",
    tags=["CMS Text Requests"],
)

cms_admin_text_requests_router = APIRouter(
    prefix="/cms/admin/text-requests",
    tags=["CMS Admin Text Requests"],
)


@cms_author_text_requests_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TextRequestDTO,
)
def create_text_request(
    background_tasks: BackgroundTasks,
    message: Annotated[str, Form()],
    files: Annotated[Optional[List[UploadFile]], File()] = None,
    group_id: Annotated[Optional[UUID], Form()] = None,
    collection_id: Annotated[Optional[UUID], Form()] = None,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
) -> TextRequestDTO:
    """Ask for texts (chants) that are not in the library yet.

    Sent as multipart/form-data. Only `message` is required; `files` may be
    repeated for each attachment (documents, archives such as zip, images),
    and each is stored in S3 as uploaded. `group_id` and `collection_id` say
    which space and chant collection the request was made from. The request
    is then posted to Discord when `DISCORD_TEXT_REQUEST_WEBHOOK_URL` is set.
    """
    return create_text_request_service(
        token=token,
        message=message,
        background_tasks=background_tasks,
        files=files,
        group_id=group_id,
        collection_id=collection_id,
    )


@cms_author_text_requests_router.get(
    "/mine",
    status_code=status.HTTP_200_OK,
    response_model=TextRequestsResponse,
)
def list_my_text_requests(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[Optional[TextRequestStatus], Query(alias="status")] = None,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
) -> TextRequestsResponse:
    """The signed-in author's own requests, newest first, with status and reply."""
    return list_my_text_requests_service(token=token, skip=skip, limit=limit, status_filter=status_filter)


@cms_admin_text_requests_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=TextRequestsResponse,
)
def list_text_requests(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[Optional[TextRequestStatus], Query(alias="status")] = None,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
) -> TextRequestsResponse:
    """Every text request, newest first. Super admin / content admin only."""
    return list_text_requests_service(token=token, skip=skip, limit=limit, status_filter=status_filter)


@cms_admin_text_requests_router.get(
    "/{request_id}",
    status_code=status.HTTP_200_OK,
    response_model=TextRequestDTO,
)
def get_text_request(
    request_id: UUID,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
) -> TextRequestDTO:
    """One text request. Super admin / content admin only."""
    return get_text_request_service(token=token, request_id=request_id)


@cms_admin_text_requests_router.patch(
    "/{request_id}",
    status_code=status.HTTP_200_OK,
    response_model=TextRequestDTO,
)
def update_text_request(
    request_id: UUID,
    request: UpdateTextRequestRequest,
    token: Annotated[str, Depends(get_cms_author_token)] = "",
) -> TextRequestDTO:
    """Set a request's status, reply and linked edition (`text_id`). Only the
    fields sent change; the caller is recorded as the responder. Super admin
    / content admin only."""
    return update_text_request_service(token=token, request_id=request_id, request=request)
