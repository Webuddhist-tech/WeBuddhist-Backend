import asyncio
import logging
from datetime import timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from pecha_api.bookmarks.bookmark_enums import BookmarkType
from pecha_api.bookmarks.bookmark_models import Bookmark
from pecha_api.bookmarks.bookmark_response_models import (
    BookmarkAccumulatorDTO,
    BookmarkGroupAccumulatorDTO,
    BookmarkGroupRecitationCollectionDTO,
    BookmarkRecitationCollectionDTO,
    BookmarkPlanDTO,
    BookmarkSegmentDTO,
    BookmarkSeriesDTO,
    BookmarkTextDTO,
    BookmarkTimerDTO,
    PlanBookmarkMetadataDTO,
)
from fastapi import HTTPException
from pecha_api.texts.texts_openpecha_service import (
    get_text_by_id_from_openpecha,
    get_text_versions_from_openpecha,
)
from pecha_api.texts.texts_openpecha_api import fetch_edition_text_id
from pecha_api.recitations.recitations_services import build_first_segment_for_edition
from pecha_api.plans.public.plan_repository import get_published_plan_by_id
from pecha_api.plans.plans_enums import PlanStatus
from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.authors.plan_authors_service import safe_get_image_url
from pecha_api.plans.shared.metadata_utils import filter_by_language_with_fallback
from pecha_api.plans.users.plan_user_series_day_sync_repository import (
    get_sibling_plans_in_series_slot,
)
from pecha_api.plans.series.series_repository import get_series_by_id
from pecha_api.plans.series.series_service import (
    _metadata_response,
    _series_schedule_from_plans,
    _to_plan_status,
    compute_series_progress,
)
from pecha_api.accumulator.accumulator_models import Accumulator
from pecha_api.accumulator.group_accumulator_models import GroupAccumulator
from pecha_api.accumulator.accumulator_service import (
    generate_mala_image_presigned_url,
    resolve_accumulator_bookmark_mala_image_url,
)
from pecha_api.texts.first_segment_preview_service import (
    build_first_segment_preview_for_text,
)
from pecha_api.mantra.mantra_repository import get_mantra_by_id
from pecha_api.plans.groups.groups_repository import (
    get_group_by_id,
    get_group_member,
    is_group_published,
)
from openpecha_api.segments.openpecha_segment_service import (
    fetch_related_segments,
    fetch_segment_content,
    fetch_segment_details,
)
from pecha_api.timers.timer_repository import get_timer_by_id
from pecha_api.ambient_sounds.ambient_sound_repository import get_ambient_sound_by_id
from pecha_api.group_recitation_collection.repository import (
    get_collection_item_counts,
    get_collection_without_group_filter,
)
from pecha_api.group_recitation_collection.service import (
    _generate_presigned_url as _generate_collection_image_url,
)
from pecha_api.plans.users.recitation_collection.recitation_collection_repository import (
    get_collection_by_id as get_recitation_collection_by_id,
    get_collection_item_counts as get_recitation_collection_item_counts,
)

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_LANGUAGE = "EN"
INVALID_BOOKMARK_TEXT_PLACEHOLDER = "Invalid data"


def _normalize_language(language: Optional[str]) -> Optional[str]:
    if not language:
        return None
    normalized = language.strip().upper()
    return normalized or None


def _plan_language_code(plan) -> str:
    return plan.language.value if hasattr(plan.language, "value") else str(plan.language)


def _accumulator_metadata_language(entry) -> str:
    return entry.language.value if hasattr(entry.language, "value") else str(entry.language)


def _mantra_metadata_language(entry) -> str:
    return entry.language.value if hasattr(entry.language, "value") else str(entry.language)


def _bookmark_image_url(
    image_key: Optional[str],
    *,
    resource_id: UUID,
    resource_type: str,
) -> Optional[str]:
    image = safe_get_image_url(
        image_key,
        resource_id=resource_id,
        resource_type=resource_type,
    )
    if not image:
        return None
    return image.medium or image.original


