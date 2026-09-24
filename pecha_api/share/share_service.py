from fastapi import HTTPException
import io
import re
from functools import partial
from typing import Optional
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from pecha_api.error_contants import ErrorConstants
from starlette.responses import StreamingResponse
from .pecha_text_image_generator import (
    ImageDestination,
    generate_event_share_image,
    generate_segment_image,
)
from pecha_api.texts.segments.segments_openpecha_service import get_openpecha_segment_details_by_id
from pecha_api.texts.texts_openpecha_service import get_text_by_id_from_openpecha
from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.poems.enums import PoemStatus
from pecha_api.poems.repository import get_poem_by_id
from pecha_api.events.event_repository import get_event_by_id
from pecha_api.group_posts.enums import GroupPostStatus
from pecha_api.group_posts.repository import get_post_by_id_only
import anyio
from anyio import to_thread

from pecha_api.share.share_response_models import (
    ShareRequest,
    ShortUrlResponse
)

from pecha_api.short_url.short_url_service import get_short_url

LOGO_PATH = "pecha_api/share/static/img/pecha-logo.png"
IMAGE_PATH = "pecha_api/share/static/img/output.png"
MEDIA_TYPE = "image/png"
# (title, description, language) as the share card needs it.
EventShareMetadata = tuple[str, Optional[str], Optional[str]]
DEFAULT_OG_TITLE = get("SITE_NAME")
DEFAULT_OG_DESCRIPTION = get("SITE_NAME")
PECHA_FRONTEND_ENDPOINT = "https://webuddhist.com/chapter"
_EMPTY_IDS = {"", "none", "null"}
_UUID_PATTERN = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_PATH_ID_PATTERNS = {
    "poem_id": re.compile(rf"/poems?/({_UUID_PATTERN})", re.IGNORECASE),
    "event_id": re.compile(rf"/events?/({_UUID_PATTERN})", re.IGNORECASE),
    "post_id": re.compile(rf"/posts?/({_UUID_PATTERN})", re.IGNORECASE),
}
_TYPE_TO_ID_FIELD = {
    "poem": "poem_id",
    "event": "event_id",
    "post": "post_id",
}
# Order matters: _primary_content_id resolves ties with this precedence.
_CONTENT_ID_FIELDS = ("poem_id", "event_id", "post_id", "segment_id", "text_id")


async def get_generated_image(share_request: Optional[ShareRequest] = None):
    if share_request is not None:
        _apply_inferred_ids(share_request)
        if _has_resolvable_content(share_request):
            image_bytes = await _render_share_image_bytes(share_request)
            return StreamingResponse(io.BytesIO(image_bytes), media_type=MEDIA_TYPE)

    try:
        image_path = IMAGE_PATH
        async with await anyio.open_file(image_path, "rb") as file:
            image_bytes = await file.read()

        return StreamingResponse(io.BytesIO(image_bytes), media_type=MEDIA_TYPE)

    except HTTPException as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=ErrorConstants.IMAGE_NOT_FOUND_MESSAGE
        )


async def generate_short_url(share_request: ShareRequest) -> ShortUrlResponse:
    _apply_inferred_ids(share_request)
    og_title = DEFAULT_OG_TITLE
    og_description = DEFAULT_OG_DESCRIPTION
    event_metadata: Optional[EventShareMetadata] = None
    if _normalized_id(share_request.event_id) is not None:
        event_metadata = await to_thread.run_sync(
            partial(
                _load_event_share_metadata,
                _normalized_id(share_request.event_id),
                share_request.language,
                get("SITE_NAME"),
            )
        )
        title, description, _language = event_metadata
        og_title = title
        if description:
            og_description = description
    if share_request.logo:
        await to_thread.run_sync(partial(_generate_logo_image_, share_request=share_request))

    # The card image needs the same event this just loaded. Handing it over
    # saves a second session and a second eager-loaded event query on a path
    # that runs for every share.
    await _generate_segment_content_image_(
        share_request=share_request,
        event_metadata=event_metadata,
    )

    payload = _generate_short_url_payload_(
        share_request=share_request,
        og_title=og_title,
        og_description=og_description,
    )
    short_url: ShortUrlResponse = await get_short_url(payload=payload)

    return short_url


def _generate_logo_image_(share_request: ShareRequest):
    generate_segment_image(
        text_color=share_request.text_color,
        bg_color=share_request.bg_color,
        logo_path=LOGO_PATH
    )


