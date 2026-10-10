import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.config import get, get_int
from pecha_api.db.database import SessionLocal
from pecha_api.group_recitation_collection.repository import get_collection_by_id
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.groups.groups_repository import get_group_by_id
from pecha_api.plans.response_message import NOT_FOUND
from pecha_api.plans.shared.permissions import (
    require_active_author,
    require_can_create_content,
    require_cms_write_access,
    require_content_manager,
)
from pecha_api.text_requests.discord_text_request_client import (
    TextRequestAttachmentLink,
    TextRequestNotification,
    send_text_request_to_discord,
)
from pecha_api.text_requests.text_request_enums import TextRequestStatus
from pecha_api.text_requests.text_request_models import TextRequest
from pecha_api.text_requests.text_request_repository import (
    create_text_request,
    get_text_request_by_id,
    list_text_requests,
    save_text_request,
)
from pecha_api.text_requests.text_request_response_models import (
    TextRequestAttachmentDTO,
    TextRequestAuthorDTO,
    TextRequestDTO,
    TextRequestsResponse,
    UpdateTextRequestRequest,
)
from pecha_api.uploads.S3_utils import delete_file, generate_presigned_access_url, upload_stream

logger = logging.getLogger(__name__)

TEXT_ID_MAX_LENGTH = 255
FILENAME_MAX_LENGTH = 150

TEXT_REQUEST_MESSAGE_REQUIRED = "A message describing the requested texts is required."
TEXT_REQUEST_MESSAGE_TOO_LONG = "The message must be at most {max_length} characters."
TEXT_REQUEST_REPLY_TOO_LONG = "The reply must be at most {max_length} characters."
TEXT_REQUEST_TEXT_ID_TOO_LONG = "The text id must be at most {max_length} characters."
TEXT_REQUEST_TOO_MANY_ATTACHMENTS = "At most {max_files} files can be attached to a request."
TEXT_REQUEST_ATTACHMENTS_TOO_LARGE = "Attached files must be at most {max_mb} MB in total."
TEXT_REQUEST_EMPTY_ATTACHMENT = "Attachment '{filename}' is empty."
TEXT_REQUEST_UNSUPPORTED_ATTACHMENT = (
    "Attachment '{filename}' is not a supported file type. "
    "Supported: {extensions}."
)
TEXT_REQUEST_COLLECTION_NEEDS_GROUP = "A chant collection can only be given together with its space."

# Documents, archives and images someone may send a text as. The stored type
# comes from this map, never from the client, and every file is served as a
# download, so nothing uploaded here renders in a browser.
_ATTACHMENT_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".epub": "application/epub+zip",
    ".xml": "application/xml",
    ".json": "application/json",
    ".zip": "application/zip",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\- ()]+", re.UNICODE)


@dataclass(frozen=True)
class _PendingAttachment:
    upload: UploadFile
    filename: str
    content_type: str
    size: int


def _clean_filename(raw: Optional[str], index: int) -> str:
    # Browsers on Windows may send a full path; only the last part is a name.
    name = os.path.basename((raw or "").replace("\\", "/")).strip()
    name = _UNSAFE_FILENAME_CHARS.sub("_", name).strip(". ")
    if not name:
        name = f"attachment-{index + 1}"
    if len(name) > FILENAME_MAX_LENGTH:
        stem, extension = os.path.splitext(name)
        name = stem[: FILENAME_MAX_LENGTH - len(extension)] + extension
    return name


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _validate_message(message: Optional[str]) -> str:
    message = (message or "").strip()
    if not message:
        raise _bad_request(TEXT_REQUEST_MESSAGE_REQUIRED)
    max_length = get_int("TEXT_REQUEST_MAX_MESSAGE_LENGTH")
    if len(message) > max_length:
        raise _bad_request(TEXT_REQUEST_MESSAGE_TOO_LONG.format(max_length=max_length))
    return message


def _upload_size(upload: UploadFile) -> int:
    upload.file.seek(0, os.SEEK_END)
    size = upload.file.tell()
    upload.file.seek(0)
    return size


