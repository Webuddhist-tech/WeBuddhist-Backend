from typing import Optional, Tuple
from urllib.parse import urlparse

from ..plans.videos.youtube_utils import extract_youtube_video_id
from .accumulator_enums import GroupAccumulatorLinkType


def is_valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def classify_link(url: str) -> Tuple[GroupAccumulatorLinkType, Optional[str]]:
    """YouTube resolves to YOUTUBE with its video id so the app can play it
    inline; everything else is a LINK the app opens externally."""
    video_id = extract_youtube_video_id(url)
    if video_id:
        return GroupAccumulatorLinkType.YOUTUBE, video_id
    return GroupAccumulatorLinkType.LINK, None
