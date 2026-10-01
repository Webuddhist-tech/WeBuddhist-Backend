from typing import Optional

import pytest
from fastapi import HTTPException
from starlette import status
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from pecha_api.bookmarks.bookmark_enums import BookmarkType
from pecha_api.texts.first_segment_preview_service import resolve_segment_by_ref
from pecha_api.bookmarks.bookmark_utils import (
    enrich_text_bookmark,
)


@pytest.mark.asyncio
async def test_resolve_segment_by_ref_with_uuid():
    segment_id = str(uuid4())
    mock_segment = MagicMock()

    with patch(
        "pecha_api.texts.first_segment_preview_service.Segment.get_segment_by_id",
        new_callable=AsyncMock,
        return_value=mock_segment,
    ):
        result = await resolve_segment_by_ref(segment_id)

    assert result is mock_segment


@pytest.mark.asyncio
async def test_resolve_segment_by_ref_with_pecha_id_when_uuid_lookup_fails():
    mock_segment = MagicMock()

    with patch(
        "pecha_api.texts.first_segment_preview_service.Segment.get_segment_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.texts.first_segment_preview_service.Segment.get_segment_by_pecha_segment_id",
        new_callable=AsyncMock,
        return_value=mock_segment,
    ) as mock_pecha_lookup:
        result = await resolve_segment_by_ref(str(uuid4()))

    mock_pecha_lookup.assert_awaited_once()
    assert result is mock_segment


@pytest.mark.asyncio
async def test_resolve_segment_by_ref_with_non_uuid_uses_pecha_lookup():
    verse_locator = "segment-ref-abc-123"
    mock_segment = MagicMock()

    with patch(
        "pecha_api.texts.first_segment_preview_service.Segment.get_segment_by_pecha_segment_id",
        new_callable=AsyncMock,
        return_value=mock_segment,
    ) as mock_pecha_lookup:
        result = await resolve_segment_by_ref(verse_locator)

    mock_pecha_lookup.assert_awaited_once_with(pecha_segment_id=verse_locator)
    assert result is mock_segment


@pytest.mark.asyncio
async def test_fetch_openpecha_segment_returns_none_when_content_missing():
    from pecha_api.bookmarks.bookmark_utils import _fetch_openpecha_segment

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_details",
        new_callable=AsyncMock,
        return_value={"text_id": str(uuid4())},
    ):
        result = await _fetch_openpecha_segment("missing-ref")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_openpecha_segment_returns_none_when_text_id_missing():
    from pecha_api.bookmarks.bookmark_utils import _fetch_openpecha_segment

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value="content",
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_details",
        new_callable=AsyncMock,
        return_value={},
    ):
        result = await _fetch_openpecha_segment("some-ref")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_openpecha_segment_returns_data_on_success():
    from pecha_api.bookmarks.bookmark_utils import _fetch_openpecha_segment

    text_id = str(uuid4())

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value="content",
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_details",
        new_callable=AsyncMock,
        return_value={"text_id": text_id},
    ):
        result = await _fetch_openpecha_segment("some-ref")

    assert result == {"id": "some-ref", "text_id": text_id, "content": "content"}


@pytest.mark.asyncio
async def test_resolve_localized_openpecha_segment_returns_mapped_segment():
    from pecha_api.bookmarks.bookmark_utils import _resolve_localized_openpecha_segment

    segment_id = str(uuid4())
    target_text_id = str(uuid4())
    mapped_id = str(uuid4())

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_related_segments",
        new_callable=AsyncMock,
        return_value={"items": [{"id": mapped_id, "text_id": target_text_id}]},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value="Localized content",
    ):
        result = await _resolve_localized_openpecha_segment(
            segment_id=segment_id,
            target_text_id=target_text_id,
        )

    assert result == {
        "id": mapped_id,
        "text_id": target_text_id,
        "content": "Localized content",
    }


@pytest.mark.asyncio
async def test_resolve_localized_openpecha_segment_returns_none_when_no_match():
    from pecha_api.bookmarks.bookmark_utils import _resolve_localized_openpecha_segment

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_related_segments",
        new_callable=AsyncMock,
        return_value={"items": []},
    ):
        result = await _resolve_localized_openpecha_segment(
            segment_id=str(uuid4()),
            target_text_id=str(uuid4()),
        )

    assert result is None


@pytest.mark.asyncio
async def test_resolve_localized_openpecha_segment_returns_none_when_item_has_no_id():
    from pecha_api.bookmarks.bookmark_utils import _resolve_localized_openpecha_segment

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_related_segments",
        new_callable=AsyncMock,
        return_value={"items": [{"text_id": str(uuid4())}]},
    ):
        result = await _resolve_localized_openpecha_segment(
            segment_id=str(uuid4()),
            target_text_id=str(uuid4()),
        )

    assert result is None


@pytest.mark.asyncio
async def test_resolve_localized_openpecha_segment_returns_none_when_content_fetch_fails():
    from pecha_api.bookmarks.bookmark_utils import _resolve_localized_openpecha_segment

    mapped_id = str(uuid4())

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_related_segments",
        new_callable=AsyncMock,
        return_value={"items": [{"id": mapped_id}]},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _resolve_localized_openpecha_segment(
            segment_id=str(uuid4()),
            target_text_id=str(uuid4()),
        )

    assert result is None


@pytest.mark.asyncio
async def test_resolve_localized_openpecha_segment_returns_none_on_upstream_error():
    from pecha_api.bookmarks.bookmark_utils import _resolve_localized_openpecha_segment

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_related_segments",
        new_callable=AsyncMock,
        side_effect=RuntimeError("upstream unavailable"),
    ):
        result = await _resolve_localized_openpecha_segment(
            segment_id=str(uuid4()),
            target_text_id=str(uuid4()),
        )

    assert result is None