def _check_attachments(files: List[UploadFile]) -> List[_PendingAttachment]:
    """Check every attachment before anything is stored, so a request is
    either kept with all its files or rejected with none uploaded."""
    max_files = get_int("TEXT_REQUEST_MAX_ATTACHMENTS")
    if len(files) > max_files:
        raise _bad_request(TEXT_REQUEST_TOO_MANY_ATTACHMENTS.format(max_files=max_files))

    max_mb = get_int("TEXT_REQUEST_MAX_TOTAL_ATTACHMENT_MB")
    remaining_bytes = max_mb * 1024 * 1024

    pending: List[_PendingAttachment] = []
    used_names = set()
    for index, upload in enumerate(files):
        filename = _clean_filename(upload.filename, index)
        extension = os.path.splitext(filename)[1].lower()
        content_type = _ATTACHMENT_CONTENT_TYPES.get(extension)
        if content_type is None:
            raise _bad_request(
                TEXT_REQUEST_UNSUPPORTED_ATTACHMENT.format(
                    filename=filename,
                    extensions=", ".join(sorted(_ATTACHMENT_CONTENT_TYPES)),
                )
            )

        size = _upload_size(upload)
        if size == 0:
            raise _bad_request(TEXT_REQUEST_EMPTY_ATTACHMENT.format(filename=filename))
        remaining_bytes -= size
        if remaining_bytes < 0:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=TEXT_REQUEST_ATTACHMENTS_TOO_LARGE.format(max_mb=max_mb),
            )

        # Two files of the same name would land on the same S3 key.
        unique_name = filename
        stem, ext = os.path.splitext(filename)
        counter = 2
        while unique_name.lower() in used_names:
            unique_name = f"{stem} ({counter}){ext}"
            counter += 1
        used_names.add(unique_name.lower())

        pending.append(
            _PendingAttachment(upload=upload, filename=unique_name, content_type=content_type, size=size)
        )
    return pending


def _content_disposition(filename: str) -> str:
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii").replace('"', "") or "attachment"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"


def _discard(s3_keys: List[str]) -> None:
    for s3_key in s3_keys:
        try:
            delete_file(s3_key)
        except Exception:
            logger.exception("Failed to delete orphaned text request attachment: %s", s3_key)


def _signed_url(s3_key: str) -> str:
    try:
        return generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key=s3_key)
    except Exception:
        logger.exception("Failed to sign text request attachment: %s", s3_key)
        return ""


def _author_dto(author: Optional[Author]) -> Optional[TextRequestAuthorDTO]:
    if author is None:
        return None
    return TextRequestAuthorDTO(
        id=author.id,
        first_name=author.first_name,
        last_name=author.last_name,
        email=author.email,
    )


def _author_name(author: Optional[Author]) -> Optional[str]:
    if author is None:
        return None
    name = f"{author.first_name or ''} {author.last_name or ''}".strip()
    return name or author.email


def _group_name(group) -> Optional[str]:
    if group is None:
        return None
    entries = group.metadata_entries or []
    for entry in entries:
        language = entry.language.value if hasattr(entry.language, "value") else str(entry.language)
        if language.upper() == "EN":
            return entry.title
    return entries[0].title if entries else group.slug


def _collection_name(collection) -> Optional[str]:
    if collection is None or collection.deleted_at is not None:
        return None
    return collection.name


def _to_dto(text_request: TextRequest) -> TextRequestDTO:
    return TextRequestDTO(
        id=text_request.id,
        message=text_request.message,
        status=TextRequestStatus(text_request.status),
        reply=text_request.reply,
        text_id=text_request.text_id,
        group_id=text_request.group_id,
        group_name=_group_name(text_request.group),
        collection_id=text_request.collection_id,
        collection_name=_collection_name(text_request.collection),
        attachments=[
            TextRequestAttachmentDTO(
                filename=attachment["filename"],
                content_type=attachment["content_type"],
                size=attachment["size"],
                url=_signed_url(attachment["key"]),
            )
            for attachment in (text_request.attachments or [])
        ],
        requester=_author_dto(text_request.requester),
        responder=_author_dto(text_request.responder),
        responded_at=text_request.responded_at,
        created_at=text_request.created_at,
        updated_at=text_request.updated_at,
    )