async def _generate_segment_content_image_(
    share_request: ShareRequest,
    output_path: Optional[ImageDestination] = None,
    event_metadata: Optional["EventShareMetadata"] = None,
):
    _, content_key = _primary_content_id(share_request)
    if content_key == "event_id":
        await _generate_event_content_image_(share_request, output_path, event_metadata)
        return

    main_content_text, reference_text, language = await _resolve_share_image_text(
        share_request
    )

    image_kwargs = {
        "text": main_content_text,
        "ref_str": reference_text,
        "lang": language,
        "text_color": share_request.text_color,
        "bg_color": share_request.bg_color,
        "logo_path": LOGO_PATH if share_request.logo else None,
    }
    if output_path is not None:
        image_kwargs["output_path"] = output_path
    # Pillow rendering is CPU-bound and blocks the event loop otherwise.
    await to_thread.run_sync(partial(generate_segment_image, **image_kwargs))


async def _resolve_share_image_text(
    share_request: ShareRequest,
) -> tuple[str, str, Optional[str]]:
    site_name = get("SITE_NAME")
    main_content_text = site_name
    reference_text = site_name
    language = share_request.language

    poem_id = _normalized_id(share_request.poem_id)
    post_id = _normalized_id(share_request.post_id)
    segment_id = _normalized_id(share_request.segment_id)
    text_id = _normalized_id(share_request.text_id)

    # The poem/post lookups use a synchronous session, so they run in a
    # worker thread rather than blocking the event loop for every OG request.
    if poem_id is not None:
        return await to_thread.run_sync(
            partial(_resolve_poem_share_text, poem_id, site_name)
        )
    if post_id is not None:
        return await to_thread.run_sync(
            partial(_resolve_post_share_text, post_id, site_name)
        )
    if segment_id is not None:
        segment_details = await get_openpecha_segment_details_by_id(
            segment_id=segment_id,
        )
        return (
            segment_details.content,
            segment_details.text.title,
            segment_details.text.language,
        )
    if text_id is not None:
        text_detail = await get_text_by_id_from_openpecha(text_id=text_id)
        return text_detail.title, site_name, text_detail.language

    return main_content_text, reference_text, language


def _resolve_poem_share_text(poem_id: str, site_name: str) -> tuple[str, str, Optional[str]]:
    poem_uuid = _parse_uuid(poem_id)
    if poem_uuid is None:
        return site_name, site_name, None

    with SessionLocal() as db:
        poem = get_poem_by_id(db=db, poem_id=poem_uuid, status=PoemStatus.PUBLISHED)
    if poem is None:
        return site_name, site_name, None

    main_text = poem.content or poem.title or site_name
    reference_text = poem.author_name or poem.title or site_name
    return main_text, reference_text, _language_code(poem.language)


async def _generate_event_content_image_(
    share_request: ShareRequest,
    output_path: Optional[ImageDestination] = None,
    event_metadata: Optional["EventShareMetadata"] = None,
) -> None:
    site_name = get("SITE_NAME")
    event_id = _normalized_id(share_request.event_id)
    # Already loaded when this render is part of building a short URL; loaded
    # here when the image endpoint is called on its own.
    if event_metadata is None:
        event_metadata = await to_thread.run_sync(
            partial(_load_event_share_metadata, event_id, share_request.language, site_name)
        )
    title, _description, language = event_metadata
    image_kwargs = {
        "title": title,
        "lang": language,
        "logo_path": LOGO_PATH,
    }
    if output_path is not None:
        image_kwargs["output_path"] = output_path
    await to_thread.run_sync(partial(generate_event_share_image, **image_kwargs))


def _load_event_share_metadata(
    event_id: Optional[str],
    language: Optional[str],
    site_name: str,
) -> EventShareMetadata:
    """The event name and description used on the short URL card.

    The image is the WeBuddhist logo plus this name - the event photo is not
    part of the share card.
    """
    event_uuid = _parse_uuid(event_id) if event_id else None
    if event_uuid is None:
        return site_name, None, language

    with SessionLocal() as db:
        event = get_event_by_id(db=db, event_id=event_uuid)
        if event is None:
            return site_name, None, language
        metadata = _first_metadata(event.metadata_entries, language)
        title = (metadata.name if metadata is not None and metadata.name else None) or site_name
        description = (
            metadata.description.strip()
            if metadata is not None and metadata.description
            else None
        ) or None
        resolved_language = (
            _language_code(metadata.language) if metadata is not None else None
        ) or language
    return title, description, resolved_language


def _resolve_post_share_text(post_id: str, site_name: str) -> tuple[str, str, Optional[str]]:
    post_uuid = _parse_uuid(post_id)
    if post_uuid is None:
        return site_name, site_name, None

    with SessionLocal() as db:
        post = get_post_by_id_only(
            db=db,
            post_id=post_uuid,
            status=GroupPostStatus.PUBLISHED,
        )
    if post is None:
        return site_name, site_name, None

    main_text = (post.caption or "").strip() or site_name
    return main_text, site_name, None