@pytest.mark.asyncio
async def test_fetch_openpecha_segment_content_safe_returns_none_on_error():
    from pecha_api.bookmarks.bookmark_utils import _fetch_openpecha_segment_content_safe

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        side_effect=RuntimeError("upstream unavailable"),
    ):
        result = await _fetch_openpecha_segment_content_safe("some-ref")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_openpecha_segment_details_safe_returns_none_on_error():
    from pecha_api.bookmarks.bookmark_utils import _fetch_openpecha_segment_details_safe

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_details",
        new_callable=AsyncMock,
        side_effect=RuntimeError("upstream unavailable"),
    ):
        result = await _fetch_openpecha_segment_details_safe("some-ref")

    assert result is None


@pytest.mark.asyncio
async def test_enrich_verse_bookmark_uses_localized_segment_when_language_differs():
    """When a language is requested and it resolves to a different text than
    the verse's own text, enrichment should swap in the segment mapped into
    that target text (via _resolve_localized_openpecha_segment) rather than
    keeping the original-language content."""
    source_text_id = str(uuid4())
    localized_text_id = str(uuid4())
    verse_locator = "segment-ref-abc-123"
    localized_segment_id = str(uuid4())

    bookmark = MagicMock()
    bookmark.type = BookmarkType.VERSE
    bookmark.source_id = verse_locator
    bookmark.name = None

    localized_text = MagicMock()
    localized_text.id = localized_text_id
    localized_text.title = "Localized title"

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value="Original content",
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_details",
        new_callable=AsyncMock,
        return_value={"text_id": source_text_id},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_localized_text",
        new_callable=AsyncMock,
        return_value=localized_text,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_localized_openpecha_segment",
        new_callable=AsyncMock,
        return_value={
            "id": localized_segment_id,
            "text_id": localized_text_id,
            "content": "Localized content",
        },
    ) as mock_resolve_localized:
        result = await enrich_text_bookmark(bookmark, language="BO")

    mock_resolve_localized.assert_awaited_once_with(
        segment_id=verse_locator,
        target_text_id=localized_text_id,
    )
    assert result["text"].id == localized_text_id
    assert result["text"].title == "Localized title"
    assert result["text"].segment.id == localized_segment_id
    assert result["text"].segment.content == "Localized content"


@pytest.mark.asyncio
async def test_enrich_text_bookmark_without_verse_uses_first_segment():
    text_id = str(uuid4())
    segment_id = str(uuid4())

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = text_id
    bookmark.name = None

    mock_text = MagicMock()
    mock_text.title = "Heart Sutra"

    mock_segment = MagicMock()
    mock_segment.id = segment_id
    mock_segment.text_id = text_id
    mock_segment.content = "Segment content"

    with patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_edition_text_id",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.build_first_segment_preview_for_text",
        new_callable=AsyncMock,
        return_value=(segment_id, "Segment content"),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ):
        result = await enrich_text_bookmark(bookmark)

    assert result["text"].id == text_id
    assert result["text"].title == "Heart Sutra"
    assert result["text"].segment.id == segment_id
    assert result["text"].segment.content == "Segment content"


@pytest.mark.asyncio
async def test_enrich_text_bookmark_with_name_as_segment_ref():
    text_id = str(uuid4())
    verse_locator = "segment-ref-abc-123"

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = text_id
    bookmark.name = verse_locator

    mock_text = MagicMock()
    mock_text.title = "Heart Sutra"

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_details",
        new_callable=AsyncMock,
        return_value={"text_id": text_id},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value="Named segment content",
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ):
        result = await enrich_text_bookmark(bookmark)

    assert result["text"].segment.id == verse_locator
    assert result["text"].segment.content == "Named segment content"


@pytest.mark.asyncio
async def test_enrich_text_bookmark_with_name_falls_back_to_first_segment_when_refetch_fails():
    """The name was already confirmed to belong to text_id via
    _fetch_openpecha_segment_details_safe; a transient failure re-fetching
    its content/details shouldn't blank out the whole bookmark when a
    first-segment preview is still available."""
    text_id = str(uuid4())
    segment_id = str(uuid4())
    verse_locator = "segment-ref-abc-123"

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = text_id
    bookmark.name = verse_locator

    mock_text = MagicMock()
    mock_text.title = "Heart Sutra"

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_details",
        new_callable=AsyncMock,
        return_value={"text_id": text_id},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.build_first_segment_preview_for_text",
        new_callable=AsyncMock,
        return_value=(segment_id, "Fallback preview content"),
    ):
        result = await enrich_text_bookmark(bookmark)

    assert result["text"].id == text_id
    assert result["text"].title == "Heart Sutra"
    assert result["text"].segment.id == segment_id
    assert result["text"].segment.content == "Fallback preview content"


@pytest.mark.asyncio
async def test_enrich_text_bookmark_returns_empty_when_segment_missing():
    text_id = str(uuid4())

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = text_id
    bookmark.name = None

    with patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_edition_text_id",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=MagicMock(title="Unused"),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.build_first_segment_preview_for_text",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await enrich_text_bookmark(bookmark)

    assert result == {}


@pytest.mark.asyncio
async def test_enrich_verse_bookmark_includes_segment_content():
    text_id = str(uuid4())
    verse_locator = "segment-ref-abc-123"

    bookmark = MagicMock()
    bookmark.type = BookmarkType.VERSE
    bookmark.source_id = verse_locator
    bookmark.name = None

    mock_text = MagicMock()
    mock_text.title = "Lotus Sutra"

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value="Verse segment content",
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_details",
        new_callable=AsyncMock,
        return_value={"text_id": text_id},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ):
        result = await enrich_text_bookmark(bookmark)

    assert result["text"].id == text_id
    assert result["text"].title == "Lotus Sutra"
    assert result["text"].segment.id == verse_locator
    assert result["text"].segment.content == "Verse segment content"


