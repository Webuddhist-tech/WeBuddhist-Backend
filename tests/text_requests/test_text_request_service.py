from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

# Registers every mapper, so the TextRequest relationships can resolve.
import pecha_api.app  # noqa: F401

from pecha_api.text_requests.text_request_enums import TextRequestStatus
from pecha_api.text_requests.text_request_models import TextRequest
from pecha_api.text_requests.text_request_response_models import UpdateTextRequestRequest
from pecha_api.text_requests.text_request_service import (
    create_text_request_service,
    list_my_text_requests_service,
    list_text_requests_service,
    update_text_request_service,
)

SERVICE = "pecha_api.text_requests.text_request_service"


def _upload(filename: str, data: bytes = b"some bytes") -> UploadFile:
    return UploadFile(file=BytesIO(data), filename=filename)


def _author(role: str = "CREATOR"):
    author = MagicMock()
    author.id = uuid4()
    author.first_name = "Tenzin"
    author.last_name = "Dolma"
    author.email = "author@example.com"
    author.is_active = True
    author.platform_role = role
    return author


def _stamp(text_request: TextRequest, requester=None) -> TextRequest:
    now = datetime.now(timezone.utc)
    text_request.created_at = now
    text_request.updated_at = now
    text_request.requester = requester
    text_request.responder = None
    text_request.group = None
    text_request.collection = None
    return text_request


@pytest.fixture
def mocks():
    author = _author()
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    with patch(f"{SERVICE}.SessionLocal", return_value=db), patch(
        f"{SERVICE}.validate_and_extract_author_details", return_value=author
    ), patch(f"{SERVICE}.upload_stream") as upload, patch(
        f"{SERVICE}.create_text_request",
        side_effect=lambda db, text_request: _stamp(text_request, author),
    ) as create, patch(f"{SERVICE}.delete_file") as delete, patch(
        f"{SERVICE}.get_group_by_id", return_value=MagicMock()
    ) as get_group, patch(f"{SERVICE}.require_can_create_content") as can_create, patch(
        f"{SERVICE}.get_collection_by_id", return_value=MagicMock()
    ) as get_collection, patch(
        f"{SERVICE}.generate_presigned_access_url",
        side_effect=lambda bucket_name, s3_key: f"https://signed/{s3_key}",
    ):
        yield {
            "author": author,
            "db": db,
            "upload": upload,
            "create": create,
            "delete": delete,
            "get_group": get_group,
            "can_create": can_create,
            "get_collection": get_collection,
        }


def test_create_uploads_files_stores_request_and_schedules_discord(mocks):
    background_tasks = BackgroundTasks()
    group_id = uuid4()
    collection_id = uuid4()

    result = create_text_request_service(
        token="token",
        message="  Please add the Heart Sutra in Tibetan.  ",
        background_tasks=background_tasks,
        files=[_upload("heart sutra.pdf"), _upload("C:\\scans\\pages.zip")],
        group_id=group_id,
        collection_id=collection_id,
    )

    stored = mocks["create"].call_args.kwargs["text_request"]
    assert result.message == "Please add the Heart Sutra in Tibetan."
    assert result.status == TextRequestStatus.PENDING
    assert stored.requester_author_id == mocks["author"].id
    assert stored.group_id == group_id
    assert stored.collection_id == collection_id
    assert [a["key"] for a in stored.attachments] == [
        f"text-requests/{stored.id}/heart sutra.pdf",
        f"text-requests/{stored.id}/pages.zip",
    ]
    assert [a["content_type"] for a in stored.attachments] == ["application/pdf", "application/zip"]
    assert [a.url for a in result.attachments] == [
        f"https://signed/{a['key']}" for a in stored.attachments
    ]
    first_upload = mocks["upload"].call_args_list[0].kwargs
    assert first_upload["content_disposition"].startswith("attachment;")
    mocks["can_create"].assert_called_once()
    assert len(background_tasks.tasks) == 1
    notification = background_tasks.tasks[0].args[0]
    assert notification.requester_email == "author@example.com"
    assert len(notification.attachments) == 2


def test_create_without_files_or_group(mocks):
    result = create_text_request_service(
        token="token",
        message="Need the Medicine Buddha sadhana",
        background_tasks=BackgroundTasks(),
    )

    assert result.attachments == []
    mocks["upload"].assert_not_called()
    mocks["can_create"].assert_not_called()


def test_create_rejects_empty_message(mocks):
    with pytest.raises(HTTPException) as error:
        create_text_request_service(token="token", message="   ", background_tasks=BackgroundTasks())
    assert error.value.status_code == 400
    mocks["create"].assert_not_called()


def test_create_rejects_unsupported_file_before_uploading(mocks):
    with pytest.raises(HTTPException) as error:
        create_text_request_service(
            token="token",
            message="hello",
            background_tasks=BackgroundTasks(),
            files=[_upload("ok.pdf"), _upload("run.exe")],
        )
    assert error.value.status_code == 400
    assert "run.exe" in error.value.detail
    mocks["upload"].assert_not_called()


def test_create_rejects_files_over_total_size(mocks):
    with patch(f"{SERVICE}.get_int", side_effect=lambda key: {"TEXT_REQUEST_MAX_TOTAL_ATTACHMENT_MB": 1}.get(key, 4000)):
        with pytest.raises(HTTPException) as error:
            create_text_request_service(
                token="token",
                message="hello",
                background_tasks=BackgroundTasks(),
                files=[_upload("big.pdf", b"x" * (1024 * 1024 + 1))],
            )
    assert error.value.status_code == 413
    mocks["upload"].assert_not_called()


