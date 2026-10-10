from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from pecha_api.text_requests.text_request_enums import TextRequestStatus


class TextRequestAuthorDTO(BaseModel):
    id: UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None


class TextRequestAttachmentDTO(BaseModel):
    filename: str
    content_type: str
    size: int
    url: str


class TextRequestDTO(BaseModel):
    id: UUID
    message: str
    status: TextRequestStatus
    reply: Optional[str] = None
    text_id: Optional[str] = None
    group_id: Optional[UUID] = None
    group_name: Optional[str] = None
    collection_id: Optional[UUID] = None
    collection_name: Optional[str] = None
    attachments: List[TextRequestAttachmentDTO]
    requester: Optional[TextRequestAuthorDTO] = None
    responder: Optional[TextRequestAuthorDTO] = None
    responded_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TextRequestsResponse(BaseModel):
    requests: List[TextRequestDTO]
    skip: int
    limit: int
    total: int


class UpdateTextRequestRequest(BaseModel):
    """Every field is optional; only the ones sent are changed. An empty
    `text_id` or `reply` clears it."""

    status: Optional[TextRequestStatus] = None
    reply: Optional[str] = None
    text_id: Optional[str] = None
