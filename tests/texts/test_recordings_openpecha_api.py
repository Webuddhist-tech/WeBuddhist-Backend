from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status

from pecha_api.texts.recordings_openpecha_api import (
    create_edition_recording,
    delete_recording,
    fetch_edition_recordings,
    fetch_persons,
    fetch_recording,
    fetch_recording_audio_location,
    patch_recording,
)

EDITION_ID = "ED123"
RECORDING_ID = "REC1"

RAW_RECORDING = {
    "id": RECORDING_ID,
    "edition_id": EDITION_ID,
    "text_id": "TXT1",
    "contributions": [{"type": "person", "id": "PER1", "role": "narrator"}],
    "format": "mp3",
    "size_bytes": 100,
}


def _make_mock_client(**method_responses):
    """Build a mock authenticated client whose async httpx client returns the
    given canned response for each HTTP method passed in (get/post/patch/delete)."""
    mock_http_client = AsyncMock()
    for method, response in method_responses.items():
        setattr(mock_http_client, method, AsyncMock(return_value=response))

    mock_client = MagicMock()
    mock_client.get_async_httpx_client.return_value = mock_http_client
    return mock_client


def _response(status_code: int, json_data=None, headers=None):
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data
    mock_response.headers = headers or {}
    return mock_response


PATCH_TARGET = "pecha_api.texts.recordings_openpecha_api.get_authenticated_open_pecha_client"


# ============================================================================
# fetch_edition_recordings
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_edition_recordings_success(mocker):
    mocker.patch(
        PATCH_TARGET,
        return_value=_make_mock_client(get=_response(200, [RAW_RECORDING])),
    )
    result = await fetch_edition_recordings(edition_id=EDITION_ID)
    assert result == [RAW_RECORDING]


@pytest.mark.asyncio
async def test_fetch_edition_recordings_404(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(get=_response(404)))
    with pytest.raises(HTTPException) as exc_info:
        await fetch_edition_recordings(edition_id=EDITION_ID)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_fetch_edition_recordings_unexpected_status(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(get=_response(500)))
    with pytest.raises(HTTPException) as exc_info:
        await fetch_edition_recordings(edition_id=EDITION_ID)
    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY


# ============================================================================
# fetch_persons
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_persons_success(mocker):
    raw_person = {"id": "P1", "name": {"en": "Jane"}, "bdrc": "P123"}
    mock_client = _make_mock_client(
        get=_response(
            200,
            {"items": [raw_person], "has_more": False, "offset": 0, "limit": 20},
        )
    )
    mocker.patch(PATCH_TARGET, return_value=mock_client)

    result = await fetch_persons(name="Jane", limit=20, offset=0)

    assert result == [raw_person]
    mock_client.get_async_httpx_client().get.assert_awaited_once_with(
        "/v2/persons", params={"limit": 20, "offset": 0, "name": "Jane"}
    )


@pytest.mark.asyncio
async def test_fetch_persons_omits_blank_name_filter(mocker):
    mock_client = _make_mock_client(
        get=_response(
            200, {"items": [], "has_more": False, "offset": 0, "limit": 20}
        )
    )
    mocker.patch(PATCH_TARGET, return_value=mock_client)

    await fetch_persons(name=None, limit=20, offset=0)

    mock_client.get_async_httpx_client().get.assert_awaited_once_with(
        "/v2/persons", params={"limit": 20, "offset": 0}
    )


@pytest.mark.asyncio
async def test_fetch_persons_unexpected_status(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(get=_response(500)))
    with pytest.raises(HTTPException) as exc_info:
        await fetch_persons(name=None, limit=20, offset=0)
    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.asyncio
async def test_fetch_edition_recordings_network_error(mocker):
    mock_client = MagicMock()
    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(side_effect=RuntimeError("boom"))
    mock_client.get_async_httpx_client.return_value = mock_http_client
    mocker.patch(PATCH_TARGET, return_value=mock_client)

    with pytest.raises(HTTPException) as exc_info:
        await fetch_edition_recordings(edition_id=EDITION_ID)
    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY


