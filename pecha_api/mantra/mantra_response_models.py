from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from uuid import UUID

from ..plans.plans_enums import LanguageCode
from ..plans.media.media_response_models import ImageUrlModel


def _validate_unique_languages(metadata: List["MantraMetadataInput"]) -> List["MantraMetadataInput"]:
    languages = [entry.language.value for entry in metadata]
    if len(languages) != len(set(languages)):
        raise ValueError("Duplicate languages in metadata are not allowed")
    return metadata


class MantraMetadataInput(BaseModel):
    mantra: str
    title: Optional[str] = None
    pronunciation: Optional[str] = None
    language: LanguageCode

    @field_validator("mantra")
    @classmethod
    def validate_mantra_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("mantra text must not be empty")
        return value.strip()


class CreateMantraRequest(BaseModel):
    audio_url: Optional[str] = None
    mala_image_id: Optional[UUID] = None
    deity_image_key: Optional[str] = None
    metadata: List[MantraMetadataInput]

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: List[MantraMetadataInput]) -> List[MantraMetadataInput]:
        if not value:
            raise ValueError("At least one metadata entry is required")
        return _validate_unique_languages(value)


class UpdateMantraRequest(BaseModel):
    deity_image_key: Optional[str] = Field(..., description="S3 key of the deity image's 'original' size, or null to clear it")


class MantraMetadataDTO(BaseModel):
    id: UUID
    mantra: str
    title: Optional[str] = None
    pronunciation: Optional[str] = None
    language: LanguageCode

    class Config:
        from_attributes = True


class MantraDTO(BaseModel):
    id: UUID
    audio_url: Optional[str] = None
    mala_image_id: Optional[UUID] = None
    mala_image_url: Optional[str] = None
    deity_image: Optional[ImageUrlModel] = None
    metadata: List[MantraMetadataDTO] = []

    class Config:
        from_attributes = True


class CMSMantraDTO(MantraDTO):
    """CMS-facing variant of MantraDTO that also round-trips the raw S3 key
    so an edit form can re-submit it via PATCH without re-uploading."""
    deity_image_key: Optional[str] = None


class MantraResponse(BaseModel):
    mantras: List[MantraDTO]
