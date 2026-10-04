from pydantic import BaseModel, Field
from pecha_api.plans.tasks.task_settings_models import TaskSettingsDTO
from typing import Optional
from uuid import UUID
from typing import List
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_response_model import SubTaskDTO


# Request/Response Models
class CreateTaskRequest(BaseModel):
    plan_id: UUID
    day_id: UUID
    title: str
    description: Optional[str] = None
    estimated_time: Optional[int] = None

class TaskDTO(BaseModel):
    id: UUID
    title: str
    display_order: int
    estimated_time: Optional[int] = None
    settings: TaskSettingsDTO = Field(default_factory=TaskSettingsDTO)

class UpdatedTaskDayResponse(BaseModel):
    task_id: UUID
    title: str
    day_id: UUID
    display_order: int
    estimated_time: Optional[int] = None
    settings: TaskSettingsDTO = Field(default_factory=TaskSettingsDTO)

class UpdateTaskDayRequest(BaseModel):
    target_day_id: UUID

class UpdateTaskTitleRequest(BaseModel):
    title: Optional[str] = None

class UpdateTaskTitleResponse(BaseModel):
    task_id: UUID
    title: Optional[str] = None

class TaskOrderItem(BaseModel):
    id: UUID
    display_order: int

class UpdateTaskOrderRequest(BaseModel):
    tasks: List[TaskOrderItem]
    
class UpdatedTaskOrderResponse(BaseModel):
    updated_tasks: List[TaskOrderItem]
    
class GetTaskRequest(BaseModel):
    task_id: UUID

class GetTaskResponse(BaseModel):
    id: UUID
    title: str
    display_order: int
    estimated_time: Optional[int] = None
    subtasks: List[SubTaskDTO]
    settings: TaskSettingsDTO = Field(default_factory=TaskSettingsDTO)

class ContentAndImageUrl(BaseModel):
    content: str
    image_url: Optional[str] = None