from pydantic import BaseModel, model_validator
from typing import Optional
from pecha_api.plans.plans_enums import ContentType, is_reference_content_type
from pecha_api.plans.shared.subtask_reference_resolver import SubTaskReferenceDTO
from typing import List
from uuid import UUID


CONTENT_REQUIRED = "content is required for this content type"


class SubTaskRequestFields(BaseModel):
    content_type: str
    # Optional only for reference content types (GROUP_ACCUMULATION,
    # GROUP_COLLECTION, EVENT, POST), which carry no inline content - the
    # linked entity is the content. Inline types still require it.
    content: Optional[str] = None
    duration: Optional[str] = None
    # Target of a reference content type (GROUP_ACCUMULATION, GROUP_COLLECTION,
    # EVENT, POST); must belong to the plan's group.
    reference_id: Optional[UUID] = None
    source_text_id: Optional[str] = None
    pecha_segment_id: Optional[str] = None
    segment_ids: Optional[List[str]] = None
    segment_numbers: Optional[List[int]] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None

    @model_validator(mode="after")
    def _require_content_for_inline_types(self):
        if self.content is None and not is_reference_content_type(self.content_type):
            raise ValueError(CONTENT_REQUIRED)
        return self


class SubTaskRequest(BaseModel):
    task_id: UUID
    sub_tasks: List[SubTaskRequestFields]


class SubTaskDTO(BaseModel):
    id: Optional[UUID]
    content_type: ContentType
    content: Optional[str] = None
    duration: Optional[str] = None
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    source_text_id: Optional[str] = None
    pecha_segment_id: Optional[str] = None
    segment_ids: Optional[List[str]] = None
    segment_numbers: Optional[List[int]] = None
    segment_refs: Optional[List[Optional[str]]] = None
    reference_id: Optional[UUID] = None
    reference: Optional[SubTaskReferenceDTO] = None
    display_order: int
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None

class SubTaskResponse(BaseModel):
    sub_tasks: List[SubTaskDTO]


class UpdateSubTaskRequest(BaseModel):
    task_id: UUID
    sub_tasks: List[SubTaskDTO]

class UpdateSubTaskResponse(BaseModel):
    sub_task_id: UUID

class SubtaskOrderItem(BaseModel):
    id: UUID
    display_order: int    

class SubTaskOrderRequest(BaseModel):
    subtasks: List[SubtaskOrderItem]

class UpdatedSubtaskOrderItem(BaseModel):
    sub_task_id: UUID
    display_order: int

class SubTaskOrderResponse(BaseModel):
    updated_subtasks: List[UpdatedSubtaskOrderItem]