def _text_language_code(text) -> str:
    return text.language if isinstance(text.language, str) else str(text.language)


async def _try_get_openpecha_text(text_id: str):
    try:
        return await get_text_by_id_from_openpecha(text_id=text_id)
    except HTTPException:
        return None


async def _try_build_first_segment_preview(text_id: str):
    try:
        return await build_first_segment_preview_for_text(text_id)
    except Exception:
        # A preview is a nice-to-have decoration; don't let a lookup failure
        # (e.g. Mongo unavailable) 500 the whole bookmarks list.
        logger.warning("Failed to build first segment preview for text %s", text_id, exc_info=True)
        return None


async def _resolve_edition_text_id(edition_id: str) -> Optional[str]:
    """Chant/recitation bookmarks store an edition id as `source_id` (the
    recitations listing hands out edition ids in place of text ids). Plain
    text bookmarks store a real text id, which isn't a valid edition, so any
    failure here just means "not an edition" rather than a hard error.
    """
    try:
        return await fetch_edition_text_id(edition_id=edition_id)
    except Exception:
        return None


async def _try_build_first_segment_for_edition(edition_id: str):
    try:
        return await build_first_segment_for_edition(edition_id=edition_id)
    except Exception:
        logger.warning("Failed to build first segment for edition %s", edition_id, exc_info=True)
        return None


def _invalid_text_bookmark_segment(source_id: str) -> BookmarkSegmentDTO:
    return BookmarkSegmentDTO(id=source_id, content=INVALID_BOOKMARK_TEXT_PLACEHOLDER)


async def _fetch_openpecha_segment_content_safe(segment_id: str) -> Optional[str]:
    try:
        return await fetch_segment_content(segment_id)
    except Exception:
        logger.warning(
            "Failed to fetch segment content for bookmark segment %s from openpecha",
            segment_id,
            exc_info=True,
        )
        return None


async def _fetch_openpecha_segment_details_safe(segment_id: str) -> Optional[dict]:
    try:
        return await fetch_segment_details(segment_id)
    except Exception:
        logger.warning(
            "Failed to fetch segment details for bookmark segment %s from openpecha",
            segment_id,
            exc_info=True,
        )
        return None


async def _fetch_openpecha_segment(segment_id: str) -> Optional[dict]:
    """Resolve a bookmark's verse/segment id straight from openpecha -
    there's no local Mongo segments collection to fall back to any more.
    Returns {"id", "text_id", "content"}, or None if either call fails.
    """
    content, details = await asyncio.gather(
        _fetch_openpecha_segment_content_safe(segment_id),
        _fetch_openpecha_segment_details_safe(segment_id),
    )
    text_id = details.get("text_id") if details else None
    if content is None or not text_id:
        return None
    return {"id": segment_id, "text_id": text_id, "content": content}


async def _resolve_localized_openpecha_segment(
    segment_id: str,
    target_text_id: str,
) -> Optional[dict]:
    """Find the segment mapped into `target_text_id` for a source segment,
    via openpecha's related-segments lookup (replaces the old local Mongo
    segment-mapping table)."""
    try:
        related = await fetch_related_segments(
            segment_id=segment_id,
            limit=1,
            offset=0,
            text_id=target_text_id,
        )
    except Exception:
        logger.warning(
            "Failed to fetch related segments for %s in text %s from openpecha",
            segment_id,
            target_text_id,
            exc_info=True,
        )
        return None

    items = related.get("items") or [] if related else []
    if not items:
        return None
    mapped_id = items[0].get("id")
    if not mapped_id:
        return None

    content = await _fetch_openpecha_segment_content_safe(mapped_id)
    if content is None:
        return None
    return {"id": mapped_id, "text_id": target_text_id, "content": content}