@pytest.mark.asyncio
async def test_enrich_verse_bookmark_returns_empty_when_segment_not_found():
    bookmark = MagicMock()
    bookmark.type = BookmarkType.VERSE
    bookmark.source_id = "missing-ref"
    bookmark.name = None

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_segment_content",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await enrich_text_bookmark(bookmark)

    assert result == {}


@pytest.mark.asyncio
async def test_enrich_unsupported_bookmark_type_returns_empty():
    bookmark = MagicMock()
    bookmark.type = BookmarkType.PLAN
    bookmark.source_id = str(uuid4())

    result = await enrich_text_bookmark(bookmark)

    assert result == {}


@pytest.mark.asyncio
async def test_enrich_text_bookmark_handles_missing_text_details():
    text_id = str(uuid4())
    segment_id = str(uuid4())

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = text_id
    bookmark.name = None

    with patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_edition_text_id",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found."),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.build_first_segment_preview_for_text",
        new_callable=AsyncMock,
        return_value=(segment_id, "Segment content"),
    ):
        result = await enrich_text_bookmark(bookmark)

    assert result["text"].id == text_id
    assert result["text"].title == ""
    assert result["text"].segment.content == "Segment content"


@pytest.mark.asyncio
async def test_enrich_text_bookmark_with_language_uses_localized_text():
    text_id = str(uuid4())
    localized_text_id = str(uuid4())
    segment_id = str(uuid4())

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = text_id
    bookmark.name = None

    localized_text = MagicMock()
    localized_text.id = localized_text_id
    localized_text.title = "བོད་ཡིག་ཁ་བྱང་"

    with patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_edition_text_id",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_localized_text",
        new_callable=AsyncMock,
        return_value=localized_text,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.build_first_segment_preview_for_text",
        new_callable=AsyncMock,
        return_value=(segment_id, "English content"),
    ) as mock_preview:
        result = await enrich_text_bookmark(bookmark, language="BO")

    mock_preview.assert_awaited_once_with(localized_text_id)
    assert result["text"].id == localized_text_id
    assert result["text"].title == "བོད་ཡིག་ཁ་བྱང་"


@pytest.mark.asyncio
async def test_enrich_text_bookmark_resolves_chant_source_id_as_edition():
    edition_id = str(uuid4())
    resolved_text_id = str(uuid4())
    segment_id = str(uuid4())

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = edition_id
    bookmark.name = None

    mock_text = MagicMock()
    mock_text.title = "Heart Sutra Chant"

    mock_segment = MagicMock()
    mock_segment.id = segment_id
    mock_segment.content = "Om mani padme hum"

    with patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_edition_text_id",
        new_callable=AsyncMock,
        return_value=resolved_text_id,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ) as mock_get_text, patch(
        "pecha_api.bookmarks.bookmark_utils.build_first_segment_for_edition",
        new_callable=AsyncMock,
        return_value=mock_segment,
    ) as mock_build_segment:
        result = await enrich_text_bookmark(bookmark)

    mock_get_text.assert_awaited_once_with(text_id=resolved_text_id)
    mock_build_segment.assert_awaited_once_with(edition_id=edition_id)
    assert result["text"].id == edition_id
    assert result["text"].title == "Heart Sutra Chant"
    assert result["text"].segment.id == segment_id
    assert result["text"].segment.content == "Om mani padme hum"


@pytest.mark.asyncio
async def test_enrich_text_bookmark_edition_source_returns_invalid_data_when_lookups_fail():
    edition_id = str(uuid4())
    resolved_text_id = str(uuid4())

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = edition_id
    bookmark.name = None

    with patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_edition_text_id",
        new_callable=AsyncMock,
        return_value=resolved_text_id,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found."),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.build_first_segment_for_edition",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await enrich_text_bookmark(bookmark)

    assert result["text"].id == edition_id
    assert result["text"].title == "Invalid data"
    assert result["text"].segment.content == "Invalid data"


@pytest.mark.asyncio
async def test_resolve_edition_text_id_returns_none_for_plain_text_id():
    from pecha_api.bookmarks.bookmark_utils import _resolve_edition_text_id

    text_id = str(uuid4())

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_edition_text_id",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Edition not found."),
    ):
        result = await _resolve_edition_text_id(text_id)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_edition_text_id_returns_text_id_for_edition():
    from pecha_api.bookmarks.bookmark_utils import _resolve_edition_text_id

    edition_id = str(uuid4())
    resolved_text_id = str(uuid4())

    with patch(
        "pecha_api.bookmarks.bookmark_utils.fetch_edition_text_id",
        new_callable=AsyncMock,
        return_value=resolved_text_id,
    ):
        result = await _resolve_edition_text_id(edition_id)

    assert result == resolved_text_id


def test_enrich_plan_bookmark_with_language_uses_matching_sibling():
    from pecha_api.bookmarks.bookmark_utils import enrich_plan_bookmark

    source_plan_id = uuid4()
    bo_plan_id = uuid4()
    mock_db = MagicMock()

    source_plan = MagicMock()
    source_plan.id = source_plan_id
    source_plan.series_id = uuid4()
    source_plan.display_order = 1
    source_plan.language = MagicMock(value="EN")

    bo_plan = MagicMock()
    bo_plan.id = bo_plan_id
    bo_plan.title = "བོད་ཡིག་ཐེངས་"
    bo_plan.description = "བོད་ཡིག་ཞབས་ཞུ་"
    bo_plan.language = MagicMock(value="BO")
    bo_plan.difficulty_level = None
    bo_plan.image_url = None
    bo_plan.author = None
    bo_plan.start_date = None
    bo_plan.display_order = 1
    bo_plan.tag_list = []

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_published_plan_by_id",
        side_effect=lambda db, plan_id: source_plan if plan_id == source_plan_id else bo_plan,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_sibling_plans_in_series_slot",
        return_value=[bo_plan],
    ):
        mock_db.query.return_value.filter.return_value.count.return_value = 3
        result = enrich_plan_bookmark(
            db=mock_db,
            source_id=str(source_plan_id),
            language="BO",
        )

    assert result["plan"].id == bo_plan_id
    assert result["plan"].metadata.title == "བོད་ཡིག་ཐེངས་"
    assert result["plan"].metadata.language == "BO"


