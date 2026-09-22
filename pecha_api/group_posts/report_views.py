from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.group_posts.report_response_models import ReportGroupPostRequest
from pecha_api.group_posts.report_service import (
    report_comment_service,
    report_post_service,
)
from pecha_api.users.users_service import validate_and_extract_user_details

oauth2_scheme = HTTPBearer()

group_post_reports_router = APIRouter(
    prefix="/groups/author",
    tags=["Group Post Reports"],
)


@group_post_reports_router.post(
    "/posts/{post_id}/report",
    status_code=status.HTTP_204_NO_CONTENT,
)
def report_post(
    post_id: UUID,
    request: ReportGroupPostRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    """Report a post for moderation. One report per user per post; you cannot
    report your own post."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    report_post_service(
        post_id=post_id,
        user_id=user.id,
        reason=request.reason,
        description=request.description,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@group_post_reports_router.post(
    "/comments/{comment_id}/report",
    status_code=status.HTTP_204_NO_CONTENT,
)
def report_comment(
    comment_id: UUID,
    request: ReportGroupPostRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> Response:
    """Report a comment for moderation. One report per user per comment; you
    cannot report your own comment."""
    user = validate_and_extract_user_details(token=authentication_credential.credentials)
    report_comment_service(
        comment_id=comment_id,
        user_id=user.id,
        reason=request.reason,
        description=request.description,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
