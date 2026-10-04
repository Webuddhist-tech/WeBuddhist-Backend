from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from PIL import Image

from pecha_api.feedback.feedback_service import submit_feedback_service

SERVICE = "pecha_api.feedback.feedback_service"


def _png_upload(filename: str = "photo.png") -> UploadFile:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), color=(200, 100, 50)).save(buffer, format="PNG")
    buffer.seek(0)
    return UploadFile(file=buffer, filename=filename)


def _stamp(db, feedback):
    now = datetime.now(timezone.utc)
    feedback.created_at = now
    feedback.updated_at = now
    return feedback


@pytest.fixture
def mocks():
    user = MagicMock()
    user.id = uuid4()
    user.email = "user@example.com"

    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    with patch(f"{SERVICE}.SessionLocal", return_value=db), patch(
        f"{SERVICE}.validate_and_extract_user_details", return_value=user
    ) as validate, patch(f"{SERVICE}.upload_bytes") as upload, patch(
        f"{SERVICE}.create_feedback", side_effect=lambda db, feedback: _stamp(db, feedback)
    ) as create, patch(f"{SERVICE}.delete_file") as delete, patch(
        f"{SERVICE}.generate_presigned_access_url",
        side_effect=lambda bucket_name, s3_key: f"https://signed/{s3_key}",
    ):
        yield {
            "user": user,
            "db": db,
            "validate": validate,
            "upload": upload,
            "create": create,
            "delete": delete,
        }


def test_submit_feedback_stores_images_and_schedules_discord(mocks):
    background_tasks = BackgroundTasks()

    result = submit_feedback_service(
        token="token",
        content="  The timer stops when the screen locks.  ",
        background_tasks=background_tasks,
        images=[_png_upload(), _png_upload("second.png")],
        platform="android 14",
        app_version="2.3.1",
    )

    user_id = mocks["user"].id
    assert result.user_id == user_id
    assert result.content == "The timer stops when the screen locks."
    assert result.platform == "android 14"
    assert result.app_version == "2.3.1"

    stored = mocks["create"].call_args.kwargs["feedback"]
    assert stored.image_keys == [
        f"feedback/{user_id}/{stored.id}/feedback-1.png",
        f"feedback/{user_id}/{stored.id}/feedback-2.png",
    ]
    assert result.image_urls == [f"https://signed/{key}" for key in stored.image_keys]
    assert mocks["upload"].call_count == 2
    assert mocks["upload"].call_args.kwargs["content_type"] == "image/png"

    assert len(background_tasks.tasks) == 1
    notification = background_tasks.tasks[0].args[0]
    assert notification.feedback_id == stored.id
    assert notification.user_email == "user@example.com"
    assert [image.filename for image in notification.images] == ["feedback-1.png", "feedback-2.png"]


def test_submit_feedback_without_images_or_device_context(mocks):
    background_tasks = BackgroundTasks()

    result = submit_feedback_service(
        token="token",
        content="Love the app",
        background_tasks=background_tasks,
        platform="   ",
    )

    stored = mocks["create"].call_args.kwargs["feedback"]
    assert stored.image_keys is None
    assert stored.platform is None
    assert stored.app_version is None
    assert result.image_urls == []
    mocks["upload"].assert_not_called()
    assert len(background_tasks.tasks) == 1


def test_submit_feedback_truncates_long_device_context(mocks):
    submit_feedback_service(
        token="token",
        content="hi",
        background_tasks=BackgroundTasks(),
        platform="p" * 400,
        app_version="v" * 100,
    )

    stored = mocks["create"].call_args.kwargs["feedback"]
    assert len(stored.platform) == 255
    assert len(stored.app_version) == 64


@pytest.mark.parametrize("content", ["", "   ", None])
def test_submit_feedback_rejects_empty_content(mocks, content):
    background_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback_service(token="token", content=content, background_tasks=background_tasks)

    assert exc_info.value.status_code == 400
    mocks["create"].assert_not_called()
    assert background_tasks.tasks == []


def test_submit_feedback_rejects_too_long_content(mocks, monkeypatch):
    monkeypatch.setenv("FEEDBACK_MAX_CONTENT_LENGTH", "10")

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback_service(token="token", content="x" * 11, background_tasks=BackgroundTasks())

    assert exc_info.value.status_code == 400
    mocks["create"].assert_not_called()


def test_submit_feedback_rejects_too_many_images(mocks):
    with pytest.raises(HTTPException) as exc_info:
        submit_feedback_service(
            token="token",
            content="hi",
            background_tasks=BackgroundTasks(),
            images=[_png_upload() for _ in range(4)],
        )

    assert exc_info.value.status_code == 400
    mocks["upload"].assert_not_called()


def test_submit_feedback_rejects_non_image_attachment(mocks):
    not_an_image = UploadFile(file=BytesIO(b"definitely not a picture"), filename="photo.png")

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback_service(
            token="token",
            content="hi",
            background_tasks=BackgroundTasks(),
            images=[not_an_image],
        )

    assert exc_info.value.status_code == 400
    mocks["upload"].assert_not_called()


def test_submit_feedback_rejects_oversized_images(mocks, monkeypatch):
    monkeypatch.setenv("FEEDBACK_MAX_TOTAL_IMAGE_MB", "0")

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback_service(
            token="token",
            content="hi",
            background_tasks=BackgroundTasks(),
            images=[_png_upload()],
        )

    assert exc_info.value.status_code == 413
    mocks["upload"].assert_not_called()


def test_submit_feedback_discards_uploads_when_insert_fails(mocks):
    mocks["create"].side_effect = RuntimeError("db down")
    background_tasks = BackgroundTasks()

    with pytest.raises(RuntimeError):
        submit_feedback_service(
            token="token",
            content="hi",
            background_tasks=background_tasks,
            images=[_png_upload()],
        )

    uploaded_key = mocks["upload"].call_args.kwargs["s3_key"]
    mocks["delete"].assert_called_once_with(uploaded_key)
    assert background_tasks.tasks == []


def test_submit_feedback_requires_valid_user(mocks):
    mocks["validate"].side_effect = HTTPException(status_code=401, detail="bad token")

    with pytest.raises(HTTPException) as exc_info:
        submit_feedback_service(token="bad", content="hi", background_tasks=BackgroundTasks())

    assert exc_info.value.status_code == 401
    mocks["create"].assert_not_called()