def test_enrich_plan_bookmark_returns_empty_for_invalid_source_id():
    from pecha_api.bookmarks.bookmark_utils import enrich_plan_bookmark

    result = enrich_plan_bookmark(db=MagicMock(), source_id="not-a-uuid")

    assert result == {}


def test_enrich_plan_bookmark_returns_empty_when_plan_not_found():
    from pecha_api.bookmarks.bookmark_utils import enrich_plan_bookmark

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_published_plan_by_id",
        return_value=None,
    ):
        result = enrich_plan_bookmark(
            db=MagicMock(),
            source_id=str(uuid4()),
        )

    assert result == {}


def test_enrich_plan_bookmark_includes_dates_and_image():
    from datetime import datetime, timedelta, timezone
    from pecha_api.bookmarks.bookmark_utils import enrich_plan_bookmark

    plan_id = uuid4()
    mock_db = MagicMock()
    start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

    mock_plan = MagicMock()
    mock_plan.id = plan_id
    mock_plan.title = "Morning Practice"
    mock_plan.description = "Daily practice"
    mock_plan.language = "EN"
    mock_plan.image_url = "plans/original/plan.png"
    mock_plan.start_date = start_date

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_published_plan_by_id",
        return_value=mock_plan,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._bookmark_image_url",
        return_value="https://example.com/plan.png",
    ):
        mock_db.query.return_value.filter.return_value.count.return_value = 7
        result = enrich_plan_bookmark(db=mock_db, source_id=str(plan_id))

    assert result["plan"].id == plan_id
    assert result["plan"].metadata.title == "Morning Practice"
    assert result["plan"].image == "https://example.com/plan.png"
    assert result["plan"].start_date == start_date
    assert result["plan"].end_date == start_date + timedelta(days=6)


def test_enrich_series_bookmark_success():
    from datetime import datetime, timezone
    from pecha_api.bookmarks.bookmark_utils import enrich_series_bookmark
    from pecha_api.plans.series.series_response_models import SeriesMetadataDTO

    series_id = uuid4()
    mock_db = MagicMock()
    mock_series = MagicMock()
    mock_series.id = series_id
    mock_series.status = "PUBLISHED"
    mock_series.plans = []
    mock_series.metadata_entries = []
    mock_series.image = "series/original/series.png"
    start_date = datetime.now(timezone.utc)
    end_date = datetime.now(timezone.utc)
    metadata = SeriesMetadataDTO(
        id=uuid4(),
        title="Series title",
        language="BO",
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_series_by_id",
        return_value=mock_series,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._to_plan_status",
        return_value=__import__(
            "pecha_api.plans.plans_enums", fromlist=["PlanStatus"]
        ).PlanStatus.PUBLISHED,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._series_schedule_from_plans",
        return_value=(start_date, end_date, 10),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._metadata_response",
        return_value=metadata,
    ) as mock_metadata_response, patch(
        "pecha_api.bookmarks.bookmark_utils._bookmark_image_url",
        return_value="https://example.com/series.png",
    ) as mock_image_url:
        result = enrich_series_bookmark(
            db=mock_db,
            source_id=str(series_id),
            language="BO",
        )

    mock_metadata_response.assert_called_once_with(
        [],
        language="BO",
        fallback=True,
    )
    mock_image_url.assert_called_once_with(
        "series/original/series.png",
        resource_id=series_id,
        resource_type="series",
    )
    assert result["series"].id == series_id
    assert result["series"].metadata == metadata
    assert result["series"].image == "https://example.com/series.png"
    assert result["series"].start_date == start_date
    assert result["series"].end_date == end_date


def test_enrich_series_bookmark_returns_empty_when_unpublished():
    from pecha_api.bookmarks.bookmark_utils import enrich_series_bookmark
    from pecha_api.plans.plans_enums import PlanStatus

    series_id = uuid4()

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_series_by_id",
        return_value=MagicMock(),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._to_plan_status",
        return_value=PlanStatus.DRAFT,
    ):
        result = enrich_series_bookmark(db=MagicMock(), source_id=str(series_id))

    assert result == {}


def test_enrich_accumulator_bookmark_success():
    from pecha_api.bookmarks.bookmark_utils import enrich_accumulator_bookmark

    accumulator_id = uuid4()
    mock_db = MagicMock()
    mock_accumulator = MagicMock()
    mock_accumulator.id = accumulator_id
    mock_accumulator.mantra_id = None
    metadata_entry = MagicMock()
    metadata_entry.name = "Mala Practice"
    mock_accumulator.metadata_entries = [metadata_entry]

    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = (
        mock_accumulator
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.resolve_accumulator_bookmark_mala_image_url",
        return_value="https://example.com/mala.png",
    ):
        result = enrich_accumulator_bookmark(
            db=mock_db,
            source_id=str(accumulator_id),
        )

    assert result["accumulator"].id == accumulator_id
    assert result["accumulator"].title == "Mala Practice"
    assert result["accumulator"].image == "https://example.com/mala.png"