async def _enrich_edition_text_bookmark(
    source_id: str,
    resolved_text_id: str,
    language: Optional[str],
) -> dict:
    lookup_text_id = resolved_text_id
    if language:
        text = await _resolve_localized_text(text_id=lookup_text_id, language=language)
        if not text:
            text = await _try_get_openpecha_text(text_id=lookup_text_id)
    else:
        text = await _try_get_openpecha_text(text_id=lookup_text_id)

    segment = await _try_build_first_segment_for_edition(source_id)

    return {
        "text": BookmarkTextDTO(
            # The id on the wire is always the edition id (`source_id`), matching
            # how chant/recitation listings expose editions as the text id.
            id=source_id,
            title=text.title if text else INVALID_BOOKMARK_TEXT_PLACEHOLDER,
            segment=(
                BookmarkSegmentDTO(id=segment.id, content=segment.content)
                if segment
                else _invalid_text_bookmark_segment(source_id)
            ),
        )
    }


async def enrich_text_bookmark(
    bookmark: Bookmark,
    language: Optional[str] = None,
) -> dict:
    verse_id: Optional[str] = None
    text_id: Optional[str] = None
    segment_id: Optional[str] = None
    segment_content: Optional[str] = None
    segment_source_text_id: Optional[str] = None
    use_first_segment_preview = False

    if bookmark.type == BookmarkType.VERSE:
        verse_id = bookmark.source_id
        resolved = await _fetch_openpecha_segment(verse_id)
        if not resolved:
            return {}
        text_id = resolved["text_id"]
        segment_id = resolved["id"]
        segment_content = resolved["content"]
        segment_source_text_id = resolved["text_id"]
    elif bookmark.type == BookmarkType.TEXT:
        text_id = bookmark.source_id
        if bookmark.name:
            candidate_details = await _fetch_openpecha_segment_details_safe(bookmark.name)
            if candidate_details and candidate_details.get("text_id") == text_id:
                verse_id = bookmark.name
        if verse_id:
            resolved = await _fetch_openpecha_segment(verse_id)
            if resolved:
                segment_id = resolved["id"]
                segment_content = resolved["content"]
                segment_source_text_id = resolved["text_id"]
            else:
                # The name was already confirmed to belong to this text
                # above; a transient failure re-fetching its content/details
                # shouldn't blank out the whole bookmark when a first-segment
                # preview of the same text is still available.
                use_first_segment_preview = True
        else:
            resolved_edition_text_id = await _resolve_edition_text_id(text_id)
            if resolved_edition_text_id is not None:
                return await _enrich_edition_text_bookmark(
                    source_id=text_id,
                    resolved_text_id=resolved_edition_text_id,
                    language=language,
                )
            use_first_segment_preview = True
    else:
        return {}

    if language:
        text = await _resolve_localized_text(text_id=text_id, language=language)
        if text:
            text_id = str(text.id)
        else:
            text = await _try_get_openpecha_text(text_id=text_id)
    else:
        text = await _try_get_openpecha_text(text_id=text_id)

    if (
        not use_first_segment_preview
        and language
        and segment_id
        and text_id != segment_source_text_id
    ):
        localized = await _resolve_localized_openpecha_segment(
            segment_id=segment_id,
            target_text_id=text_id,
        )
        if localized:
            segment_id = localized["id"]
            segment_content = localized["content"]

    segment_dto = None
    if use_first_segment_preview:
        preview = await _try_build_first_segment_preview(text_id)
        if not preview:
            return {}
        segment_id, preview_content = preview
        segment_dto = BookmarkSegmentDTO(
            id=segment_id,
            content=preview_content,
        )
    elif segment_id and segment_content is not None:
        segment_dto = BookmarkSegmentDTO(
            id=segment_id,
            content=segment_content,
        )

    return {
        "text": BookmarkTextDTO(
            id=text_id,
            title=text.title if text else "",
            segment=segment_dto,
        )
    }


