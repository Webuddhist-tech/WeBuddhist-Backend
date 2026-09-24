from __future__ import annotations

import logging
from typing import IO, Any

import httpx
from fastapi import HTTPException
from starlette import status

from pecha_api.external_clients import get_authenticated_open_pecha_client

logger = logging.getLogger(__name__)

_UNEXPECTED_UPSTREAM_RESPONSE = "Unexpected response from upstream service"


def _client() -> httpx.AsyncClient:
    return get_authenticated_open_pecha_client().get_async_httpx_client()


async def fetch_edition_recordings(edition_id: str) -> list[dict[str, Any]]:
    try:
        response = await _client().get(f"/v2/editions/{edition_id}/recordings")
    except Exception:
        logger.exception("Failed to fetch edition recordings from OpenPecha API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch recordings from upstream service",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Edition with id '{edition_id}' not found",
        )
    if response.status_code != 200:
        logger.error("Unexpected status %d fetching edition recordings", response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNEXPECTED_UPSTREAM_RESPONSE,
        )
    return response.json()


async def create_edition_recording(
    edition_id: str,
    metadata_json: str,
    filename: str,
    content_type: str,
    file: IO[bytes],
) -> str:
    try:
        # Stream directly from the (typically disk-backed, for real-sized
        # uploads) spooled file instead of taking a `bytes` argument, so this
        # layer never has to hold a second full-size copy of the recording
        # in memory alongside FastAPI's own upload buffer.
        response = await _client().post(
            f"/v2/editions/{edition_id}/recordings",
            data={"metadata": metadata_json},
            files={"audio": (filename, file, content_type)},
        )
    except Exception:
        logger.exception("Failed to create edition recording via OpenPecha API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload recording to upstream service",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Edition with id '{edition_id}' not found",
        )
    if response.status_code == 422:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=response.json(),
        )
    if response.status_code != 201:
        logger.error("Unexpected status %d creating edition recording", response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNEXPECTED_UPSTREAM_RESPONSE,
        )
    return response.json()["id"]


async def fetch_persons(name: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if name:
        params["name"] = name
    try:
        response = await _client().get("/v2/persons", params=params)
    except Exception:
        logger.exception("Failed to fetch persons from OpenPecha API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch persons from upstream service",
        )

    if response.status_code != 200:
        logger.error("Unexpected status %d fetching persons", response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNEXPECTED_UPSTREAM_RESPONSE,
        )
    # Unlike /v2/editions/{id}/recordings, this endpoint responds with a
    # PaginatedResponse envelope (`{"items": [...], "has_more": ..., ...}`)
    # rather than a bare array.
    return response.json()["items"]


async def fetch_recording(recording_id: str) -> dict[str, Any]:
    try:
        response = await _client().get(f"/v2/recordings/{recording_id}")
    except Exception:
        logger.exception("Failed to fetch recording from OpenPecha API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch recording from upstream service",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording with id '{recording_id}' not found",
        )
    if response.status_code != 200:
        logger.error("Unexpected status %d fetching recording", response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNEXPECTED_UPSTREAM_RESPONSE,
        )
    return response.json()


async def fetch_recording_audio_location(recording_id: str) -> str:
    try:
        # Disable redirect-following for this call only, so the presigned
        # Location header is returned instead of the client eagerly fetching
        # (and buffering) the audio bytes itself.
        response = await _client().get(
            f"/v2/recordings/{recording_id}/audio",
            follow_redirects=False,
        )
    except Exception:
        logger.exception("Failed to fetch recording audio location from OpenPecha API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch recording audio from upstream service",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording with id '{recording_id}' not found",
        )
    if response.status_code != 307:
        logger.error(
            "Unexpected status %d fetching recording audio location", response.status_code
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNEXPECTED_UPSTREAM_RESPONSE,
        )

    location = response.headers.get("location")
    if not location:
        logger.error("Missing Location header in recording audio redirect")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNEXPECTED_UPSTREAM_RESPONSE,
        )
    return location


async def patch_recording(recording_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await _client().patch(f"/v2/recordings/{recording_id}", json=payload)
    except Exception:
        logger.exception("Failed to update recording via OpenPecha API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to update recording via upstream service",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording with id '{recording_id}' not found",
        )
    if response.status_code == 422:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=response.json(),
        )
    if response.status_code != 200:
        logger.error("Unexpected status %d updating recording", response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNEXPECTED_UPSTREAM_RESPONSE,
        )
    return response.json()


async def delete_recording(recording_id: str) -> None:
    try:
        response = await _client().delete(f"/v2/recordings/{recording_id}")
    except Exception:
        logger.exception("Failed to delete recording via OpenPecha API")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to delete recording via upstream service",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording with id '{recording_id}' not found",
        )
    if response.status_code != 204:
        logger.error("Unexpected status %d deleting recording", response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNEXPECTED_UPSTREAM_RESPONSE,
        )
