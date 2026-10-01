from pydantic import BaseModel, Field
from pecha_api.plans.tasks.task_settings_models import TaskSettingsDTO
from uuid import UUID
from typing import Optional
from pecha_api.plans.plans_enums import ContentType
from typing import List


class SubTaskDTO(BaseModel):
    id: UUID
    content_type: ContentType
    content: Optional[str] = None
    duration: Optional[str] = None
    display_order: Optional[int] = None

class TaskDTO(BaseModel):
    id: UUID
    title: Optional[str] = None 
    estimated_time: Optional[int] = None
    display_order: Optional[int] = None
    subtasks: List[SubTaskDTO] = []
    settings: TaskSettingsDTO = Field(default_factory=TaskSettingsDTO)

class PlanDayDTO(BaseModel):
    id: UUID
    day_number: int
    tasks: List[TaskDTO]