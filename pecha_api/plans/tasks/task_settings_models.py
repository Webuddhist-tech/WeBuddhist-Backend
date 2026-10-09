from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class TaskSettingsDTO(BaseModel):
    """How the reader opens a task by default.

    A panel can be open with no text id: the reader then shows the list of
    commentaries/translations without opening one. The ids are OpenPecha text
    ids, which is what the reader's panels are keyed by.
    """

    is_commentary_open: bool = False
    commentary_text_id: Optional[str] = None
    is_translation_open: bool = False
    translation_text_id: Optional[str] = None
    is_live: bool = False


class UpdateTaskSettingsRequest(BaseModel):
    is_commentary_open: bool = False
    commentary_text_id: Optional[str] = Field(default=None, max_length=255)
    is_translation_open: bool = False
    translation_text_id: Optional[str] = Field(default=None, max_length=255)
    is_live: bool = False

    @field_validator("commentary_text_id", "translation_text_id", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


def _flag(value: Any) -> bool:
    # A task that has not been flushed yet has None here, not the column default.
    return value is True


def _text_id(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def build_task_settings(task: Any) -> TaskSettingsDTO:
    return TaskSettingsDTO(
        is_commentary_open=_flag(getattr(task, "is_commentary_open", False)),
        commentary_text_id=_text_id(getattr(task, "commentary_text_id", None)),
        is_translation_open=_flag(getattr(task, "is_translation_open", False)),
        translation_text_id=_text_id(getattr(task, "translation_text_id", None)),
        is_live=_flag(getattr(task, "is_live", False)),
    )