def test_enrich_accumulator_bookmark_uses_mantra_title_and_image():
    from pecha_api.bookmarks.bookmark_utils import enrich_accumulator_bookmark

    accumulator_id = uuid4()
    mantra_id = uuid4()
    mock_db = MagicMock()
    mock_accumulator = MagicMock()
    mock_accumulator.id = accumulator_id
    mock_accumulator.mantra_id = mantra_id
    # Accumulator's own metadata should be ignored in favour of the mantra's.
    accumulator_metadata = MagicMock()
    accumulator_metadata.name = "Accumulator Title"
    mock_accumulator.metadata_entries = [accumulator_metadata]

    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = (
        mock_accumulator
    )

    mock_mantra = MagicMock()
    mock_mantra.mala.url = "s3://bucket/mantra.png"
    mantra_metadata = MagicMock()
    mantra_metadata.title = "Mantra Title"
    mock_mantra.metadata_entries = [mantra_metadata]

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_mantra_by_id",
        return_value=mock_mantra,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.resolve_accumulator_bookmark_mala_image_url",
        return_value="https://example.com/accumulator.png",
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.generate_mala_image_presigned_url",
        return_value="https://example.com/mantra.png",
    ):
        result = enrich_accumulator_bookmark(
            db=mock_db,
            source_id=str(accumulator_id),
        )

    assert result["accumulator"].id == accumulator_id
    assert result["accumulator"].title == "Mantra Title"
    assert result["accumulator"].image == "https://example.com/mantra.png"


def test_enrich_accumulator_bookmark_falls_back_when_mantra_incomplete():
    from pecha_api.bookmarks.bookmark_utils import enrich_accumulator_bookmark

    accumulator_id = uuid4()
    mantra_id = uuid4()
    mock_db = MagicMock()
    mock_accumulator = MagicMock()
    mock_accumulator.id = accumulator_id
    mock_accumulator.mantra_id = mantra_id
    accumulator_metadata = MagicMock()
    accumulator_metadata.name = "Accumulator Title"
    mock_accumulator.metadata_entries = [accumulator_metadata]

    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = (
        mock_accumulator
    )

    # Mantra exists but has no mala image and no metadata title.
    mock_mantra = MagicMock()
    mock_mantra.mala = None
    mock_mantra.metadata_entries = []

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_mantra_by_id",
        return_value=mock_mantra,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.resolve_accumulator_bookmark_mala_image_url",
        return_value="https://example.com/accumulator.png",
    ):
        result = enrich_accumulator_bookmark(
            db=mock_db,
            source_id=str(accumulator_id),
        )

    # Falls back per-field to the accumulator's own title/image.
    assert result["accumulator"].title == "Accumulator Title"
    assert result["accumulator"].image == "https://example.com/accumulator.png"


def test_enrich_accumulator_bookmark_filters_metadata_by_language():
    from pecha_api.bookmarks.bookmark_utils import enrich_accumulator_bookmark

    accumulator_id = uuid4()
    mock_db = MagicMock()
    mock_accumulator = MagicMock()
    mock_accumulator.id = accumulator_id
    mock_accumulator.mantra_id = None
    metadata_entry = MagicMock()
    metadata_entry.name = "བོད་ཡིག་མཚན་"
    mock_accumulator.metadata_entries = [metadata_entry]

    mock_db.query.return_value.options.return_value.filter.return_value.first.return_value = (
        mock_accumulator
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.resolve_accumulator_bookmark_mala_image_url",
        return_value=None,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.filter_by_language_with_fallback",
        return_value=[metadata_entry],
    ) as mock_filter:
        result = enrich_accumulator_bookmark(
            db=mock_db,
            source_id=str(accumulator_id),
            language="BO",
        )

    mock_filter.assert_called_once()
    assert result["accumulator"].title == "བོད་ཡིག་མཚན་"


def test_enrich_timer_bookmark_success():
    from pecha_api.bookmarks.bookmark_utils import enrich_timer_bookmark

    timer_id = uuid4()
    ambient_sound_id = uuid4()
    mock_timer = MagicMock()
    mock_timer.id = timer_id
    mock_timer.name = "Meditation Timer"
    mock_timer.duration = 600
    mock_timer.ambient_sound_id = ambient_sound_id
    mock_timer.bell_at_start = True
    mock_timer.bell_at_end = False

    mock_ambient_sound = MagicMock()
    mock_ambient_sound.name = "Rain"

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_timer_by_id",
        return_value=mock_timer,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_ambient_sound_by_id",
        return_value=mock_ambient_sound,
    ):
        result = enrich_timer_bookmark(db=MagicMock(), source_id=str(timer_id))

    assert result["timer"].id == timer_id
    assert result["timer"].title == "Meditation Timer"
    assert result["timer"].duration == 600
    assert result["timer"].ambient_sound_name == "Rain"
    assert result["timer"].bell_at_start is True
    assert result["timer"].bell_at_end is False


def test_enrich_timer_bookmark_no_ambient_sound():
    from pecha_api.bookmarks.bookmark_utils import enrich_timer_bookmark

    timer_id = uuid4()
    mock_timer = MagicMock()
    mock_timer.id = timer_id
    mock_timer.name = "Meditation Timer"
    mock_timer.duration = 600
    mock_timer.ambient_sound_id = None
    mock_timer.bell_at_start = True
    mock_timer.bell_at_end = True

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_timer_by_id",
        return_value=mock_timer,
    ) as mock_get_timer, patch(
        "pecha_api.bookmarks.bookmark_utils.get_ambient_sound_by_id",
    ) as mock_get_ambient_sound:
        result = enrich_timer_bookmark(db=MagicMock(), source_id=str(timer_id))

    mock_get_ambient_sound.assert_not_called()
    assert result["timer"].ambient_sound_name is None


def test_enrich_timer_bookmark_returns_empty_when_not_found():
    from pecha_api.bookmarks.bookmark_utils import enrich_timer_bookmark

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_timer_by_id",
        return_value=None,
    ):
        result = enrich_timer_bookmark(db=MagicMock(), source_id=str(uuid4()))

    assert result == {}


