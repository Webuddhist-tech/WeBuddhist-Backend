from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status

from pecha_api.texts.text_recordings_models import (
    RecordingContribution,
    RecordingCreateMetadata,
    RecordingPatchRequest,
)
from pecha_api.texts.text_recordings_service import (
    create_edition_recording,
    delete_recording,
    get_edition_recordings,
    get_recording,
    search_persons,
    update_recording,
    validate_recording_audio_file,
)

TOKEN = "token-123"
EDITION_ID = "ED123"
RECORDING_ID = "REC1"
TEXT_ID = "TXT1"
AUDIO_URL = "https://s3.example.com/signed"

RAW_RECORDING = {
    "id": RECORDING_ID,
    "edition_id": EDITION_ID,
    "text_id": TEXT_ID,
    "contributions": [{"type": "person", "id": "PER1", "role": "narrator"}],
    "format": "mp3",
    "size_bytes": 100,
}

SERVICE = "pecha_api.texts.text_recordings_service"


def _make_upload_file(filename="reading.mp3", content=b"audio-bytes", size=None, content_type="audio/mpeg"):
    upload = MagicMock()
    upload.filename = filename
    upload.size = size if size is not None else len(content)
    upload.content_type = content_type
    upload.file = BytesIO(content)
    upload.read = AsyncMock(return_value=content)
    upload.seek = AsyncMock()
    return upload


def _patch_audio_location(mocker, url=AUDIO_URL):
    return mocker.patch(
        f"{SERVICE}.openpecha_api.fetch_recording_audio_location",
        new=AsyncMock(return_value=url),
    )


# ============================================================================
# validate_recording_audio_file
# ============================================================================

def test_validate_recording_audio_file_rejects_unsupported_extension():
    with pytest.raises(HTTPException) as exc_info:
        validate_recording_audio_file(_make_upload_file(filename="reading.txt"))
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_validate_recording_audio_file_rejects_oversized_file(mocker):
    mocker.patch(f"{SERVICE}.get_int", return_value=10)
    with pytest.raises(HTTPException) as exc_info:
        validate_recording_audio_file(_make_upload_file(size=1000))
    assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


def test_validate_recording_audio_file_accepts_valid_file():
    validate_recording_audio_file(_make_upload_file())


def test_validate_recording_audio_file_rejects_aac_unsupported_by_openpecha():
    """AAC isn't in OpenPecha's AudioFormat enum, so accepting it here would
    only defer the failure to a 422 from the upstream API."""
    with pytest.raises(HTTPException) as exc_info:
        validate_recording_audio_file(_make_upload_file(filename="reading.aac"))
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_validate_recording_audio_file_accepts_flac():
    validate_recording_audio_file(_make_upload_file(filename="reading.flac"))


# ============================================================================
# search_persons
# ============================================================================

@pytest.mark.asyncio
async def test_search_persons_returns_mapped_list(mocker):
    mock_validate = mocker.patch(f"{SERVICE}.validate_cms_author_details")
    mocker.patch(
        f"{SERVICE}.openpecha_api.fetch_persons",
        new=AsyncMock(return_value=[{"id": "P1", "name": {"en": "Jane"}, "bdrc": "P123"}]),
    )

    result = await search_persons(token=TOKEN, name="Jane", limit=20, offset=0)

    mock_validate.assert_called_once_with(token=TOKEN)
    assert len(result) == 1
    assert result[0].id == "P1"
    assert result[0].bdrc_id == "P123"


# ============================================================================
# get_edition_recordings
# ============================================================================

@pytest.mark.asyncio
async def test_get_edition_recordings_returns_mapped_list(mocker):
    mocker.patch(f"{SERVICE}.validate_cms_author_details")
    mocker.patch(f"{SERVICE}.fetch_edition_text_id", new=AsyncMock(return_value=TEXT_ID))
    mocker.patch(
        f"{SERVICE}.openpecha_api.fetch_edition_recordings",
        new=AsyncMock(return_value=[RAW_RECORDING]),
    )
    _patch_audio_location(mocker)

    result = await get_edition_recordings(token=TOKEN, edition_id=EDITION_ID)

    assert len(result) == 1
    assert result[0].id == RECORDING_ID
    assert result[0].audio_url == AUDIO_URL


# ============================================================================
# create_edition_recording
# ============================================================================

