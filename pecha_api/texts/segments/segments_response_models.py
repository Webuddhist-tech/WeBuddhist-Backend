from pydantic import BaseModel, Field
from typing import List, Optional

from sqlalchemy.orm import strategies

from .segments_enum import SegmentType
from pecha_api.texts.texts_response_models import TextDTO
from pecha_api.plans.videos.plan_video_response_models import PlanVideoDTO


class Mapping(BaseModel):
    text_id: str
    segments: List[str]


class CreateSegment(BaseModel):
    pecha_segment_id: Optional[str] = None
    content: str
    pecha_segment_id: Optional[str] = None
    type: SegmentType
    mapping: Optional[List[Mapping]] = []


class CreateSegmentRequest(BaseModel):
    text_id: str
    segments: List[CreateSegment]


class MappingResponse(BaseModel):
    text_id: str
    segments: List[str]

class SegmentDTO(BaseModel):
    id: str
    pecha_segment_id: Optional[str] = None
    text_id: str
    content: str
    type: SegmentType
    mapping: Optional[List[MappingResponse]] = None
    text: Optional[TextDTO] = None

class SegmentUpdate(BaseModel):
    pecha_segment_id: str
    content: str

class SegmentUpdateRequest(BaseModel):
    pecha_text_id: str
    segments: List[SegmentUpdate]
    
class MappedSegmentDTO(BaseModel):
    segment_id: str
    content: str

class SegmentResponse(BaseModel):
    segments: List[SegmentDTO]


class SegmentSearchRequest(BaseModel):
    content: str = Field(..., min_length=1)

class ParentSegment(BaseModel):
    segment_id: str
    content: str

# segment translation models
class SegmentTranslation(BaseModel):
    segment_id: str
    text_id: str
    title: str
    source: str
    language: str
    content: str
    source_link: Optional[str] = None
    license: Optional[str] = None

class SegmentRecitation(BaseModel):
    segment_id: str
    text_id: str
    title: str
    source: str
    language: str
    content: str

class SegmentTransliteration(BaseModel):
    segment_id: str
    text_id: str
    title: str
    source: str
    language: str
    content: str

class SegmentAdaptation(BaseModel):
    segment_id: str
    text_id: str
    title: str
    source: str
    language: str
    content: str

class SegmentTranslationsResponse(BaseModel):
    parent_segment: ParentSegment
    translations: List[SegmentTranslation]

# segment commentary models
class SegmentCommentry(BaseModel):
    text_id: str
    title: str
    segments: List[MappedSegmentDTO]
    language: str
    count: int
    source_link: Optional[str] = None
    license: Optional[str] = None

class SegmentCommentariesResponse(BaseModel):
    parent_segment: ParentSegment
    commentaries: List[SegmentCommentry]

# segment info models

class SegmentInfosRequest(BaseModel):
    text_id: str

class RelatedText(BaseModel):
    commentaries: Optional[int] = 0
    root_text: Optional[int] = 0

class Resources(BaseModel):
    sheets: int

class SegmentInfo(BaseModel):
    segment_id: str
    text_id: str
    translations: Optional[int] = 0
    related_text: RelatedText
    resources: Resources
    videos: List[PlanVideoDTO] = Field(default_factory=list)

class SegmentInfoResponse(BaseModel):
    segment_info: SegmentInfo

# segment's root mapping models

class MappedSegmentResponseDTO(BaseModel):
    segment_id: str
    content: str

class SegmentRootMapping(BaseModel):
    text_id: str
    title: str
    language: str
    segments: List[MappedSegmentResponseDTO]

class SegmentRootMappingResponse(BaseModel):
    parent_segment: ParentSegment
    segment_root_mapping: List[SegmentRootMapping]


class V2RelatedSegmentItem(BaseModel):
    id: str
    content: Optional[str] = None


class V2SegmentTextGroup(BaseModel):
    text_id: str
    title: str
    language: Optional[str] = None
    source_link: Optional[str] = None
    license: Optional[str] = None
    segments: List[V2RelatedSegmentItem]


class V2SegmentTranslationsResponse(BaseModel):
    parent_segment: ParentSegment
    translations: List[V2SegmentTextGroup]
    skip: int
    limit: int
    has_more: bool = False


class V2SegmentRootTextResponse(BaseModel):
    parent_segment: ParentSegment
    root_text: List[V2SegmentTextGroup]
    skip: int
    limit: int
    has_more: bool = False


class V2SegmentCommentariesResponse(BaseModel):
    parent_segment: ParentSegment
    commentaries: List[V2SegmentTextGroup]
    skip: int
    limit: int
    has_more: bool = False


class V2SegmentTextDetail(BaseModel):
    text_id: str
    title: str
    language: Optional[str] = None


class V2SegmentResponse(BaseModel):
    segment_id: str
    content: str
    text: Optional[V2SegmentTextDetail] = None


class SegmentRelatedText(BaseModel):
    commentaries: int
    root_text: int


class SegmentResources(BaseModel):
    sheets: int


class V2SegmentInfo(BaseModel):
    segment_id: str
    text_id: str
    translations: int
    related_text: SegmentRelatedText
    resources: SegmentResources


class V2SegmentInfoResponse(BaseModel):
    segment_info: V2SegmentInfo
