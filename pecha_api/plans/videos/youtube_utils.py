import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Set
from urllib.parse import parse_qs, urlparse

import httpx

from pecha_api import config

logger = logging.getLogger(__name__)

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

_ISO8601_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)
_YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_MAX_VIDEO_IDS_PER_REQUEST = 50
_REQUEST_TIMEOUT_SECONDS = 10.0
_FAILED_LOOKUP_TTL = timedelta(minutes=15)
_failed_lookup_until: Dict[str, datetime] = {}


def extract_youtube_video_id(url: str) -> Optional[str]:
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    if host not in _YOUTUBE_HOSTS:
        return None
    if host in ("youtu.be", "www.youtu.be"):
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path.startswith(("/embed/", "/shorts/", "/v/")):
        candidate = parsed.path.split("/")[2]
    else:
        candidate = parse_qs(parsed.query).get("v", [None])[0]
    if candidate and re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    return None


def parse_iso8601_duration(iso: Optional[str]) -> Optional[int]:
    """Convert a YouTube contentDetails.duration value to whole seconds.

    Live or unparseable values (including P0D / zero) return None.
    """
    if not iso:
        return None
    match = _ISO8601_DURATION.fullmatch(iso.strip())
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    total = int(days * 86400 + hours * 3600 + minutes * 60 + seconds)
    return total if total > 0 else None


def _lookup_backoff_active(video_id: str, *, now: datetime) -> bool:
    until = _failed_lookup_until.get(video_id)
    return until is not None and until > now


def _mark_failed_lookups(video_ids: Sequence[str], *, now: datetime) -> None:
    retry_after = now + _FAILED_LOOKUP_TTL
    for video_id in video_ids:
        if video_id:
            _failed_lookup_until[video_id] = retry_after


def _clear_failed_lookups(video_ids: Iterable[str]) -> None:
    for video_id in video_ids:
        if video_id:
            _failed_lookup_until.pop(video_id, None)


def fetch_youtube_durations(video_ids: Sequence[str]) -> Dict[str, int]:
    """Look up video lengths via YouTube Data API v3 `videos.list`.

    Missing API key, HTTP errors, and empty items are swallowed so callers
    can still save or return the link without a duration.
    """
    api_key = (config.get("YOUTUBE_API_KEY") or "").strip()
    unique_ids = list(dict.fromkeys(video_id for video_id in video_ids if video_id))
    if not api_key or not unique_ids:
        return {}

    now = datetime.now(timezone.utc)
    lookup_ids = [video_id for video_id in unique_ids if not _lookup_backoff_active(video_id, now=now)]
    if not lookup_ids:
        return {}

    durations: Dict[str, int] = {}
    for offset in range(0, len(lookup_ids), _MAX_VIDEO_IDS_PER_REQUEST):
        batch = lookup_ids[offset : offset + _MAX_VIDEO_IDS_PER_REQUEST]
        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                response = client.get(
                    _YOUTUBE_VIDEOS_URL,
                    params={
                        "part": "contentDetails",
                        "id": ",".join(batch),
                        "key": api_key,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as error:
            logger.warning(
                "YouTube duration lookup failed for ids %s status=%s",
                batch,
                error.response.status_code,
            )
            _mark_failed_lookups(batch, now=now)
            continue
        except httpx.HTTPError as error:
            logger.warning(
                "YouTube duration lookup failed for ids %s error=%s",
                batch,
                type(error).__name__,
            )
            _mark_failed_lookups(batch, now=now)
            continue
        except Exception as error:
            logger.warning(
                "YouTube duration lookup failed for ids %s error=%s",
                batch,
                type(error).__name__,
            )
            _mark_failed_lookups(batch, now=now)
            continue

        batch_found: Set[str] = set()
        for item in payload.get("items") or []:
            video_id = item.get("id")
            iso_duration = (item.get("contentDetails") or {}).get("duration")
            seconds = parse_iso8601_duration(iso_duration)
            if video_id and seconds is not None:
                durations[video_id] = seconds
                batch_found.add(video_id)
        unresolved = [video_id for video_id in batch if video_id not in batch_found]
        if unresolved:
            _mark_failed_lookups(unresolved, now=now)
        if batch_found:
            _clear_failed_lookups(batch_found)
    return durations


def lookup_youtube_duration_seconds(video_id: Optional[str]) -> Optional[int]:
    if not video_id:
        return None
    return fetch_youtube_durations([video_id]).get(video_id)


def durations_for_video_ids(video_ids: Iterable[str]) -> Dict[str, int]:
    try:
        return fetch_youtube_durations(list(video_ids))
    except Exception as error:
        logger.warning("YouTube duration lookup failed error=%s", type(error).__name__)
        return {}