@pytest.mark.asyncio
async def test_create_edition_recording_uploads_and_refetches(mocker):
    mocker.patch(f"{SERVICE}.validate_cms_author_details")
    mocker.patch(f"{SERVICE}.fetch_edition_text_id", new=AsyncMock(return_value=TEXT_ID))
    mock_create = AsyncMock(return_value=RECORDING_ID)
    mocker.patch(f"{SERVICE}.openpecha_api.create_edition_recording", new=mock_create)
    mocker.patch(
        f"{SERVICE}.openpecha_api.fetch_recording", new=AsyncMock(return_value=RAW_RECORDING)
    )
    _patch_audio_location(mocker)

    metadata = RecordingCreateMetadata(
        contributions=[RecordingContribution(type="person", id="PER1", role="narrator")]
    )
    file = _make_upload_file()

    result = await create_edition_recording(
        token=TOKEN, edition_id=EDITION_ID, file=file, metadata=metadata
    )

    assert result.id == RECORDING_ID
    assert result.audio_url == AUDIO_URL
    mock_create.assert_awaited_once()
    _, kwargs = mock_create.call_args
    assert kwargs["edition_id"] == EDITION_ID
    assert kwargs["filename"] == "reading.mp3"
    assert kwargs["content_type"] == "audio/mpeg"
    assert kwargs["file"] is file.file
    file.seek.assert_awaited_once_with(0)


@pytest.mark.asyncio
async def test_create_edition_recording_rejects_invalid_file_before_upload(mocker):
    mocker.patch(f"{SERVICE}.validate_cms_author_details")
    mocker.patch(f"{SERVICE}.fetch_edition_text_id", new=AsyncMock(return_value=TEXT_ID))
    mock_create = AsyncMock()
    mocker.patch(f"{SERVICE}.openpecha_api.create_edition_recording", new=mock_create)

    metadata = RecordingCreateMetadata(
        contributions=[RecordingContribution(type="person", id="PER1", role="narrator")]
    )
    file = _make_upload_file(filename="reading.txt")

    with pytest.raises(HTTPException) as exc_info:
        await create_edition_recording(
            token=TOKEN, edition_id=EDITION_ID, file=file, metadata=metadata
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    mock_create.assert_not_awaited()


# ============================================================================
# get_recording
# ============================================================================

@pytest.mark.asyncio
async def test_get_recording_returns_mapped_response(mocker):
    mocker.patch(f"{SERVICE}.validate_cms_author_details")
    mocker.patch(
        f"{SERVICE}.openpecha_api.fetch_recording", new=AsyncMock(return_value=RAW_RECORDING)
    )
    _patch_audio_location(mocker)

    result = await get_recording(token=TOKEN, recording_id=RECORDING_ID)

    assert result.id == RECORDING_ID
    assert result.audio_url == AUDIO_URL


# ============================================================================
# update_recording
# ============================================================================

@pytest.mark.asyncio
async def test_update_recording_sends_patch_when_fields_set(mocker):
    mocker.patch(f"{SERVICE}.validate_cms_author_details")
    mock_patch = AsyncMock(return_value=RAW_RECORDING)
    mocker.patch(f"{SERVICE}.openpecha_api.patch_recording", new=mock_patch)
    mock_fetch = AsyncMock(return_value=RAW_RECORDING)
    mocker.patch(f"{SERVICE}.openpecha_api.fetch_recording", new=mock_fetch)
    _patch_audio_location(mocker)

    request = RecordingPatchRequest.model_validate({"duration_ms": 5000})
    result = await update_recording(token=TOKEN, recording_id=RECORDING_ID, request=request)

    assert result.id == RECORDING_ID
    mock_patch.assert_awaited_once_with(recording_id=RECORDING_ID, payload={"duration_ms": 5000})
    mock_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_recording_skips_upstream_patch_when_nothing_set(mocker):
    mocker.patch(f"{SERVICE}.validate_cms_author_details")
    mock_patch = AsyncMock()
    mocker.patch(f"{SERVICE}.openpecha_api.patch_recording", new=mock_patch)
    mock_fetch = AsyncMock(return_value=RAW_RECORDING)
    mocker.patch(f"{SERVICE}.openpecha_api.fetch_recording", new=mock_fetch)
    _patch_audio_location(mocker)

    request = RecordingPatchRequest()
    result = await update_recording(token=TOKEN, recording_id=RECORDING_ID, request=request)

    assert result.id == RECORDING_ID
    mock_patch.assert_not_awaited()
    mock_fetch.assert_awaited_once_with(recording_id=RECORDING_ID)


# ============================================================================
# delete_recording
# ============================================================================

@pytest.mark.asyncio
async def test_delete_recording_delegates_to_openpecha_api(mocker):
    mocker.patch(f"{SERVICE}.validate_cms_author_details")
    mock_delete = AsyncMock()
    mocker.patch(f"{SERVICE}.openpecha_api.delete_recording", new=mock_delete)

    await delete_recording(token=TOKEN, recording_id=RECORDING_ID)

    mock_delete.assert_awaited_once_with(recording_id=RECORDING_ID)
