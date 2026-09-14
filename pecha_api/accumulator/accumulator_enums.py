import enum
from sqlalchemy import Enum


class AccumulatorType(enum.Enum):
    PRESET = "preset"
    USER = "user_created"


AccumulatorTypeEnum = Enum(
    AccumulatorType,
    name="accumulatortype",
    values_callable=lambda x: [e.value for e in x]
)


class GroupAccumulatorLinkType(enum.Enum):
    """Only YOUTUBE plays inline in the app; LINK opens externally."""
    YOUTUBE = "YOUTUBE"
    LINK = "LINK"


GroupAccumulatorLinkTypeEnum = Enum(
    GroupAccumulatorLinkType,
    name="group_accumulator_link_type",
    values_callable=lambda x: [e.value for e in x]
)
