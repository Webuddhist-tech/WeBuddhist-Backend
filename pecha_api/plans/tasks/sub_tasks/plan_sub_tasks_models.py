from sqlalchemy import Column, Integer, DateTime, Boolean, Text, ForeignKey, Index, UUID, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship
from uuid import uuid4
from pecha_api.db.database import Base
from pecha_api.plans.plans_enums import ContentTypeEnum
from _datetime import datetime
import _datetime


class PlanSubTask(Base):
    __tablename__ = "sub_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False)
    audio_url = Column(String(255), nullable=True)
    content_type = Column(ContentTypeEnum, nullable=False)
    content = Column(Text, nullable=True)
    duration=Column(String(255), nullable=True)
    # Not UUID-only: can hold an external (pecha-style) text id too, not just
    # an internal Text UUID.
    source_text_id = Column(String(255), nullable=True)
    pecha_segment_id = Column(String(255), nullable=True)
    # Not UUID-only: can hold external (pecha-style) segment ids too, not just
    # internal Segment UUIDs.
    segment_ids = Column(ARRAY(String(255)), nullable=True)
    segment_numbers = Column(ARRAY(Integer), nullable=True)
    # Target of a reference content type (GROUP_ACCUMULATION, GROUP_COLLECTION,
    # EVENT, POST). The content_type says which table the id belongs to; no FK
    # because the target table varies.
    reference_id = Column(UUID(as_uuid=True), nullable=True)

    display_order = Column(Integer, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)
    created_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255))

    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(String(255))

    # Relationships
    task = relationship("PlanTask", back_populates="sub_tasks")
    user_sub_task_completions = relationship("UserSubTaskCompletion", back_populates="sub_task", cascade="all, delete-orphan", passive_deletes=True)
    timestamp = relationship(
        "SubTaskTimestamp",
        back_populates="sub_task",
        uselist=False,
        cascade="all, delete-orphan",
    )
    preset = relationship(
        "SubTaskPreset",
        back_populates="sub_task",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_sub_tasks_task_order", "task_id", "display_order"),
        Index("idx_sub_tasks_content_type", "content_type"),
        Index("idx_sub_tasks_reference_id", "reference_id"),
    )


from pecha_api.plans.audio.sub_task_timestamps_models import SubTaskTimestamp  # noqa: F401, E402
from pecha_api.plans.tasks.sub_tasks.subtask_preset_models import SubTaskPreset  # noqa: F401, E402
