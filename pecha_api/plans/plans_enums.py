import enum
from sqlalchemy import Enum

class DifficultyLevel(enum.Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"

class ContentType(enum.Enum):
    TEXT = "TEXT"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    IMAGE = "IMAGE"
    SOURCE_REFERENCE = "SOURCE_REFERENCE"
    # Content types that point at another piece of WeBuddhist content instead
    # of carrying the content themselves. Each stores the target's id in
    # PlanSubTask.reference_id and is resolved for display at read time.
    GROUP_ACCUMULATION = "GROUP_ACCUMULATION"
    GROUP_COLLECTION = "GROUP_COLLECTION"
    EVENT = "EVENT"
    POST = "POST"


# Content types whose payload is a reference to another entity (reference_id)
# rather than inline content.
REFERENCE_CONTENT_TYPES = frozenset(
    {
        ContentType.GROUP_ACCUMULATION,
        ContentType.GROUP_COLLECTION,
        ContentType.EVENT,
        ContentType.POST,
    }
)


def is_reference_content_type(content_type) -> bool:
    """True when the content type links to other content instead of carrying it.

    Accepts a ContentType or its string name; an unrecognised value is not a
    reference type, so it stays subject to the inline content requirement.
    """
    if isinstance(content_type, ContentType):
        return content_type in REFERENCE_CONTENT_TYPES
    try:
        return ContentType(content_type) in REFERENCE_CONTENT_TYPES
    except ValueError:
        return False

class UserPlanStatus(enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"

class PlanStatus(enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    UNPUBLISHED = "UNPUBLISHED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"

class LanguageCode(enum.Enum):
    EN = "EN"
    BO = "BO"
    ZH = "ZH"
    HI = "HI"
    NE = "NE"
    MN = "MN"
    LA = "LA"

class SortOrder(enum.Enum):
    ASC = "asc"
    DESC = "desc"

class SortBy(enum.Enum):
    TOTAL_DAYS = "total_days"
    STATUS = "status"
    CREATED_AT = "created_at"

class EnrollmentSource(enum.Enum):
    DIRECT = "DIRECT"
    SERIES = "SERIES"

class SeriesStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class PlanAudioType(enum.Enum):
    RECITATION = "RECITATION"
    INSTRUCTION = "INSTRUCTION"
    TEXT_READING = "TEXT_READING"


class MonlamVoiceName(str, enum.Enum):
    # Lhasa
    DOLKAR_LHASA_FEMALE = "dolkar_lhasa_female"
    YANGCHEN_LHASA_FEMALE = "yangchen_lhasa_female"
    DARJEEYALPHEL_LHASA_MALE = "darjeeyalphel_lhasa_male"
    HISTRY_LHASA_MALE = "histry_lhasa_male"
    SONAMTSERING_LHASA_MALE = "sonamtsering_lhasa_male"
    # Amdo
    DOLMA_AMDO_FEMALE = "dolma_amdo_female"
    KID_AMDO_FEMALE = "kid_amdo_female"
    BUDDHAHISTORY_AMDO_MALE = "buddhahistory_amdo_male"
    HISTORY_AMDO_MALE = "history_amdo_male"
    KALSANG_GYATSO_AMDO_MALE = "kalsang_gyatso_amdo_male"
    # Kham
    KOTHEKE_KHAM_MALE = "kotheke_kham_male"
    TIBET_TONGUE_KHAM_MALE = "tibet_tongue_kham_male"
    TSERING_WANGMO_KHAM_FEMALE = "tsering_wangmo_kham_female"
    WANGDONTSO_KHAM_FEMALE = "wangdontso_kham_female"


class AudioJobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# SQLAlchemy enum types
DifficultyLevelEnum = Enum(DifficultyLevel)
ContentTypeEnum = Enum(ContentType)
UserPlanStatusEnum = Enum(UserPlanStatus)
PlanStatusEnum = Enum(PlanStatus)
LanguageCodeEnum = Enum(LanguageCode)
EnrollmentSourceEnum = Enum(EnrollmentSource)
SeriesStatusEnum = Enum(SeriesStatus)
PlanAudioTypeEnum = Enum(PlanAudioType)