# ============================================================================
# create_edition_recording
# ============================================================================

@pytest.mark.asyncio
async def test_create_edition_recording_success(mocker):
    mocker.patch(
        PATCH_TARGET,
        return_value=_make_mock_client(post=_response(201, {"id": RECORDING_ID})),
    )
    result = await create_edition_recording(
        edition_id=EDITION_ID,
        metadata_json='{"contributions":[]}',
        filename="reading.mp3",
        content_type="audio/mpeg",
        file=BytesIO(b"bytes"),
    )
    assert result == RECORDING_ID


@pytest.mark.asyncio
async def test_create_edition_recording_422(mocker):
    mocker.patch(
        PATCH_TARGET,
        return_value=_make_mock_client(post=_response(422, {"detail": "bad"})),
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_edition_recording(
            edition_id=EDITION_ID,
            metadata_json="{}",
            filename="reading.mp3",
            content_type="audio/mpeg",
            file=BytesIO(b"bytes"),
        )
    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_create_edition_recording_404(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(post=_response(404)))
    with pytest.raises(HTTPException) as exc_info:
        await create_edition_recording(
            edition_id=EDITION_ID,
            metadata_json="{}",
            filename="reading.mp3",
            content_type="audio/mpeg",
            file=BytesIO(b"bytes"),
        )
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# fetch_recording
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_recording_success(mocker):
    mocker.patch(
        PATCH_TARGET,
        return_value=_make_mock_client(get=_response(200, RAW_RECORDING)),
    )
    result = await fetch_recording(recording_id=RECORDING_ID)
    assert result == RAW_RECORDING


@pytest.mark.asyncio
async def test_fetch_recording_404(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(get=_response(404)))
    with pytest.raises(HTTPException) as exc_info:
        await fetch_recording(recording_id=RECORDING_ID)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# fetch_recording_audio_location
# ============================================================================

@pytest.mark.asyncio
async def test_fetch_recording_audio_location_success(mocker):
    mocker.patch(
        PATCH_TARGET,
        return_value=_make_mock_client(
            get=_response(307, headers={"location": "https://s3.example.com/signed"})
        ),
    )
    result = await fetch_recording_audio_location(recording_id=RECORDING_ID)
    assert result == "https://s3.example.com/signed"


@pytest.mark.asyncio
async def test_fetch_recording_audio_location_missing_header_raises_502(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(get=_response(307)))
    with pytest.raises(HTTPException) as exc_info:
        await fetch_recording_audio_location(recording_id=RECORDING_ID)
    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.asyncio
async def test_fetch_recording_audio_location_404(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(get=_response(404)))
    with pytest.raises(HTTPException) as exc_info:
        await fetch_recording_audio_location(recording_id=RECORDING_ID)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# patch_recording
# ============================================================================

@pytest.mark.asyncio
async def test_patch_recording_success(mocker):
    mocker.patch(
        PATCH_TARGET,
        return_value=_make_mock_client(patch=_response(200, RAW_RECORDING)),
    )
    result = await patch_recording(recording_id=RECORDING_ID, payload={"duration_ms": 1})
    assert result == RAW_RECORDING


@pytest.mark.asyncio
async def test_patch_recording_404(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(patch=_response(404)))
    with pytest.raises(HTTPException) as exc_info:
        await patch_recording(recording_id=RECORDING_ID, payload={})
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# delete_recording
# ============================================================================

@pytest.mark.asyncio
async def test_delete_recording_success(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(delete=_response(204)))
    await delete_recording(recording_id=RECORDING_ID)


@pytest.mark.asyncio
async def test_delete_recording_404(mocker):
    mocker.patch(PATCH_TARGET, return_value=_make_mock_client(delete=_response(404)))
    with pytest.raises(HTTPException) as exc_info:
        await delete_recording(recording_id=RECORDING_ID)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