async def _resolve_localized_text(text_id: str, language: Optional[str]):
    text = await _try_get_openpecha_text(text_id=text_id)
    if not text or not language:
        return text

    try:
        version_response = await get_text_versions_from_openpecha(text_id=text_id)
    except HTTPException:
        return text

    group_texts = [version_response.text] + list(version_response.versions or [])
    matched = filter_by_language_with_fallback(
        entries=group_texts,
        language=language,
        language_of=_text_language_code,
        fallback_language=DEFAULT_FALLBACK_LANGUAGE,
    )
    return matched[0] if matched else text


def _resolve_published_plan_for_language(
    db: Session,
    plan_id: UUID,
    language: Optional[str],
):
    plan = get_published_plan_by_id(db=db, plan_id=plan_id)
    if not plan or not language:
        return plan

    candidates = [plan]
    if plan.series_id is not None and plan.display_order is not None:
        siblings = get_sibling_plans_in_series_slot(
            db=db,
            series_id=plan.series_id,
            display_order=plan.display_order,
            exclude_plan_id=plan.id,
        )
        for sibling in siblings:
            published_sibling = get_published_plan_by_id(db=db, plan_id=sibling.id)
            if published_sibling:
                candidates.append(published_sibling)

    matched = filter_by_language_with_fallback(
        entries=candidates,
        language=language,
        language_of=_plan_language_code,
        fallback_language=DEFAULT_FALLBACK_LANGUAGE,
    )
    return matched[0] if matched else plan


def enrich_plan_bookmark(
    db: Session,
    source_id: str,
    language: Optional[str] = None,
) -> dict:
    plan_id = _parse_source_uuid(source_id)
    if plan_id is None:
        return {}

    plan = _resolve_published_plan_for_language(db=db, plan_id=plan_id, language=language)
    if not plan:
        return {}

    total_days = db.query(PlanItem).filter(PlanItem.plan_id == plan.id).count()
    end_date = None
    if plan.start_date and total_days > 0:
        end_date = plan.start_date + timedelta(days=total_days - 1)

    return {
        "plan": BookmarkPlanDTO(
            id=plan.id,
            metadata=PlanBookmarkMetadataDTO(
                title=plan.title,
                description=plan.description,
                language=_plan_language_code(plan),
            ),
            image=_bookmark_image_url(
                plan.image_url,
                resource_id=plan.id,
                resource_type="plan",
            ),
            start_date=plan.start_date,
            end_date=end_date,
        )
    }


def enrich_series_bookmark(
    db: Session,
    source_id: str,
    language: Optional[str] = None,
) -> dict:
    series_id = _parse_source_uuid(source_id)
    if series_id is None:
        return {}

    series = get_series_by_id(db=db, series_id=series_id)
    if not series or _to_plan_status(series.status) != PlanStatus.PUBLISHED:
        return {}

    start_date, end_date, total_days = _series_schedule_from_plans(
        series.plans,
        published_only=True,
        language=language,
        fallback=True,
    )
    metadata_entries = getattr(series, "metadata_entries", None) or []

    return {
        "series": BookmarkSeriesDTO(
            id=series.id,
            metadata=_metadata_response(
                metadata_entries,
                language=language,
                fallback=True,
            ),
            image=_bookmark_image_url(
                series.image,
                resource_id=series.id,
                resource_type="series",
            ),
            start_date=start_date,
            end_date=end_date,
            progress=compute_series_progress(start_date=start_date, total_days=total_days),
        )
    }


def _mantra_bookmark_title_image(mantra, language: Optional[str]) -> tuple[str, Optional[str]]:
    """Bookmark (title, image) derived from the linked mantra.

    Either field may be empty when the mantra is only partially populated
    (no default mala image, or no metadata title); callers should fall back
    to the accumulator's own values in that case.
    """
    image = (
        generate_mala_image_presigned_url(mantra.mala.url)
        if mantra.mala is not None
        else None
    )
    entries = list(mantra.metadata_entries)
    if language:
        entries = filter_by_language_with_fallback(
            entries=entries,
            language=language,
            language_of=_mantra_metadata_language,
            fallback_language=DEFAULT_FALLBACK_LANGUAGE,
        )
    title = entries[0].title if entries else ""
    return title or "", image