def test_enrich_recitation_collection_bookmark_success() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_recitation_collection_bookmark,
    )

    collection_id = uuid4()
    user_id = uuid4()
    mock_collection = MagicMock()
    mock_collection.id = collection_id
    mock_collection.name = "My Daily Recitations"
    mock_collection.img_url = "collections/daily.jpg"

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_recitation_collection_by_id",
        return_value=mock_collection,
    ) as mock_get, patch(
        "pecha_api.bookmarks.bookmark_utils.get_recitation_collection_item_counts",
        return_value={collection_id: 3},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._generate_collection_image_url",
        return_value="https://cdn.example.com/daily.jpg",
    ):
        result = enrich_recitation_collection_bookmark(
            db=MagicMock(),
            source_id=str(collection_id),
            user_id=user_id,
        )

    assert mock_get.call_args.kwargs["user_id"] == user_id
    dto = result["recitation_collection"]
    assert dto.id == collection_id
    assert dto.title == "My Daily Recitations"
    assert dto.image == "https://cdn.example.com/daily.jpg"
    assert dto.item_count == 3


def test_enrich_recitation_collection_bookmark_returns_empty_when_not_found() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_recitation_collection_bookmark,
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_recitation_collection_by_id",
        return_value=None,
    ):
        result = enrich_recitation_collection_bookmark(
            db=MagicMock(),
            source_id=str(uuid4()),
            user_id=uuid4(),
        )

    assert result == {}


def test_enrich_recitation_collection_bookmark_returns_empty_for_invalid_uuid() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_recitation_collection_bookmark,
    )

    result = enrich_recitation_collection_bookmark(
        db=MagicMock(),
        source_id="not-a-uuid",
        user_id=uuid4(),
    )

    assert result == {}


def _mock_group_collection(
    collection_id: UUID,
    group_id: UUID,
    name: str,
    img_url: Optional[str],
) -> MagicMock:
    mock_collection = MagicMock()
    mock_collection.id = collection_id
    mock_collection.group_id = group_id
    mock_collection.name = name
    mock_collection.img_url = img_url
    return mock_collection


def _mock_group(*, is_public: bool, group_status: str = "PUBLISHED") -> MagicMock:
    mock_group = MagicMock()
    mock_group.is_public = is_public
    # Published by default; these cases cover is_public on a live group.
    mock_group.status = group_status
    return mock_group


def test_enrich_group_recitation_collection_bookmark_success() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_group_recitation_collection_bookmark,
    )

    collection_id = uuid4()
    group_id = uuid4()
    mock_collection = _mock_group_collection(
        collection_id, group_id, "Morning Chants", "collections/morning.jpg"
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_without_group_filter",
        return_value=mock_collection,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=_mock_group(is_public=True),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_item_counts",
        return_value={collection_id: 5},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._generate_collection_image_url",
        return_value="https://cdn.example.com/morning.jpg",
    ):
        result = enrich_group_recitation_collection_bookmark(
            db=MagicMock(),
            source_id=str(collection_id),
            user_id=uuid4(),
        )

    dto = result["group_recitation_collection"]
    assert dto.id == collection_id
    assert dto.group_id == group_id
    assert dto.title == "Morning Chants"
    assert dto.image == "https://cdn.example.com/morning.jpg"
    assert dto.item_count == 5


def test_enrich_group_recitation_collection_bookmark_allows_private_group_member() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_group_recitation_collection_bookmark,
    )

    collection_id = uuid4()
    user_id = uuid4()
    mock_collection = _mock_group_collection(
        collection_id, uuid4(), "Private Chants", None
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_without_group_filter",
        return_value=mock_collection,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=_mock_group(is_public=False),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_member",
        return_value=MagicMock(),
    ) as mock_get_member, patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_item_counts",
        return_value={collection_id: 2},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._generate_collection_image_url",
        return_value=None,
    ):
        result = enrich_group_recitation_collection_bookmark(
            db=MagicMock(),
            source_id=str(collection_id),
            user_id=user_id,
        )

    assert mock_get_member.call_args.kwargs["author_id"] == user_id
    assert result["group_recitation_collection"].id == collection_id


def test_enrich_group_recitation_collection_bookmark_returns_empty_for_non_member() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_group_recitation_collection_bookmark,
    )

    collection_id = uuid4()
    mock_collection = _mock_group_collection(
        collection_id, uuid4(), "Private Chants", None
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_without_group_filter",
        return_value=mock_collection,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=_mock_group(is_public=False),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_member",
        return_value=None,
    ):
        result = enrich_group_recitation_collection_bookmark(
            db=MagicMock(),
            source_id=str(collection_id),
            user_id=uuid4(),
        )

    assert result == {}


def test_enrich_group_recitation_collection_bookmark_returns_empty_when_group_missing() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_group_recitation_collection_bookmark,
    )

    collection_id = uuid4()
    mock_collection = _mock_group_collection(
        collection_id, uuid4(), "Orphan Chants", None
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_without_group_filter",
        return_value=mock_collection,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=None,
    ):
        result = enrich_group_recitation_collection_bookmark(
            db=MagicMock(),
            source_id=str(collection_id),
            user_id=uuid4(),
        )

    assert result == {}


def test_enrich_group_recitation_collection_bookmark_returns_empty_when_not_found() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_group_recitation_collection_bookmark,
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_without_group_filter",
        return_value=None,
    ):
        result = enrich_group_recitation_collection_bookmark(
            db=MagicMock(),
            source_id=str(uuid4()),
            user_id=uuid4(),
        )

    assert result == {}


def test_enrich_group_recitation_collection_bookmark_returns_empty_for_invalid_uuid() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_group_recitation_collection_bookmark,
    )

    result = enrich_group_recitation_collection_bookmark(
        db=MagicMock(),
        source_id="not-a-uuid",
        user_id=uuid4(),
    )

    assert result == {}


