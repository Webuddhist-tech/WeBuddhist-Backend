import json

import pytest
from pydantic import ValidationError

from pecha_api.texts.text_recordings_models import (
    AudioFormat,
    LicenseType,
    PersonResponse,
    RecordingContribution,
    RecordingCreateMetadata,
    RecordingPatchRequest,
    RecordingResponse,
)

RAW_RECORDING = {
    "id": "REC1",
    "edition_id": "ED123",
    "text_id": "TXT1",
    "title": {"en": "A Reading"},
    "language": "en",
    "license": "cc0",
    "date": "2024",
    "duration_ms": 12000,
    "contributions": [
        {"type": "person", "id": "PER123", "role": "narrator", "name": {"en": "Jane"}},
        {"type": "ai", "id": "AI-1", "role": "narrator"},
    ],
    "format": "mp3",
    "size_bytes": 4096,
}


# ============================================================================
# RecordingContribution
# ============================================================================

def test_person_contribution_to_upstream_payload_omits_blank_fields():
    contribution = RecordingContribution(type="person", id="PER123", role="narrator")
    assert contribution.to_upstream_payload() == {
        "type": "person",
        "id": "PER123",
        "role": "narrator",
    }


def test_person_contribution_to_upstream_payload_prefers_id_over_bdrc_id():
    contribution = RecordingContribution(
        type="person", id="PER123", bdrc_id="P123", role="narrator"
    )
    assert contribution.to_upstream_payload() == {
        "type": "person",
        "id": "PER123",
        "role": "narrator",
    }


def test_person_contribution_to_upstream_payload_falls_back_to_bdrc_id():
    contribution = RecordingContribution(type="person", bdrc_id="P123", role="narrator")
    assert contribution.to_upstream_payload() == {
        "type": "person",
        "bdrc_id": "P123",
        "role": "narrator",
    }


def test_ai_contribution_to_upstream_payload():
    contribution = RecordingContribution(type="ai", id="AI-1", role="narrator")
    assert contribution.to_upstream_payload() == {
        "type": "ai",
        "id": "AI-1",
        "role": "narrator",
    }


def test_ai_contribution_without_id_is_rejected():
    with pytest.raises(ValidationError):
        RecordingContribution(type="ai", role="narrator")


def test_contribution_from_upstream_round_trips():
    contribution = RecordingContribution.from_upstream(
        {"type": "person", "id": "PER123", "role": "narrator", "name": {"en": "Jane"}}
    )
    assert contribution.id == "PER123"
    assert contribution.name == {"en": "Jane"}


# ============================================================================
# PersonResponse
# ============================================================================

def test_person_response_from_upstream_maps_bdrc_field():
    result = PersonResponse.from_upstream(
        {"id": "P1", "name": {"en": "Jane"}, "bdrc": "P123", "wiki": "Q123"}
    )
    assert result.id == "P1"
    assert result.bdrc_id == "P123"
    assert result.wiki == "Q123"
    assert result.name == {"en": "Jane"}


def test_person_response_from_upstream_defaults_optional_fields():
    result = PersonResponse.from_upstream({"id": "P1", "name": {"en": "Jane"}})
    assert result.bdrc_id is None
    assert result.wiki is None
    assert result.alt_names is None


# ============================================================================
# RecordingResponse
# ============================================================================

def test_recording_response_from_upstream():
    result = RecordingResponse.from_upstream(RAW_RECORDING, audio_url="https://s3.example.com/signed")

    assert result.id == "REC1"
    assert result.edition_id == "ED123"
    assert result.text_id == "TXT1"
    assert result.format == AudioFormat.MP3
    assert result.license == LicenseType.CC0
    assert len(result.contributions) == 2
    assert result.contributions[0].role.value == "narrator"
    assert result.audio_url == "https://s3.example.com/signed"


def test_recording_response_defaults_license_when_absent():
    data = {key: value for key, value in RAW_RECORDING.items() if key != "license"}
    result = RecordingResponse.from_upstream(data, audio_url="https://s3.example.com/signed")
    assert result.license == LicenseType.PUBLIC


# ============================================================================
# RecordingCreateMetadata
# ============================================================================

def test_create_metadata_requires_at_least_one_contribution():
    with pytest.raises(ValidationError):
        RecordingCreateMetadata(contributions=[])


def test_create_metadata_to_upstream_json_serializes_enum_values():
    metadata = RecordingCreateMetadata(
        license=LicenseType.CC_BY,
        contributions=[RecordingContribution(type="person", id="PER1", role="narrator")],
    )
    payload = json.loads(metadata.to_upstream_json())

    assert payload["license"] == "cc-by"
    assert payload["contributions"] == [
        {"type": "person", "id": "PER1", "role": "narrator"}
    ]
    assert "title" not in payload
    assert "language" not in payload


# ============================================================================
# RecordingPatchRequest
# ============================================================================

def test_patch_request_only_forwards_fields_set_on_input():
    request = RecordingPatchRequest.model_validate({"duration_ms": 5000})
    assert request.to_upstream_payload() == {"duration_ms": 5000}


def test_patch_request_forwards_explicit_null_to_clear_a_field():
    request = RecordingPatchRequest.model_validate({"title": None})
    payload = request.to_upstream_payload()
    assert "title" in payload
    assert payload["title"] is None


def test_patch_request_with_no_fields_set_produces_empty_payload():
    request = RecordingPatchRequest()
    assert request.to_upstream_payload() == {}


def test_patch_request_serializes_contributions_and_license():
    request = RecordingPatchRequest.model_validate(
        {
            "license": "public",
            "contributions": [{"type": "person", "id": "PER1", "role": "narrator"}],
        }
    )
    payload = request.to_upstream_payload()
    assert payload["license"] == "public"
    assert payload["contributions"] == [
        {"type": "person", "id": "PER1", "role": "narrator"}
    ]
