from typing import Annotated, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from pecha_api.feedback.feedback_response_models import FeedbackDTO
from pecha_api.feedback.feedback_service import submit_feedback_service

oauth2_scheme = HTTPBearer()
feedback_router = APIRouter(
    prefix="/feedback",
    tags=["User Feedback"],
)


@feedback_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackDTO,
)
def submit_feedback(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    background_tasks: BackgroundTasks,
    content: Annotated[str, Form()],
    images: Annotated[Optional[List[UploadFile]], File()] = None,
    platform: Annotated[Optional[str], Form()] = None,
    app_version: Annotated[Optional[str], Form()] = None,
) -> FeedbackDTO:
    """Store the signed-in user's feedback, then forward it to Discord.

    Sent as multipart/form-data. Only `content` is required; `images` may be
    repeated for each attachment. The Discord post happens after the
    response and only when `DISCORD_FEEDBACK_WEBHOOK_URL` is set.
    """
    return submit_feedback_service(
        token=authentication_credential.credentials,
        content=content,
        background_tasks=background_tasks,
        images=images,
        platform=platform,
        app_version=app_version,
    )
