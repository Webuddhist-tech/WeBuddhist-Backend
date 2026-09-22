from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from pecha_api.group_posts.enums import GroupPostReportReason

_MAX_DESCRIPTION = 1000


class ReportGroupPostRequest(BaseModel):
    """Report a post or a comment on it. `description` is free text the
    reporter adds, required in practice only for reason=OTHER."""

    reason: GroupPostReportReason
    description: Optional[str] = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > _MAX_DESCRIPTION:
            raise ValueError(
                f"Description must be at most {_MAX_DESCRIPTION} characters"
            )
        return value
