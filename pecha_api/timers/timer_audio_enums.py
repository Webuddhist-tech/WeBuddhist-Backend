import enum
from sqlalchemy import Enum


class TimerAudioType(enum.Enum):
    """PRESET is curated in Studio and listed to everyone. USER is uploaded by
    someone for themselves and listed only back to them."""
    PRESET = "preset"
    USER = "user_uploaded"


# values_callable so PostgreSQL stores the values ("preset", "user_uploaded")
# rather than the member names, matching TimerTypeEnum.
TimerAudioTypeEnum = Enum(
    TimerAudioType,
    name="timeraudiotype",
    values_callable=lambda x: [e.value for e in x]
)