def test_enrich_group_recitation_collection_bookmark_defaults_item_count_to_zero() -> None:
    from pecha_api.bookmarks.bookmark_utils import (
        enrich_group_recitation_collection_bookmark,
    )

    collection_id = uuid4()
    mock_collection = _mock_group_collection(
        collection_id, uuid4(), "Empty Collection", None
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_without_group_filter",
        return_value=mock_collection,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=_mock_group(is_public=True),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_collection_item_counts",
        return_value={},
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._generate_collection_image_url",
        return_value=None,
    ):
        result = enrich_group_recitation_collection_bookmark(
            db=MagicMock(),
            source_id=str(collection_id),
            user_id=uuid4(),
        )

    dto = result["group_recitation_collection"]
    assert dto.item_count == 0
    assert dto.image is None


@pytest.mark.asyncio
async def test_resolve_localized_text_returns_matching_group_text():
    from pecha_api.bookmarks.bookmark_utils import _resolve_localized_text

    text_id = str(uuid4())
    localized_text = MagicMock()
    localized_text.language = "BO"

    source_text = MagicMock()
    source_text.group_id = uuid4()

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=source_text,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_versions_from_openpecha",
        new_callable=AsyncMock,
        return_value=MagicMock(text=source_text, versions=[localized_text]),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.filter_by_language_with_fallback",
        return_value=[localized_text],
    ):
        result = await _resolve_localized_text(text_id=text_id, language="BO")

    assert result is localized_text


