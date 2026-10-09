import logging
import uuid
from io import BytesIO
from typing import List, Optional

from fastapi import BackgroundTasks, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from starlette import status

from pecha_api.config import get, get_int
from pecha_api.db.database import SessionLocal
from pecha_api.feedback.discord_feedback_client import (
    FeedbackImage,
    FeedbackNotification,
    send_feedback_to_discord,
)
from pecha_api.feedback.feedback_models import Feedback
from pecha_api.feedback.feedback_repository import create_feedback
from pecha_api.feedback.feedback_response_models import FeedbackDTO
from pecha_api.uploads.S3_utils import delete_file, generate_presigned_access_url, upload_bytes
from pecha_api.users.users_service import validate_and_extract_user_details

logger = logging.getLogger(__name__)

PLATFORM_MAX_LENGTH = 255
APP_VERSION_MAX_LENGTH = 64

FEEDBACK_CONTENT_REQUIRED = "Feedback content must not be empty."
FEEDBACK_CONTENT_TOO_LONG = "Feedback content must be at most {max_length} characters."
FEEDBACK_TOO_MANY_IMAGES = "At most {max_images} images can be attached to a feedback."
FEEDBACK_IMAGES_TOO_LARGE = "Attached images must be at most {max_mb} MB in total."
FEEDBACK_INVALID_IMAGE = "Attachment '{filename}' is not a valid image."

# Pillow's format name -> the extension the object is stored under.
_IMAGE_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}


def _clean_optional(value: Optional[str], max_length: int) -> Optional[str]:
    # Device context is informational: a too-long OS version string is cut,
    # never a reason to throw the user's feedback away.
    if value is None:
        return None
    value = value.strip()
    return value[:max_length] or None


def _validate_content(content: Optional[str]) -> str:
    content = (content or "").strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=FEEDBACK_CONTENT_REQUIRED)
    max_length = get_int("FEEDBACK_MAX_CONTENT_LENGTH")
    if len(content) > max_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FEEDBACK_CONTENT_TOO_LONG.format(max_length=max_length),
        )
    return content


def _read_images(images: List[UploadFile]) -> List[FeedbackImage]:
    """Read and check every attachment before anything is stored.

    The type comes from the decoded bytes, not the client's content type or
    filename, so what lands in S3 and in Discord is known to be an image.
    """
    max_images = get_int("FEEDBACK_MAX_IMAGES")
    if len(images) > max_images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FEEDBACK_TOO_MANY_IMAGES.format(max_images=max_images),
        )

    max_mb = get_int("FEEDBACK_MAX_TOTAL_IMAGE_MB")
    remaining_bytes = max_mb * 1024 * 1024
    too_large = HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail=FEEDBACK_IMAGES_TOO_LARGE.format(max_mb=max_mb),
    )

    read_images: List[FeedbackImage] = []
    for index, upload in enumerate(images):
        upload.file.seek(0)
        # One byte past what is left, so an oversized upload is caught without
        # pulling the whole of it into memory.
        data = upload.file.read(remaining_bytes + 1)
        if len(data) > remaining_bytes:
            raise too_large
        remaining_bytes -= len(data)

        invalid_image = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FEEDBACK_INVALID_IMAGE.format(filename=upload.filename or index + 1),
        )
        try:
            with Image.open(BytesIO(data)) as image:
                image_format = image.format
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
            raise invalid_image
        extension = _IMAGE_EXTENSIONS.get(image_format or "")
        content_type = Image.MIME.get(image_format or "")
        if not extension or not content_type:
            raise invalid_image

        read_images.append(
            FeedbackImage(
                filename=f"feedback-{index + 1}{extension}",
                content_type=content_type,
                data=data,
            )
        )
    return read_images


def _discard(s3_keys: List[str]) -> None:
    for s3_key in s3_keys:
        try:
            delete_file(s3_key)
        except Exception:
            logger.exception("Failed to delete orphaned feedback image: %s", s3_key)


def _to_dto(feedback: Feedback) -> FeedbackDTO:
    return FeedbackDTO(
        id=feedback.id,
        user_id=feedback.user_id,
        content=feedback.content,
        image_urls=[
            generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key=s3_key)
            for s3_key in (feedback.image_keys or [])
        ],
        platform=feedback.platform,
        app_version=feedback.app_version,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


def submit_feedback_service(
    token: str,
    content: Optional[str],
    background_tasks: BackgroundTasks,
    images: Optional[List[UploadFile]] = None,
    platform: Optional[str] = None,
    app_version: Optional[str] = None,
) -> FeedbackDTO:
    """Store a user's feedback, then hand it to Discord.

    The database is the record: the Discord post is scheduled only once the
    row is committed, and runs after the response, so a missing or failing
    webhook never fails the request.
    """
    content = _validate_content(content)
    platform = _clean_optional(platform, PLATFORM_MAX_LENGTH)
    app_version = _clean_optional(app_version, APP_VERSION_MAX_LENGTH)
    feedback_images = _read_images(images or [])

    with SessionLocal() as db:
        current_user = validate_and_extract_user_details(token=token, db=db)
        user_id = current_user.id
        user_email = current_user.email
        feedback_id = uuid.uuid4()

        uploaded_keys: List[str] = []
        committed = False
        try:
            for image in feedback_images:
                s3_key = f"feedback/{user_id}/{feedback_id}/{image.filename}"
                upload_bytes(
                    bucket_name=get("AWS_BUCKET_NAME"),
                    s3_key=s3_key,
                    file=BytesIO(image.data),
                    content_type=image.content_type,
                )
                uploaded_keys.append(s3_key)

            feedback = create_feedback(
                db=db,
                feedback=Feedback(
                    id=feedback_id,
                    user_id=user_id,
                    content=content,
                    image_keys=uploaded_keys or None,
                    platform=platform,
                    app_version=app_version,
                ),
            )
            committed = True
        except Exception:
            # Only once the row is known not to have landed: after the commit
            # the images belong to a stored feedback.
            if not committed:
                _discard(uploaded_keys)
            raise

        background_tasks.add_task(
            send_feedback_to_discord,
            FeedbackNotification(
                feedback_id=feedback.id,
                user_id=user_id,
                user_email=user_email,
                content=content,
                platform=platform,
                app_version=app_version,
                images=feedback_images,
            ),
        )
        return _to_dto(feedback)
