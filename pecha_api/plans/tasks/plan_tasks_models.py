from sqlalchemy import Column, Integer, DateTime, Boolean, Text, ForeignKey, Index, UUID,String, text
from sqlalchemy.orm import relationship
from uuid import uuid4
from ...db.database import Base
from _datetime import datetime
import _datetime


class PlanTask(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_item_id = Column(UUID(as_uuid=True), ForeignKey('items.id', ondelete='CASCADE'), nullable=False)

    title = Column(Text, nullable=True)

    display_order = Column(Integer, nullable=False)
    estimated_time = Column(Integer, nullable=True)  # minutes
    is_required = Column(Boolean, default=True)

    # Reader defaults for the task. A panel can be open with no text chosen:
    # the reader then shows the list of commentaries/translations to pick from.
    # The ids are OpenPecha text ids.
    is_commentary_open = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    commentary_text_id = Column(String(255), nullable=True)
    is_translation_open = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    translation_text_id = Column(String(255), nullable=True)
    # At most one live task per day; see uq_tasks_one_live_per_day.
    is_live = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc),nullable=False)
    created_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255))

    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(String(255))

    plan_item = relationship("PlanItem", backref="tasks")
    sub_tasks = relationship("PlanSubTask", back_populates="task", cascade="all, delete-orphan")
    user_task_completions = relationship("UserTaskCompletion", back_populates="task", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        Index("idx_tasks_plan_item_order", "plan_item_id", "display_order"),
        Index(
            "uq_tasks_one_live_per_day",
            "plan_item_id",
            unique=True,
            postgresql_where=text("is_live AND deleted_at IS NULL"),
            sqlite_where=text("is_live AND deleted_at IS NULL"),
        ),
    )