def test_create_renames_duplicate_filenames(mocks):
    create_text_request_service(
        token="token",
        message="hello",
        background_tasks=BackgroundTasks(),
        files=[_upload("a.pdf"), _upload("A.pdf")],
    )
    stored = mocks["create"].call_args.kwargs["text_request"]
    assert [a["filename"] for a in stored.attachments] == ["a.pdf", "A (2).pdf"]


def test_create_collection_needs_group(mocks):
    with pytest.raises(HTTPException) as error:
        create_text_request_service(
            token="token",
            message="hello",
            background_tasks=BackgroundTasks(),
            collection_id=uuid4(),
        )
    assert error.value.status_code == 400


def test_create_discards_uploads_when_save_fails(mocks):
    mocks["create"].side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        create_text_request_service(
            token="token",
            message="hello",
            background_tasks=BackgroundTasks(),
            files=[_upload("a.pdf")],
        )
    mocks["delete"].assert_called_once()


def test_reviewer_cannot_create(mocks):
    mocks["author"].platform_role = "REVIEWER"
    with pytest.raises(HTTPException) as error:
        create_text_request_service(token="token", message="hello", background_tasks=BackgroundTasks())
    assert error.value.status_code == 403


@pytest.mark.parametrize("role", ["CREATOR", "REVIEWER"])
def test_admin_list_forbidden_for_non_content_managers(mocks, role):
    mocks["author"].platform_role = role
    with pytest.raises(HTTPException) as error:
        list_text_requests_service(token="token")
    assert error.value.status_code == 403


@pytest.mark.parametrize("role", ["SUPER_ADMIN", "CONTENT_ADMIN"])
def test_admin_list_allowed_for_content_managers(mocks, role):
    mocks["author"].platform_role = role
    row = _stamp(
        TextRequest(id=uuid4(), message="m", attachments=[], status="PENDING"),
        requester=_author(),
    )
    with patch(f"{SERVICE}.list_text_requests", return_value=([row], 1)) as list_rows:
        result = list_text_requests_service(token="token", status_filter=TextRequestStatus.PENDING)
    assert result.total == 1
    assert result.requests[0].requester.email == "author@example.com"
    assert list_rows.call_args.kwargs["status"] == TextRequestStatus.PENDING


def test_list_mine_filters_by_requester(mocks):
    with patch(f"{SERVICE}.list_text_requests", return_value=([], 0)) as list_rows:
        list_my_text_requests_service(token="token")
    assert list_rows.call_args.kwargs["requester_author_id"] == mocks["author"].id


def test_update_sets_reply_text_id_status_and_responder(mocks):
    mocks["author"].platform_role = "CONTENT_ADMIN"
    row = _stamp(TextRequest(id=uuid4(), message="m", attachments=[], status="PENDING"))
    with patch(f"{SERVICE}.get_text_request_by_id", return_value=row), patch(
        f"{SERVICE}.save_text_request", side_effect=lambda db, text_request: text_request
    ) as save:
        result = update_text_request_service(
            token="token",
            request_id=row.id,
            request=UpdateTextRequestRequest(
                status=TextRequestStatus.COMPLETED,
                reply="  Added, see the linked edition.  ",
                text_id=" edition-123 ",
            ),
        )
    save.assert_called_once()
    assert row.responder_author_id == mocks["author"].id
    assert row.responded_at is not None
    assert result.status == TextRequestStatus.COMPLETED
    assert result.reply == "Added, see the linked edition."
    assert result.text_id == "edition-123"


def test_update_only_touches_sent_fields(mocks):
    mocks["author"].platform_role = "SUPER_ADMIN"
    row = _stamp(
        TextRequest(id=uuid4(), message="m", attachments=[], status="PENDING", reply="keep", text_id="e1")
    )
    with patch(f"{SERVICE}.get_text_request_by_id", return_value=row), patch(
        f"{SERVICE}.save_text_request", side_effect=lambda db, text_request: text_request
    ):
        result = update_text_request_service(
            token="token",
            request_id=row.id,
            request=UpdateTextRequestRequest(status=TextRequestStatus.IN_PROGRESS),
        )
    assert result.reply == "keep"
    assert result.text_id == "e1"
    assert result.status == TextRequestStatus.IN_PROGRESS


def test_update_without_changes_does_not_record_responder(mocks):
    mocks["author"].platform_role = "SUPER_ADMIN"
    row = _stamp(TextRequest(id=uuid4(), message="m", attachments=[], status="PENDING"))
    row.responder_author_id = None
    with patch(f"{SERVICE}.get_text_request_by_id", return_value=row), patch(
        f"{SERVICE}.save_text_request"
    ) as save:
        update_text_request_service(
            token="token",
            request_id=row.id,
            request=UpdateTextRequestRequest(status=TextRequestStatus.PENDING),
        )
    save.assert_not_called()
    assert row.responder_author_id is None


def test_update_missing_request_is_404(mocks):
    mocks["author"].platform_role = "SUPER_ADMIN"
    with patch(f"{SERVICE}.get_text_request_by_id", return_value=None):
        with pytest.raises(HTTPException) as error:
            update_text_request_service(
                token="token", request_id=uuid4(), request=UpdateTextRequestRequest(reply="x")
            )
    assert error.value.status_code == 404