def _accumulator_bookmark_title(accumulator: Accumulator, language: Optional[str]) -> str:
    """Bookmark title derived from the accumulator's own metadata."""
    entries = list(accumulator.metadata_entries)
    if language:
        entries = filter_by_language_with_fallback(
            entries=entries,
            language=language,
            language_of=_accumulator_metadata_language,
            fallback_language=DEFAULT_FALLBACK_LANGUAGE,
        )
    return (entries[0].name if entries else "") or ""


def enrich_accumulator_bookmark(
    db: Session,
    source_id: str,
    language: Optional[str] = None,
) -> dict:
    accumulator_id = _parse_source_uuid(source_id)
    if accumulator_id is None:
        return {}

    accumulator = (
        db.query(Accumulator)
        .options(
            selectinload(Accumulator.metadata_entries),
            selectinload(Accumulator.mala),
        )
        .filter(
            Accumulator.id == accumulator_id,
            Accumulator.deleted_at.is_(None),
        )
        .first()
    )
    if not accumulator:
        return {}

    # Prefer the linked mantra's title/image. Fall back per-field to the
    # accumulator's own values only when the mantra is missing or lacks that
    # field (no default mala image, or no metadata title).
    mantra = (
        get_mantra_by_id(db, accumulator.mantra_id)
        if accumulator.mantra_id is not None
        else None
    )
    if mantra is not None:
        title, image = _mantra_bookmark_title_image(mantra, language)
    else:
        title, image = "", None

    if not title:
        title = _accumulator_bookmark_title(accumulator, language)
    if image is None:
        image = resolve_accumulator_bookmark_mala_image_url(db, accumulator)

    return {
        "accumulator": BookmarkAccumulatorDTO(
            id=accumulator.id,
            title=title,
            image=image,
        )
    }


def enrich_timer_bookmark(db: Session, source_id: str) -> dict:
    timer_id = _parse_source_uuid(source_id)
    if timer_id is None:
        return {}

    timer = get_timer_by_id(db=db, timer_id=timer_id)
    if not timer:
        return {}

    ambient_sound_name = None
    if timer.ambient_sound_id:
        ambient_sound = get_ambient_sound_by_id(db=db, ambient_sound_id=timer.ambient_sound_id)
        if ambient_sound:
            ambient_sound_name = ambient_sound.name

    return {
        "timer": BookmarkTimerDTO(
            id=timer.id,
            title=timer.name,
            duration=timer.duration,
            ambient_sound_name=ambient_sound_name,
            bell_at_start=timer.bell_at_start,
            bell_at_end=timer.bell_at_end,
        )
    }


def enrich_recitation_collection_bookmark(
    db: Session,
    source_id: str,
    user_id: UUID,
) -> dict:
    collection_id = _parse_source_uuid(source_id)
    if collection_id is None:
        return {}

    collection = get_recitation_collection_by_id(
        db=db,
        collection_id=collection_id,
        user_id=user_id,
    )
    if not collection:
        return {}

    item_counts = get_recitation_collection_item_counts(
        db=db,
        collection_ids=[collection.id],
    )
    return {
        "recitation_collection": BookmarkRecitationCollectionDTO(
            id=collection.id,
            title=collection.name,
            image=_generate_collection_image_url(collection.img_url),
            item_count=item_counts.get(collection.id, 0),
        )
    }


