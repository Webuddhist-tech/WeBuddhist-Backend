from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from pecha_api.text_requests.text_request_enums import TextRequestStatus
from pecha_api.text_requests.text_request_models import TextRequest


def create_text_request(db: Session, text_request: TextRequest) -> TextRequest:
    db.add(text_request)
    db.commit()
    db.refresh(text_request)
    return text_request


def get_text_request_by_id(db: Session, request_id: UUID) -> Optional[TextRequest]:
    return db.query(TextRequest).filter(TextRequest.id == request_id).first()


def list_text_requests(
    db: Session,
    skip: int,
    limit: int,
    status: Optional[TextRequestStatus] = None,
    requester_author_id: Optional[UUID] = None,
) -> Tuple[List[TextRequest], int]:
    query = db.query(TextRequest)
    if status is not None:
        query = query.filter(TextRequest.status == status.value)
    if requester_author_id is not None:
        query = query.filter(TextRequest.requester_author_id == requester_author_id)
    total = query.count()
    rows = (
        query.order_by(TextRequest.created_at.desc(), TextRequest.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return rows, total


def save_text_request(db: Session, text_request: TextRequest) -> TextRequest:
    db.commit()
    db.refresh(text_request)
    return text_request