def _validate_context(
    db: Session,
    author: Author,
    group_id: Optional[UUID],
    collection_id: Optional[UUID],
) -> None:
    if collection_id is not None and group_id is None:
        raise _bad_request(TEXT_REQUEST_COLLECTION_NEEDS_GROUP)
    if group_id is None:
        return
    if get_group_by_id(db=db, group_id=group_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    # Asking for texts from inside a space is part of building its content.
    require_can_create_content(db=db, group_id=group_id, author=author)
    if collection_id is not None and get_collection_by_id(
        db=db, collection_id=collection_id, group_id=group_id
    ) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


def create_text_request_service(
    token: str,
    message: Optional[str],
    background_tasks: BackgroundTasks,
    files: Optional[List[UploadFile]] = None,
    group_id: Optional[UUID] = None,
    collection_id: Optional[UUID] = None,
) -> TextRequestDTO:
    """Store an author's request for texts, then hand it to Discord.

    The database is the record: the Discord post is scheduled only once the
    row is committed, and runs after the response, so a missing or failing
    webhook never fails the request.
    """
    author = validate_and_extract_author_details(token=token)
    require_active_author(author)
    require_cms_write_access(author)
    message = _validate_message(message)
    pending = _check_attachments(files or [])

    with SessionLocal() as db:
        _validate_context(db=db, author=author, group_id=group_id, collection_id=collection_id)

        request_id = uuid.uuid4()
        uploaded_keys: List[str] = []
        stored_attachments: List[dict] = []
        committed = False
        try:
            for attachment in pending:
                s3_key = f"text-requests/{request_id}/{attachment.filename}"
                upload_stream(
                    bucket_name=get("AWS_BUCKET_NAME"),
                    s3_key=s3_key,
                    fileobj=attachment.upload.file,
                    content_type=attachment.content_type,
                    content_disposition=_content_disposition(attachment.filename),
                )
                uploaded_keys.append(s3_key)
                stored_attachments.append(
                    {
                        "key": s3_key,
                        "filename": attachment.filename,
                        "content_type": attachment.content_type,
                        "size": attachment.size,
                    }
                )

            text_request = create_text_request(
                db=db,
                text_request=TextRequest(
                    id=request_id,
                    requester_author_id=author.id,
                    group_id=group_id,
                    collection_id=collection_id,
                    message=message,
                    attachments=stored_attachments,
                    status=TextRequestStatus.PENDING.value,
                ),
            )
            committed = True
        except Exception:
            # Only once the row is known not to have landed: after the commit
            # the files belong to a stored request.
            if not committed:
                _discard(uploaded_keys)
            raise

        dto = _to_dto(text_request)
        background_tasks.add_task(
            send_text_request_to_discord,
            TextRequestNotification(
                request_id=dto.id,
                requester_name=_author_name(author),
                requester_email=author.email,
                group_name=dto.group_name,
                collection_name=dto.collection_name,
                message=dto.message,
                attachments=[
                    TextRequestAttachmentLink(filename=a.filename, size=a.size, url=a.url)
                    for a in dto.attachments
                    if a.url
                ],
            ),
        )
        return dto


def list_my_text_requests_service(
    token: str,
    skip: int = 0,
    limit: int = 20,
    status_filter: Optional[TextRequestStatus] = None,
) -> TextRequestsResponse:
    """The caller's own requests, newest first, so they can follow the reply."""
    author = validate_and_extract_author_details(token=token)
    require_active_author(author)
    with SessionLocal() as db:
        rows, total = list_text_requests(
            db=db,
            skip=skip,
            limit=limit,
            status=status_filter,
            requester_author_id=author.id,
        )
        return TextRequestsResponse(
            requests=[_to_dto(row) for row in rows],
            skip=skip,
            limit=limit,
            total=total,
        )


def _require_text_request_admin(token: str) -> Author:
    author = validate_and_extract_author_details(token=token)
    require_active_author(author)
    # Super admins and content admins: the people who add texts to the library.
    require_content_manager(author)
    return author


def list_text_requests_service(
    token: str,
    skip: int = 0,
    limit: int = 20,
    status_filter: Optional[TextRequestStatus] = None,
) -> TextRequestsResponse:
    _require_text_request_admin(token)
    with SessionLocal() as db:
        rows, total = list_text_requests(db=db, skip=skip, limit=limit, status=status_filter)
        return TextRequestsResponse(
            requests=[_to_dto(row) for row in rows],
            skip=skip,
            limit=limit,
            total=total,
        )


def _get_or_404(db: Session, request_id: UUID) -> TextRequest:
    text_request = get_text_request_by_id(db=db, request_id=request_id)
    if text_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return text_request


def get_text_request_service(token: str, request_id: UUID) -> TextRequestDTO:
    _require_text_request_admin(token)
    with SessionLocal() as db:
        return _to_dto(_get_or_404(db=db, request_id=request_id))


def update_text_request_service(
    token: str,
    request_id: UUID,
    request: UpdateTextRequestRequest,
) -> TextRequestDTO:
    """Set the status, the reply and the linked edition. Whoever saves a change
    is recorded as the responder."""
    author = _require_text_request_admin(token)
    fields_set = request.model_fields_set

    with SessionLocal() as db:
        text_request = _get_or_404(db=db, request_id=request_id)
        changed = False

        if "status" in fields_set and request.status is not None:
            if text_request.status != request.status.value:
                text_request.status = request.status.value
                changed = True

        if "reply" in fields_set:
            reply = (request.reply or "").strip() or None
            max_length = get_int("TEXT_REQUEST_MAX_REPLY_LENGTH")
            if reply and len(reply) > max_length:
                raise _bad_request(TEXT_REQUEST_REPLY_TOO_LONG.format(max_length=max_length))
            if text_request.reply != reply:
                text_request.reply = reply
                changed = True

        if "text_id" in fields_set:
            text_id = (request.text_id or "").strip() or None
            if text_id and len(text_id) > TEXT_ID_MAX_LENGTH:
                raise _bad_request(TEXT_REQUEST_TEXT_ID_TOO_LONG.format(max_length=TEXT_ID_MAX_LENGTH))
            if text_request.text_id != text_id:
                text_request.text_id = text_id
                changed = True

        if changed:
            text_request.responder_author_id = author.id
            text_request.responded_at = datetime.now(timezone.utc)
            text_request = save_text_request(db=db, text_request=text_request)

        return _to_dto(text_request)
