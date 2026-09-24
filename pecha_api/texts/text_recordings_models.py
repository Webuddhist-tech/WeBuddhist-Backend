import json
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ContributorRole(str, Enum):
    TRANSLATOR = "translator"
    REVISER = "reviser"
    AUTHOR = "author"
    SCHOLAR = "scholar"
    NARRATOR = "narrator"


class LicenseType(str, Enum):
    CC0 = "cc0"
    PUBLIC = "public"
    CC_BY = "cc-by"
    CC_BY_SA = "cc-by-sa"
    CC_BY_ND = "cc-by-nd"
    CC_BY_NC = "cc-by-nc"
    CC_BY_NC_SA = "cc-by-nc-sa"
    CC_BY_NC_ND = "cc-by-nc-nd"
    COPYRIGHTED = "copyrighted"
    UNKNOWN = "unknown"


class AudioFormat(str, Enum):
    MP3 = "mp3"
    WAV = "wav"
    M4A = "m4a"
    OGG = "ogg"
    FLAC = "flac"


class RecordingContribution(BaseModel):
    type: Literal["person", "ai"]
    id: Optional[str] = None
    bdrc_id: Optional[str] = None
    role: ContributorRole
    # Set by OpenPecha on read for person contributions; never sent on write.
    name: Optional[Dict[str, str]] = None

    @model_validator(mode="after")
    def _validate_ai_has_id(self) -> "RecordingContribution":
        if self.type == "ai" and not self.id:
            raise ValueError("AI contributions require an id.")
        return self

    def to_upstream_payload(self) -> Dict[str, Any]:
        if self.type == "ai":
            return {"type": "ai", "id": self.id, "role": self.role.value}
        payload: Dict[str, Any] = {"type": "person", "role": self.role.value}
        # Upstream rejects person contributions carrying both fields, so a
        # person with a linked bdrc_id (e.g. from the persons directory)
        # still resolves to a single reference - prefer the internal id.
        if self.id:
            payload["id"] = self.id
        elif self.bdrc_id:
            payload["bdrc_id"] = self.bdrc_id
        return payload

    @classmethod
    def from_upstream(cls, data: Dict[str, Any]) -> "RecordingContribution":
        return cls(
            type=data["type"],
            id=data.get("id"),
            bdrc_id=data.get("bdrc_id"),
            role=data["role"],
            name=data.get("name"),
        )


class PersonResponse(BaseModel):
    id: str
    bdrc_id: Optional[str] = None
    wiki: Optional[str] = None
    name: Dict[str, str]
    alt_names: Optional[List[Dict[str, str]]] = None

    @classmethod
    def from_upstream(cls, data: Dict[str, Any]) -> "PersonResponse":
        return cls(
            id=data["id"],
            bdrc_id=data.get("bdrc"),
            wiki=data.get("wiki"),
            name=data.get("name") or {},
            alt_names=data.get("alt_names"),
        )


class RecordingResponse(BaseModel):
    id: str
    edition_id: str
    text_id: str
    title: Optional[Dict[str, str]] = None
    language: Optional[str] = None
    license: LicenseType = LicenseType.PUBLIC
    date: Optional[str] = None
    duration_ms: Optional[int] = None
    contributions: List[RecordingContribution] = Field(default_factory=list)
    format: AudioFormat
    size_bytes: int
    # A presigned, playable URL good for ~1hr - resolved server-side so
    # browser clients (which can't attach the CMS bearer token to an <audio>
    # tag) never need to hit an authenticated redirect endpoint themselves.
    audio_url: str

    @classmethod
    def from_upstream(cls, data: Dict[str, Any], audio_url: str) -> "RecordingResponse":
        return cls(
            id=data["id"],
            edition_id=data["edition_id"],
            text_id=data["text_id"],
            title=data.get("title"),
            language=data.get("language"),
            license=data.get("license", LicenseType.PUBLIC),
            date=data.get("date"),
            duration_ms=data.get("duration_ms"),
            contributions=[
                RecordingContribution.from_upstream(item)
                for item in data.get("contributions", [])
            ],
            format=data["format"],
            size_bytes=data["size_bytes"],
            audio_url=audio_url,
        )


class RecordingCreateMetadata(BaseModel):
    title: Optional[Dict[str, str]] = None
    language: Optional[str] = None
    license: Optional[LicenseType] = None
    date: Optional[str] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)
    contributions: List[RecordingContribution] = Field(min_length=1)

    def to_upstream_payload(self) -> Dict[str, Any]:
        payload = self.model_dump(
            mode="json", exclude_none=True, exclude={"contributions"}
        )
        payload["contributions"] = [
            contribution.to_upstream_payload() for contribution in self.contributions
        ]
        return payload

    def to_upstream_json(self) -> str:
        return json.dumps(self.to_upstream_payload())


class RecordingPatchRequest(BaseModel):
    title: Optional[Dict[str, str]] = None
    language: Optional[str] = None
    license: Optional[LicenseType] = None
    date: Optional[str] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)
    contributions: Optional[List[RecordingContribution]] = Field(
        default=None, min_length=1
    )

    def to_upstream_payload(self) -> Dict[str, Any]:
        """Only fields present in the incoming request are forwarded, so PATCH
        semantics (partial update) are preserved rather than resetting every
        omitted field to its default."""
        payload: Dict[str, Any] = {}
        for field in ("title", "language", "date", "duration_ms"):
            if field in self.model_fields_set:
                payload[field] = getattr(self, field)
        if "license" in self.model_fields_set:
            payload["license"] = self.license.value if self.license else None
        if "contributions" in self.model_fields_set:
            payload["contributions"] = (
                [c.to_upstream_payload() for c in self.contributions]
                if self.contributions is not None
                else None
            )
        return payload
