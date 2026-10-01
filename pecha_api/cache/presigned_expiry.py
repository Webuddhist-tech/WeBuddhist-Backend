"""When a cached payload's presigned URLs stop working.

A response is cached with its image URLs already signed inside it, and a
signature expires on AWS's clock rather than Redis's. Cache an entry for
longer than the URLs it carries and the tail of that entry's life serves
links that are already dead - which is exactly what happened with one-hour
signatures sitting in namespaces cached for three and a half.

Rather than asking every caller to keep its timeout in step with whatever
`ExpiresIn` the signer used, the payload is read for the answer: a SigV4 URL
states its own signing time and lifetime, so the entry can be held for as
long as its shortest-lived signature lasts and no longer.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, urlsplit

logger = logging.getLogger(__name__)

# Cheap test that decides whether a payload is worth scanning at all. Most
# cached bodies - texts, segments, calendars - carry no signed URLs, and they
# should not pay for a regex sweep to establish it.
SIGNED_URL_MARKER = "X-Amz-"

_URL_PATTERN = re.compile(r"https?://[^\s\"'\<>]+")
_AMZ_DATE_FORMAT = "%Y%m%dT%H%M%SZ"


def _expiry_of(url: str) -> Optional[datetime]:
    """When this URL's signature lapses, or None if it carries no deadline."""
    query = parse_qs(urlsplit(url).query)

    # SigV4: signing time plus a lifetime in seconds.
    signed_at = query.get("X-Amz-Date", [None])[0]
    lifetime = query.get("X-Amz-Expires", [None])[0]
    if signed_at and lifetime:
        try:
            issued = datetime.strptime(signed_at, _AMZ_DATE_FORMAT).replace(
                tzinfo=timezone.utc
            )
            return issued + timedelta(seconds=int(lifetime))
        except (TypeError, ValueError):
            logger.warning("Unparseable presigned URL deadline; ignoring it")
            return None

    # SigV2, and pre-signed CloudFront: an absolute epoch second.
    absolute = query.get("Expires", [None])[0]
    if absolute:
        try:
            return datetime.fromtimestamp(int(absolute), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            logger.warning("Unparseable presigned URL deadline; ignoring it")
    return None


def seconds_until_first_expiry(payload: str, now: Optional[datetime] = None) -> Optional[int]:
    """Seconds until the earliest-expiring signed URL in `payload` lapses.

    None when the payload holds no signed URL, which is the common case and
    means the caller's own timeout stands unaltered. A payload whose earliest
    signature has already lapsed returns 0, not a negative number.
    """
    if not payload or SIGNED_URL_MARKER not in payload:
        return None

    deadlines = [
        deadline
        for deadline in (_expiry_of(url) for url in _URL_PATTERN.findall(payload))
        if deadline is not None
    ]
    if not deadlines:
        return None

    reference = now or datetime.now(timezone.utc)
    return max(0, int((min(deadlines) - reference).total_seconds()))
