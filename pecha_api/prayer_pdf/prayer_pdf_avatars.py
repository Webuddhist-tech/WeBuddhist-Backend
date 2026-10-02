"""Profile photos for the prayer PDF, read from users.avatar_url.

The column holds either an S3 key (an uploaded photo) or the identity
provider's https URL (Auth0's `picture`). Each photo is fetched once, checked
for being a real photo rather than a generated placeholder, shrunk, and
handed back as a data: URI so Chromium never goes to the network.

A missing, unreachable or placeholder photo returns None and the card shows
the coloured initials circle instead, as the GitHub action did."""

import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, Optional, Tuple

import httpx
from PIL import Image

from pecha_api.config import get
from pecha_api.uploads.S3_utils import download_bytes, generate_presigned_access_url
from pecha_api.utils import Utils

logger = logging.getLogger(__name__)

MAX_AVATAR_BYTES = 5 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 10
_WORKERS = 8
# Printed at 9.5mm; 160px is ~430dpi there, plenty for print.
_OUTPUT_PX = 160


def is_placeholder_url(url: str) -> bool:
    """Auth0's default avatar (initials on a colour) is not a photo."""
    lowered = url.lower()
    return "cdn.auth0.com/avatars" in lowered or ("gravatar.com" in lowered and "cdn.auth0.com" in lowered)


def is_generated_avatar(image: Image.Image, *, is_png: bool) -> bool:
    """Google's letter avatars come from the same hosts as real photos and
    only differ in their pixels: a flat block of colour with one glyph.

    Two checks, as in the action: under 400 colours with one covering over
    80% (fetch_avatars.py), or, for a PNG at 64x64, two colours covering 70%
    or more (build_prayer_pdf.py)."""
    rgb = image.convert("RGB")
    colours = rgb.getcolors(maxcolors=100_000)
    if colours and len(colours) < 400 and max(count for count, _ in colours) / (rgb.width * rgb.height) > 0.80:
        return True
    if not is_png:
        return False
    small = rgb.resize((64, 64))
    top = sorted(small.getcolors(4096) or [], reverse=True)
    return bool(top) and sum(count for count, _ in top[:2]) / 4096 >= 0.7


def _fetch_bytes(reference: str) -> Optional[bytes]:
    if reference.startswith(("https://", "http://")):
        if is_placeholder_url(reference) or not Utils.is_social_picture_url(reference):
            return None
        with (
            httpx.Client(timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client,
            client.stream("GET", reference) as response,
        ):
            if response.status_code != 200:
                return None
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_AVATAR_BYTES:
                    return None
            return body
    return download_bytes(bucket_name=get("AWS_BUCKET_NAME"), s3_key=reference.lstrip("/"), max_bytes=MAX_AVATAR_BYTES)


def _to_data_uri(data: bytes) -> Optional[str]:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if is_generated_avatar(image, is_png=image.format == "PNG"):
            return None
        rgb = image.convert("RGB")
        side = min(rgb.size)
        left, top = (rgb.width - side) // 2, (rgb.height - side) // 2
        square = rgb.crop((left, top, left + side, top + side)).resize((_OUTPUT_PX, _OUTPUT_PX), Image.LANCZOS)
        out = io.BytesIO()
        square.save(out, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def load_avatar(reference: Optional[str]) -> Optional[str]:
    if not reference or not reference.strip():
        return None
    try:
        data = _fetch_bytes(reference.strip())
        return _to_data_uri(data) if data else None
    except Exception:  # one bad photo must not cost the whole PDF
        logger.info("Prayer PDF: no usable avatar at %s", reference[:80], exc_info=True)
        return None


def load_avatars(references: Iterable[Tuple[str, Optional[str]]]) -> Dict[str, Optional[str]]:
    """{user id: data URI or None} for (user id, avatar_url) pairs, fetched in parallel."""
    unique = dict(references)
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(unique))) as pool:
        results = pool.map(load_avatar, unique.values())
        return dict(zip(unique.keys(), results))


def preview_avatar_url(reference: Optional[str]) -> Optional[str]:
    """A URL the Studio's browser can load the photo from, for the live
    preview: a signed S3 link, or the identity provider's own URL. Nothing is
    downloaded, so this is quick enough to run on every keystroke."""
    if not reference or not reference.strip():
        return None
    reference = reference.strip()
    if reference.startswith(("https://", "http://")):
        if is_placeholder_url(reference) or not Utils.is_social_picture_url(reference):
            return None
        return reference
    try:
        return generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key=reference.lstrip("/")) or None
    except Exception:  # an unsignable photo just shows initials
        return None
