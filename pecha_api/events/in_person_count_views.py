from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from .in_person_count_response_models import (
    CreateInPersonCountRequest,
    InPersonCountDTO,
    InPersonCountsResponse,
    UpdateInPersonCountRequest,
)
from .in_person_count_service import (
    create_in_person_count_service,
    delete_in_person_count_service,
    list_in_person_counts_service,
    update_in_person_count_service,
)

oauth2_scheme = HTTPBearer()

cms_in_person_counts_router = APIRouter(
    prefix="/cms/events",
    tags=["CMS Events - In-person counts"],
)

Credentials = Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]


@cms_in_person_counts_router.get("/{event_id}/in-person-counts", status_code=status.HTTP_200_OK)
def list_in_person_counts(
    event_id: UUID,
    credentials: Credentials,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> InPersonCountsResponse:
    return list_in_person_counts_service(token=credentials.credentials, event_id=event_id, skip=skip, limit=limit)


@cms_in_person_counts_router.post("/{event_id}/in-person-counts", status_code=status.HTTP_201_CREATED)
def create_in_person_count(
    event_id: UUID, request: CreateInPersonCountRequest, credentials: Credentials
) -> InPersonCountDTO:
    return create_in_person_count_service(token=credentials.credentials, event_id=event_id, request=request)


@cms_in_person_counts_router.put("/{event_id}/in-person-counts/{history_id}", status_code=status.HTTP_200_OK)
def update_in_person_count(
    event_id: UUID, history_id: UUID, request: UpdateInPersonCountRequest, credentials: Credentials
) -> InPersonCountDTO:
    return update_in_person_count_service(
        token=credentials.credentials, event_id=event_id, history_id=history_id, request=request
    )


@cms_in_person_counts_router.delete(
    "/{event_id}/in-person-counts/{history_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_in_person_count(event_id: UUID, history_id: UUID, credentials: Credentials) -> None:
    delete_in_person_count_service(token=credentials.credentials, event_id=event_id, history_id=history_id)
