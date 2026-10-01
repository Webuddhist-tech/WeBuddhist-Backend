from enum import Enum


class RecurrenceFrequency(str, Enum):
    YEARLY = "YEARLY"
    MONTHLY = "MONTHLY"
    WEEKLY = "WEEKLY"


class RecurrenceDateSystem(str, Enum):
    GREGORIAN = "GREGORIAN"
    TIBETAN_LUNAR = "TIBETAN_LUNAR"


class EventLinkType(str, Enum):
    WEB = "web"
    GOOGLE_MEET = "google-meet"
    ZOOM = "zoom"
    VIDEO = "video"
    YOUTUBE = "youtube"


class ParticipationType(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