@pytest.mark.asyncio
async def test_enrich_text_bookmark_falls_back_when_localized_text_missing():
    text_id = str(uuid4())
    segment_id = str(uuid4())

    bookmark = MagicMock()
    bookmark.type = BookmarkType.TEXT
    bookmark.source_id = text_id
    bookmark.name = None

    mock_text = MagicMock()
    mock_text.title = "Original title"

    with patch(
        "pecha_api.bookmarks.bookmark_utils._resolve_localized_text",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_text_by_id_from_openpecha",
        new_callable=AsyncMock,
        return_value=mock_text,
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.build_first_segment_preview_for_text",
        new_callable=AsyncMock,
        return_value=(segment_id, "Fallback content"),
    ):
        result = await enrich_text_bookmark(bookmark, language="BO")

    assert result["text"].title == "Original title"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bookmark_type,patch_target",
    [
        (BookmarkType.TEXT, "enrich_text_bookmark"),
        (BookmarkType.VERSE, "enrich_text_bookmark"),
        (BookmarkType.PLAN, "enrich_plan_bookmark"),
        (BookmarkType.SERIES, "enrich_series_bookmark"),
        (BookmarkType.ACCUMULATOR, "enrich_accumulator_bookmark"),
        (BookmarkType.TIMER, "enrich_timer_bookmark"),
        (
            BookmarkType.RECITATION_COLLECTION,
            "enrich_recitation_collection_bookmark",
        ),
        (
            BookmarkType.GROUP_RECITATION_COLLECTION,
            "enrich_group_recitation_collection_bookmark",
        ),
    ],
)
async def test_enrich_bookmark_dispatches_by_type(bookmark_type, patch_target):
    from pecha_api.bookmarks import bookmark_utils

    bookmark = MagicMock()
    bookmark.type = bookmark_type
    bookmark.source_id = str(uuid4())
    mock_db = MagicMock()
    expected = {"key": "value"}

    if bookmark_type in (BookmarkType.TEXT, BookmarkType.VERSE):
        with patch.object(
            bookmark_utils,
            patch_target,
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_enrich:
            result = await bookmark_utils.enrich_bookmark(
                bookmark=bookmark,
                db=mock_db,
                language=" bo ",
            )
        mock_enrich.assert_awaited_once_with(bookmark, language="BO")
    elif bookmark_type in (
        BookmarkType.RECITATION_COLLECTION,
        BookmarkType.GROUP_RECITATION_COLLECTION,
    ):
        with patch.object(
            bookmark_utils,
            patch_target,
            return_value=expected,
        ) as mock_enrich:
            result = await bookmark_utils.enrich_bookmark(
                bookmark=bookmark,
                db=mock_db,
                language="EN",
            )
        mock_enrich.assert_called_once_with(
            db=mock_db,
            source_id=bookmark.source_id,
            user_id=bookmark.user_id,
        )
    elif bookmark_type == BookmarkType.TIMER:
        with patch.object(
            bookmark_utils,
            patch_target,
            return_value=expected,
        ) as mock_enrich:
            result = await bookmark_utils.enrich_bookmark(
                bookmark=bookmark,
                db=mock_db,
                language="EN",
            )
        mock_enrich.assert_called_once_with(
            db=mock_db,
            source_id=bookmark.source_id,
        )
    else:
        with patch.object(
            bookmark_utils,
            patch_target,
            return_value=expected,
        ) as mock_enrich:
            result = await bookmark_utils.enrich_bookmark(
                bookmark=bookmark,
                db=mock_db,
                language="EN",
            )
        mock_enrich.assert_called_once_with(
            db=mock_db,
            source_id=bookmark.source_id,
            language="EN",
        )

    assert result == expected


@pytest.mark.asyncio
async def test_enrich_bookmark_returns_empty_for_unknown_type():
    from pecha_api.bookmarks.bookmark_utils import enrich_bookmark

    bookmark = MagicMock()
    bookmark.type = "UNKNOWN"

    result = await enrich_bookmark(bookmark=bookmark, db=MagicMock())

    assert result == {}



# --- GROUP_ACCUMULATOR bookmarks -------------------------------------------


def _mock_group_accumulator(
    group_accumulator_id: UUID,
    group_id: UUID,
    title: Optional[str],
    image_key: Optional[str],
) -> MagicMock:
    mock_group_accumulator = MagicMock()
    mock_group_accumulator.id = group_accumulator_id
    mock_group_accumulator.group_id = group_id
    mock_group_accumulator.title = title
    mock_group_accumulator.image_key = image_key
    return mock_group_accumulator


def _db_returning_group_accumulator(group_accumulator) -> MagicMock:
    db = MagicMock()
    query_chain = MagicMock()
    query_chain.filter.return_value = query_chain
    query_chain.first.return_value = group_accumulator
    db.query.return_value = query_chain
    return db


def test_enrich_group_accumulator_bookmark_success() -> None:
    from pecha_api.bookmarks.bookmark_utils import enrich_group_accumulator_bookmark

    group_accumulator_id = uuid4()
    group_id = uuid4()
    db = _db_returning_group_accumulator(
        _mock_group_accumulator(
            group_accumulator_id, group_id, "Group Mani", "group/mani.jpg"
        )
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=_mock_group(is_public=True),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._generate_collection_image_url",
        return_value="https://cdn.example.com/mani.jpg",
    ):
        result = enrich_group_accumulator_bookmark(
            db=db,
            source_id=str(group_accumulator_id),
            user_id=uuid4(),
        )

    dto = result["group_accumulator"]
    assert dto.id == group_accumulator_id
    assert dto.group_id == group_id
    assert dto.title == "Group Mani"
    assert dto.image == "https://cdn.example.com/mani.jpg"


def test_enrich_group_accumulator_bookmark_allows_private_group_member() -> None:
    from pecha_api.bookmarks.bookmark_utils import enrich_group_accumulator_bookmark

    group_accumulator_id = uuid4()
    user_id = uuid4()
    db = _db_returning_group_accumulator(
        _mock_group_accumulator(group_accumulator_id, uuid4(), "Private Mani", None)
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=_mock_group(is_public=False),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_member",
        return_value=MagicMock(),
    ) as mock_get_member, patch(
        "pecha_api.bookmarks.bookmark_utils._generate_collection_image_url",
        return_value=None,
    ):
        result = enrich_group_accumulator_bookmark(
            db=db,
            source_id=str(group_accumulator_id),
            user_id=user_id,
        )

    assert mock_get_member.call_args.kwargs["author_id"] == user_id
    assert result["group_accumulator"].id == group_accumulator_id


def test_enrich_group_accumulator_bookmark_returns_empty_for_non_member() -> None:
    from pecha_api.bookmarks.bookmark_utils import enrich_group_accumulator_bookmark

    group_accumulator_id = uuid4()
    db = _db_returning_group_accumulator(
        _mock_group_accumulator(group_accumulator_id, uuid4(), "Private Mani", None)
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=_mock_group(is_public=False),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_member",
        return_value=None,
    ):
        result = enrich_group_accumulator_bookmark(
            db=db,
            source_id=str(group_accumulator_id),
            user_id=uuid4(),
        )

    assert result == {}


def test_enrich_group_accumulator_bookmark_returns_empty_when_group_missing() -> None:
    from pecha_api.bookmarks.bookmark_utils import enrich_group_accumulator_bookmark

    group_accumulator_id = uuid4()
    db = _db_returning_group_accumulator(
        _mock_group_accumulator(group_accumulator_id, uuid4(), "Orphan Mani", None)
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=None,
    ):
        result = enrich_group_accumulator_bookmark(
            db=db,
            source_id=str(group_accumulator_id),
            user_id=uuid4(),
        )

    assert result == {}


def test_enrich_group_accumulator_bookmark_returns_empty_when_missing() -> None:
    from pecha_api.bookmarks.bookmark_utils import enrich_group_accumulator_bookmark

    db = _db_returning_group_accumulator(None)

    result = enrich_group_accumulator_bookmark(
        db=db,
        source_id=str(uuid4()),
        user_id=uuid4(),
    )

    assert result == {}


def test_enrich_group_accumulator_bookmark_returns_empty_for_non_uuid_source() -> None:
    from pecha_api.bookmarks.bookmark_utils import enrich_group_accumulator_bookmark

    db = MagicMock()

    result = enrich_group_accumulator_bookmark(
        db=db,
        source_id="not-a-uuid",
        user_id=uuid4(),
    )

    assert result == {}
    db.query.assert_not_called()


def test_enrich_group_accumulator_bookmark_defaults_missing_title() -> None:
    """title is nullable on group_accumulators but required on the DTO."""
    from pecha_api.bookmarks.bookmark_utils import enrich_group_accumulator_bookmark

    group_accumulator_id = uuid4()
    db = _db_returning_group_accumulator(
        _mock_group_accumulator(group_accumulator_id, uuid4(), None, None)
    )

    with patch(
        "pecha_api.bookmarks.bookmark_utils.get_group_by_id",
        return_value=_mock_group(is_public=True),
    ), patch(
        "pecha_api.bookmarks.bookmark_utils._generate_collection_image_url",
        return_value=None,
    ):
        result = enrich_group_accumulator_bookmark(
            db=db,
            source_id=str(group_accumulator_id),
            user_id=uuid4(),
        )

    assert result["group_accumulator"].title == ""


@pytest.mark.asyncio
async def test_enrich_bookmark_dispatches_group_accumulator() -> None:
    from pecha_api.bookmarks.bookmark_utils import enrich_bookmark

    bookmark = MagicMock()
    bookmark.type = BookmarkType.GROUP_ACCUMULATOR
    bookmark.source_id = str(uuid4())
    bookmark.user_id = uuid4()

    with patch(
        "pecha_api.bookmarks.bookmark_utils.enrich_group_accumulator_bookmark",
        return_value={"group_accumulator": "sentinel"},
    ) as mock_enrich:
        result = await enrich_bookmark(bookmark=bookmark, db=MagicMock())

    assert result == {"group_accumulator": "sentinel"}
    assert mock_enrich.call_args.kwargs["user_id"] == bookmark.user_id