def enrich_group_recitation_collection_bookmark(
    db: Session,
    source_id: str,
    user_id: UUID,
) -> dict:
    collection_id = _parse_source_uuid(source_id)
    if collection_id is None:
        return {}

    collection = get_collection_without_group_filter(db=db, collection_id=collection_id)
    if not collection:
        return {}

    # Mirror the access rules of group-content reads: collections are visible
    # only when the group is public or the user is currently a member.
    group = get_group_by_id(db=db, group_id=collection.group_id)
    if not group or not is_group_published(group):
        return {}
    if not group.is_public and not get_group_member(
        db=db,
        group_id=collection.group_id,
        author_id=user_id,
    ):
        return {}

    item_counts = get_collection_item_counts(db=db, collection_ids=[collection.id])
    return {
        "group_recitation_collection": BookmarkGroupRecitationCollectionDTO(
            id=collection.id,
            group_id=collection.group_id,
            title=collection.name,
            image=_generate_collection_image_url(collection.img_url),
            item_count=item_counts.get(collection.id, 0),
        )
    }


def enrich_group_accumulator_bookmark(
    db: Session,
    source_id: str,
    user_id: UUID,
) -> dict:
    group_accumulator_id = _parse_source_uuid(source_id)
    if group_accumulator_id is None:
        return {}

    group_accumulator = (
        db.query(GroupAccumulator)
        .filter(
            GroupAccumulator.id == group_accumulator_id,
            GroupAccumulator.deleted_at.is_(None),
        )
        .first()
    )
    if not group_accumulator:
        return {}

    # Mirror the access rules of group-content reads: group accumulations are
    # visible only when the group is public or the user is currently a member.
    group = get_group_by_id(db=db, group_id=group_accumulator.group_id)
    if not group or not is_group_published(group):
        return {}
    if not group.is_public and not get_group_member(
        db=db,
        group_id=group_accumulator.group_id,
        author_id=user_id,
    ):
        return {}

    return {
        "group_accumulator": BookmarkGroupAccumulatorDTO(
            id=group_accumulator.id,
            group_id=group_accumulator.group_id,
            title=group_accumulator.title or "",
            image=_generate_collection_image_url(group_accumulator.image_key),
        )
    }


def _parse_source_uuid(source_id: str) -> Optional[UUID]:
    try:
        return UUID(source_id)
    except ValueError:
        return None


async def enrich_bookmark(
    bookmark: Bookmark,
    db: Session,
    language: Optional[str] = None,
) -> dict:
    normalized_language = _normalize_language(language)
    if bookmark.type in (BookmarkType.TEXT, BookmarkType.VERSE):
        return await enrich_text_bookmark(bookmark, language=normalized_language)
    if bookmark.type == BookmarkType.PLAN:
        return enrich_plan_bookmark(
            db=db,
            source_id=bookmark.source_id,
            language=normalized_language,
        )
    if bookmark.type == BookmarkType.SERIES:
        return enrich_series_bookmark(
            db=db,
            source_id=bookmark.source_id,
            language=normalized_language,
        )
    if bookmark.type == BookmarkType.ACCUMULATOR:
        return enrich_accumulator_bookmark(
            db=db,
            source_id=bookmark.source_id,
            language=normalized_language,
        )
    if bookmark.type == BookmarkType.GROUP_ACCUMULATOR:
        return enrich_group_accumulator_bookmark(
            db=db,
            source_id=bookmark.source_id,
            user_id=bookmark.user_id,
        )
    if bookmark.type == BookmarkType.TIMER:
        return enrich_timer_bookmark(db=db, source_id=bookmark.source_id)
    if bookmark.type == BookmarkType.RECITATION_COLLECTION:
        return enrich_recitation_collection_bookmark(
            db=db,
            source_id=bookmark.source_id,
            user_id=bookmark.user_id,
        )
    if bookmark.type == BookmarkType.GROUP_RECITATION_COLLECTION:
        return enrich_group_recitation_collection_bookmark(
            db=db,
            source_id=bookmark.source_id,
            user_id=bookmark.user_id,
        )
    return {}