def _generate_short_url_payload_(
    share_request: ShareRequest,
    og_description: str,
    og_title: Optional[str] = None,
) -> dict:
    _apply_inferred_ids(share_request)

    if share_request.url is None:
        share_request.url = _generate_url_(
            segment_id=share_request.segment_id,
            content_id=share_request.content_id,
            text_id=share_request.text_id,
            content_index=share_request.content_index,
        )

    payload = {
        "url": share_request.url,
        "og_title": og_title or DEFAULT_OG_TITLE,
        "og_description": og_description,
        "og_image": _share_image_url(share_request),
        "tags": share_request.tags
    }
    return payload


def _share_image_url(share_request: ShareRequest) -> str:
    pecha_backend_endpoint = get("PECHA_BACKEND_ENDPOINT")
    content_id, content_key = _primary_content_id(share_request)
    language = share_request.language
    logo = share_request.logo
    if content_id is not None:
        return (
            f"{pecha_backend_endpoint}/share/image?"
            f"{content_key}={content_id}&language={language}&logo={logo}"
        )
    return f"{pecha_backend_endpoint}/share/image?language={language}&logo={logo}"


def _generate_url_(
        content_id: str,
        content_index: int,
        text_id: str,
        segment_id: str | None = None,
) -> str:
    if segment_id is None:
        return f"{PECHA_FRONTEND_ENDPOINT}?contentId={content_id}&text_id={text_id}&contentIndex={content_index}"
    return f"{PECHA_FRONTEND_ENDPOINT}?segment_id={segment_id}&contentId={content_id}&text_id={text_id}&contentIndex={content_index}"


async def _render_share_image_bytes(share_request: ShareRequest) -> bytes:
    # Rendered straight into memory: a temp file would put open/read/unlink
    # syscalls on the async request path and leak the file if the render
    # failed. The buffer is filled inside the render worker thread.
    buffer = io.BytesIO()
    await _generate_segment_content_image_(
        share_request=share_request,
        output_path=buffer,
    )
    return buffer.getvalue()


def _apply_inferred_ids(share_request: ShareRequest) -> None:
    """Fill the poem/event/post ids from the target URL, but only when the
    caller supplied no content identifier at all.

    Inferring alongside an explicit identifier mixes two sources of truth: a
    request carrying segment_id plus an event URL would gain an event_id, and
    the fixed precedence in _primary_content_id would then silently share the
    event instead of the requested segment. The caller's own identifier wins,
    and the URL is consulted only when there is nothing to conflict with.
    """
    if _primary_content_id(share_request)[0] is not None:
        return

    inferred = _ids_from_url(share_request.url)
    share_request.poem_id = inferred.get("poem_id")
    share_request.event_id = inferred.get("event_id")
    share_request.post_id = inferred.get("post_id")


def _ids_from_url(url: Optional[str]) -> dict[str, str]:
    if not url:
        return {}

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    inferred: dict[str, str] = {}

    for key in ("poem_id", "event_id", "post_id"):
        values = params.get(key) or params.get(key.removesuffix("_id"))
        value = _normalized_id(values[0] if values else None)
        if value:
            inferred[key] = value

    type_values = params.get("type")
    id_values = params.get("id")
    if type_values and id_values:
        field = _TYPE_TO_ID_FIELD.get(type_values[0].strip().lower())
        value = _normalized_id(id_values[0])
        if field and value:
            inferred.setdefault(field, value)

    for field, pattern in _PATH_ID_PATTERNS.items():
        match = pattern.search(parsed.path)
        if match:
            inferred.setdefault(field, match.group(1))

    return inferred


def _has_resolvable_content(share_request: ShareRequest) -> bool:
    return _primary_content_id(share_request)[0] is not None


def _primary_content_id(share_request: ShareRequest) -> tuple[Optional[str], Optional[str]]:
    for key in _CONTENT_ID_FIELDS:
        value = _normalized_id(getattr(share_request, key, None))
        if value is not None:
            return value, key
    return None, None


def _normalized_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if cleaned.lower() in _EMPTY_IDS:
        return None
    return cleaned


def _parse_uuid(value: str) -> Optional[UUID]:
    try:
        return UUID(value)
    except (TypeError, ValueError):
        return None


def _language_code(language) -> Optional[str]:
    if language is None:
        return None
    code = language.value if hasattr(language, "value") else str(language)
    return code.lower()


def _first_metadata(entries, language: Optional[str]):
    entries = list(entries or [])
    wanted = (language or "").upper()
    if wanted:
        for entry in entries:
            entry_lang = _language_code(entry.language) or ""
            if entry_lang.upper() == wanted:
                return entry
    return next(iter(entries), None)
