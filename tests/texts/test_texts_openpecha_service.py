import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from pecha_api.texts.texts_openpecha_service import (
    _extract_title,
    _map_external_text_to_dto,
    _get_texts_by_collection_id,
    _fetch_versions_from_parent,
    _fetch_versions_from_related,
    _fetch_commentaries_from_parent,
    _fetch_commentaries_from_related,
    map_external_text_to_dto,
    map_external_text_to_text_version,
    paginate_versions,
    fetch_translation_details,
    fetch_commentary_details,
    get_texts_by_collection_from_openpecha,
    get_titles_and_ids_by_query,
    get_text_by_id_from_openpecha,
    get_text_versions_from_openpecha,
    get_text_versions_by_edition_from_openpecha,
    get_text_versions_by_language_from_openpecha,
    get_text_languages_from_openpecha,
    get_text_commentaries_from_openpecha,
    get_text_commentaries_by_edition_from_openpecha,
)
from pecha_api.texts.texts_response_models import (
    TextDTO,
    TextVersion,
    TextVersionResponse,
    TitleSearchResult,
    V2TextDTO,
    V2TextsCategoryResponse,
)
from pecha_api.texts.text_openpecha_response_models import CriticalEditionModel

MOCK_EXTERNAL_TEXT_DATA = {
    "id": "text-123",
    "bdrc": "bdrc-123",
    "title": {"en": "Heart Sutra", "bo": "ཤེས་རབ་སྙིང་པོ།"},
    "language": "bo",
    "category_id": "cat-1",
    "date": "2025-01-01",
    "license": "CC0",
    "translations": ["trans-1", "trans-2"],
    "commentaries": ["comm-1"]
}

MOCK_TRANSLATION_DATA = {
    "id": "trans-1",
    "title": {"en": "English Translation"},
    "language": "en",
    "translation_of": "text-123",
    "category_id": "cat-1",
    "date": "2025-01-02",
    "license": "CC BY"
}


def _text_item(text_id: str, lang: str) -> dict:
    return {
        "id": text_id,
        "title": {lang: f"Title {text_id}"},
        "language": lang,
    }


class TestExtractTitle:
    """Tests for _extract_title helper function."""

    def test_extract_title_from_dict_with_language(self):
        title_payload = {"en": "English Title", "bo": "བོད་ཡིག"}
        result = _extract_title(title_payload, "en")
        assert result == "English Title"

    def test_extract_title_from_dict_fallback(self):
        title_payload = {"en": "English Title", "bo": "བོད་ཡིག"}
        result = _extract_title(title_payload, "zh")
        assert result == "English Title"

    def test_extract_title_from_string(self):
        title_payload = "Simple Title"
        result = _extract_title(title_payload, "en")
        assert result == "Simple Title"

    def test_extract_title_strips_whitespace_from_string(self):
        assert _extract_title("  Plain title  ") == "Plain title"

    def test_extract_title_empty_dict(self):
        title_payload = {}
        result = _extract_title(title_payload, "en")
        assert result == ""

    def test_extract_title_none_language(self):
        title_payload = {"en": "English Title"}
        result = _extract_title(title_payload, None)
        assert result == "English Title"

    def test_extract_title_unsupported_type_returns_empty(self):
        assert _extract_title(123) == ""
        assert _extract_title(None) == ""


class TestMapExternalTextToDto:
    """Tests for map_external_text_to_dto function (legacy TextDTO mapper)."""

    def test_map_complete_data(self):
        result = map_external_text_to_dto(MOCK_EXTERNAL_TEXT_DATA, "en")

        assert isinstance(result, TextDTO)
        assert result.id == "text-123"
        assert result.pecha_text_id == "bdrc-123"
        assert result.title == "Heart Sutra"
        assert result.language == "bo"
        assert result.group_id == "cat-1"
        assert result.type == "root_text"
        assert result.is_published is True
        assert result.license == "CC0"

    def test_map_source_link_from_edition(self):
        data = {**MOCK_EXTERNAL_TEXT_DATA, "source_link": "https://example.com/source"}
        result = map_external_text_to_dto(data, "en")
        assert result.source_link == "https://example.com/source"

    def test_map_minimal_data(self):
        minimal_data = {"id": "min-123"}
        result = map_external_text_to_dto(minimal_data, "en")

        assert result.id == "min-123"
        assert result.pecha_text_id == "min-123"
        assert result.title == ""
        assert result.language == ""

    def test_map_with_bdrc_fallback(self):
        data_with_bdrc = {"id": "id-123", "bdrc": "bdrc-456"}
        result = map_external_text_to_dto(data_with_bdrc, "en")

        assert result.pecha_text_id == "bdrc-456"

    def test_map_categories_from_category_id(self):
        data = {"id": "id-123", "category_id": "cat-abc"}
        result = map_external_text_to_dto(data, "en")

        assert result.categories == ["cat-abc"]


class TestMapExternalTextToV2Dto:
    """Tests for _map_external_text_to_dto (V2TextDTO mapper)."""

    def test_map_external_text_to_dto(self):
        dto = _map_external_text_to_dto(
            {"id": "t1", "title": {"en": "Title"}, "language": "en", "license": "CC0"},
            "en",
        )
        assert isinstance(dto, V2TextDTO)
        assert dto.id == "t1"
        assert dto.title == "Title"
        assert dto.language == "en"
        assert dto.license == "CC0"


class TestMapExternalTextToTextVersion:
    """Tests for map_external_text_to_text_version function."""

    def test_map_translation_data(self):
        result = map_external_text_to_text_version(MOCK_TRANSLATION_DATA, "en")

        assert isinstance(result, TextVersion)
        assert result.id == "trans-1"
        assert result.title == "English Translation"
        assert result.parent_id == "text-123"
        assert result.language == "en"
        assert result.type == "translation"
        assert result.license == "CC BY"

    def test_map_translation_source_link(self):
        data = {**MOCK_TRANSLATION_DATA, "source_link": "https://example.com/source"}
        result = map_external_text_to_text_version(data, "en")
        assert result.source_link == "https://example.com/source"

    def test_map_commentary_data(self):
        commentary_data = {
            "id": "comm-1",
            "title": {"en": "Commentary"},
            "language": "bo",
            "commentary_of": "text-123",
            "date": "2025-01-01"
        }
        result = map_external_text_to_text_version(commentary_data, "en")

        assert result.parent_id == "text-123"


class TestPaginateVersions:
    """Tests for paginate_versions function."""

    def test_paginate_first_page(self):
        versions = [MagicMock(id=f"v{i}") for i in range(10)]

        result = paginate_versions(versions, skip=0, limit=5)

        assert len(result) == 5

    def test_paginate_second_page(self):
        versions = [MagicMock(id=f"v{i}") for i in range(10)]

        result = paginate_versions(versions, skip=5, limit=5)

        assert len(result) == 5

    def test_paginate_beyond_data(self):
        versions = [MagicMock(id=f"v{i}") for i in range(5)]

        result = paginate_versions(versions, skip=10, limit=5)

        assert len(result) == 0

    def test_paginate_partial_page(self):
        versions = [MagicMock(id=f"v{i}") for i in range(7)]

        result = paginate_versions(versions, skip=5, limit=5)

        assert len(result) == 2


# =============================================================================
# Service Function Tests - _get_texts_by_collection_id
# =============================================================================

class TestGetTextsByCollectionId:
    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_passes_skip_and_limit_to_upstream_without_language(self, mock_fetch_texts):
        mock_fetch_texts.return_value = {
            "items": [
                _text_item("t-en", "en"),
                _text_item("t-bo", "bo"),
                _text_item("t-zh", "zh"),
            ],
            "has_more": True,
        }

        texts, has_more = await _get_texts_by_collection_id(
            collection_id="cat-1",
            skip=5,
            limit=3,
        )

        assert [t.id for t in texts] == ["t-en", "t-bo", "t-zh"]
        assert [t.language for t in texts] == ["en", "bo", "zh"]
        assert has_more is True

        mock_fetch_texts.assert_awaited_once_with(
            category_id="cat-1",
            language=None,
            title=None,
            offset=5,
            limit=3,
        )

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_passes_title_filter_to_upstream(self, mock_fetch_texts):
        mock_fetch_texts.return_value = {
            "items": [_text_item("t-en", "en")],
            "has_more": False,
        }

        texts, has_more = await _get_texts_by_collection_id(
            collection_id="cat-1",
            skip=0,
            limit=10,
            title="heart",
        )

        assert len(texts) == 1
        assert has_more is False
        mock_fetch_texts.assert_awaited_once_with(
            category_id="cat-1",
            language=None,
            title="heart",
            offset=0,
            limit=10,
        )

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_returns_empty_list_when_no_items(self, mock_fetch_texts):
        mock_fetch_texts.return_value = {"items": [], "has_more": False}

        texts, has_more = await _get_texts_by_collection_id(
            collection_id="cat-1",
            skip=0,
            limit=10,
        )

        assert texts == []
        assert has_more is False

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_defaults_has_more_to_false_when_upstream_omits_it(self, mock_fetch_texts):
        mock_fetch_texts.return_value = {
            "items": [_text_item("t-en", "en")],
        }

        texts, has_more = await _get_texts_by_collection_id(
            collection_id="cat-1",
            skip=0,
            limit=10,
        )

        assert len(texts) == 1
        assert has_more is False

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_upstream_failure_maps_to_502(self, mock_fetch_texts):
        mock_fetch_texts.side_effect = Exception("connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await _get_texts_by_collection_id(
                collection_id="cat-1",
                skip=0,
                limit=10,
            )

        assert exc_info.value.status_code == 502


# =============================================================================
# Service Function Tests - get_texts_by_collection_from_openpecha (V2)
# =============================================================================

class TestGetTextsByCollectionFromOpenpecha:
    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_category_by_id", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_get_texts_success(self, mock_fetch_texts, mock_fetch_category):
        mock_fetch_texts.return_value = {
            "items": [
                {"id": "t-en", "title": {"en": "EN Text"}, "language": "en"},
                {"id": "t-bo", "title": {"bo": "BO Text"}, "language": "bo"},
            ],
            "has_more": False,
        }
        mock_fetch_category.return_value = {"title": {"en": "Collection"}}

        result = await get_texts_by_collection_from_openpecha(
            collection_id="cat-1",
            skip=0,
            limit=10,
        )

        assert isinstance(result, V2TextsCategoryResponse)
        assert result.collection.id == "cat-1"
        assert result.collection.title == "Collection"
        assert len(result.texts) == 2
        assert result.texts[0].id == "t-en"
        assert result.texts[1].id == "t-bo"
        assert result.has_more is False

        mock_fetch_texts.assert_awaited_once_with(
            category_id="cat-1",
            language=None,
            title=None,
            offset=0,
            limit=10,
        )

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_category_by_id", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_get_texts_with_language_filter(self, mock_fetch_texts, mock_fetch_category):
        mock_fetch_texts.return_value = {
            "items": [{"id": "t-bo", "title": {"bo": "BO Text"}, "language": "bo"}],
            "has_more": False,
        }
        mock_fetch_category.return_value = {"title": {"bo": "Collection"}}

        result = await get_texts_by_collection_from_openpecha(
            collection_id="cat-1",
            language="bo",
            skip=0,
            limit=10,
        )

        assert len(result.texts) == 1
        assert result.texts[0].language == "bo"
        mock_fetch_texts.assert_awaited_once_with(
            category_id="cat-1",
            language="bo",
            title=None,
            offset=0,
            limit=10,
        )
        mock_fetch_category.assert_awaited_once_with("cat-1", language="bo")

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_category_by_id", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_get_texts_with_title_filter(self, mock_fetch_texts, mock_fetch_category):
        mock_fetch_texts.return_value = {
            "items": [{"id": "t-en", "title": {"en": "Heart Sutra"}, "language": "en"}],
            "has_more": False,
        }
        mock_fetch_category.return_value = {"title": {"en": "Collection"}}

        result = await get_texts_by_collection_from_openpecha(
            collection_id="cat-1",
            title="heart",
            skip=0,
            limit=10,
        )

        assert len(result.texts) == 1
        mock_fetch_texts.assert_awaited_once_with(
            category_id="cat-1",
            language=None,
            title="heart",
            offset=0,
            limit=10,
        )

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_category_by_id", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_get_texts_with_pagination(self, mock_fetch_texts, mock_fetch_category):
        mock_fetch_texts.return_value = {
            "items": [
                {"id": "t-1", "title": {"en": "Text 1"}, "language": "en"},
            ],
            "has_more": True,
        }
        mock_fetch_category.return_value = None

        result = await get_texts_by_collection_from_openpecha(
            collection_id="cat-1",
            skip=1,
            limit=1,
        )

        assert len(result.texts) == 1
        assert result.texts[0].id == "t-1"
        assert result.skip == 1
        assert result.limit == 1
        assert result.has_more is True

        mock_fetch_texts.assert_awaited_once_with(
            category_id="cat-1",
            language=None,
            title=None,
            offset=1,
            limit=1,
        )

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_get_texts_upstream_error(self, mock_fetch_texts):
        mock_fetch_texts.side_effect = Exception("connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await get_texts_by_collection_from_openpecha(collection_id="cat-1")

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_category_by_id", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_get_texts_category_upstream_error(self, mock_fetch_texts, mock_fetch_category):
        mock_fetch_texts.return_value = {"items": [], "has_more": False}
        mock_fetch_category.side_effect = Exception("connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await get_texts_by_collection_from_openpecha(collection_id="cat-1")

        assert exc_info.value.status_code == 502
        assert "category" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_category_by_id", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_get_texts_without_collection_id(self, mock_fetch_texts, mock_fetch_category):
        mock_fetch_texts.return_value = {
            "items": [{"id": "t1", "title": {"en": "Text 1"}, "language": "en"}],
            "has_more": False,
        }

        result = await get_texts_by_collection_from_openpecha(skip=0, limit=10)

        assert result.collection is None
        assert len(result.texts) == 1
        mock_fetch_texts.assert_awaited_once_with(
            category_id=None,
            language=None,
            title=None,
            offset=0,
            limit=10,
        )
        mock_fetch_category.assert_not_awaited()


# =============================================================================
# Service Function Tests - get_titles_and_ids_by_query
# =============================================================================

class TestGetTitlesAndIdsByQuery:
    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_critical_editions", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_returns_edition_id_as_id(self, mock_fetch_texts, mock_fetch_editions):
        mock_fetch_texts.return_value = {
            "items": [
                {"id": "t-en", "title": {"en": "Heart Sutra"}, "language": "en"},
                {"id": "t-bo", "title": {"bo": "ཤེས་རབ་སྙིང་པོ།"}, "language": "bo"},
            ],
            "has_more": False,
        }

        async def fake_fetch_editions(text_id):
            return [CriticalEditionModel(id=f"edition-{text_id}", type="critical")]

        mock_fetch_editions.side_effect = fake_fetch_editions

        result = await get_titles_and_ids_by_query(title="heart", limit=20, offset=0)

        assert result == [
            TitleSearchResult(id="edition-t-en", title="Heart Sutra"),
            TitleSearchResult(id="edition-t-bo", title="ཤེས་རབ་སྙིང་པོ།"),
        ]
        mock_fetch_texts.assert_awaited_once_with(
            category_id=None,
            language=None,
            title="heart",
            offset=0,
            limit=20,
        )
        mock_fetch_editions.assert_any_await(text_id="t-en")
        mock_fetch_editions.assert_any_await(text_id="t-bo")

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_critical_editions", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_omits_texts_without_a_critical_edition(self, mock_fetch_texts, mock_fetch_editions):
        mock_fetch_texts.return_value = {
            "items": [
                {"id": "t-with-edition", "title": {"en": "Has Edition"}, "language": "en"},
                {"id": "t-without-edition", "title": {"en": "No Edition"}, "language": "en"},
            ],
            "has_more": False,
        }

        async def fake_fetch_editions(text_id):
            if text_id == "t-with-edition":
                return [CriticalEditionModel(id="edition-1", type="critical")]
            return []

        mock_fetch_editions.side_effect = fake_fetch_editions

        result = await get_titles_and_ids_by_query(title="edition")

        assert result == [TitleSearchResult(id="edition-1", title="Has Edition")]

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_critical_editions", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_omits_text_when_edition_fetch_fails(self, mock_fetch_texts, mock_fetch_editions):
        mock_fetch_texts.return_value = {
            "items": [{"id": "t-1", "title": {"en": "Text 1"}, "language": "en"}],
            "has_more": False,
        }
        mock_fetch_editions.side_effect = Exception("connection refused")

        result = await get_titles_and_ids_by_query(title="text")

        assert result == []

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_passes_offset_and_limit_to_upstream(self, mock_fetch_texts):
        mock_fetch_texts.return_value = {"items": [], "has_more": False}

        await get_titles_and_ids_by_query(title="sutra", limit=5, offset=10)

        mock_fetch_texts.assert_awaited_once_with(
            category_id=None,
            language=None,
            title="sutra",
            offset=10,
            limit=5,
        )

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_critical_editions", new_callable=AsyncMock)
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_missing_title_returns_default_listing(self, mock_fetch_texts, mock_fetch_editions):
        mock_fetch_texts.return_value = {
            "items": [{"id": "t-1", "title": {"en": "Text 1"}, "language": "en"}],
            "has_more": False,
        }
        mock_fetch_editions.return_value = [CriticalEditionModel(id="edition-1", type="critical")]

        result = await get_titles_and_ids_by_query(title=None)

        assert result == [TitleSearchResult(id="edition-1", title="Text 1")]
        mock_fetch_texts.assert_awaited_once_with(
            category_id=None,
            language=None,
            title=None,
            offset=0,
            limit=20,
        )

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_empty_title_is_treated_as_default_listing(self, mock_fetch_texts):
        mock_fetch_texts.return_value = {"items": [], "has_more": False}

        await get_titles_and_ids_by_query(title="")

        mock_fetch_texts.assert_awaited_once_with(
            category_id=None,
            language=None,
            title=None,
            offset=0,
            limit=20,
        )

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_texts_by_category", new_callable=AsyncMock)
    async def test_upstream_failure_maps_to_502(self, mock_fetch_texts):
        mock_fetch_texts.side_effect = Exception("connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await get_titles_and_ids_by_query(title="heart")

        assert exc_info.value.status_code == 502


# =============================================================================
# Service Function Tests - get_text_by_id_from_openpecha (V2)
# =============================================================================

class TestGetTextByIdFromOpenpecha:
    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_text_by_id", new_callable=AsyncMock)
    async def test_get_text_by_id_success(self, mock_fetch_text):
        mock_fetch_text.return_value = {
            "id": "t1",
            "title": {"en": "Test Text"},
            "language": "en",
            "license": "CC0",
        }

        result = await get_text_by_id_from_openpecha("t1")

        assert isinstance(result, V2TextDTO)
        assert result.id == "t1"
        assert result.title == "Test Text"
        assert result.language == "en"
        assert result.license == "CC0"

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_text_by_id", new_callable=AsyncMock)
    async def test_get_text_by_id_not_found(self, mock_fetch_text):
        mock_fetch_text.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_text_by_id_from_openpecha("missing")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("pecha_api.texts.texts_openpecha_service.fetch_text_by_id", new_callable=AsyncMock)
    async def test_get_text_by_id_upstream_error(self, mock_fetch_text):
        mock_fetch_text.side_effect = Exception("timeout")

        with pytest.raises(HTTPException) as exc_info:
            await get_text_by_id_from_openpecha("t1")

        assert exc_info.value.status_code == 502


# =============================================================================
# Service Function Tests - get_text_versions_from_openpecha
# =============================================================================

class TestGetTextVersionsFromOpenpecha:
    """Tests for get_text_versions_from_openpecha service function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_translation_details')
    async def test_get_text_versions_success(self, mock_fetch_translations, mock_fetch_text):
        """Test default behavior when commentary_of is set (skips related text lookup)."""
        # Text with commentary_of set - goes to default behavior
        text_data = {
            "id": "text-123",
            "bdrc": "bdrc-123",
            "title": {"en": "Heart Sutra", "bo": "ཤེས་རབ་སྙིང་པོ།"},
            "language": "bo",
            "category_id": "cat-1",
            "date": "2025-01-01",
            "license": "CC0",
            "commentary_of": "parent-text",  # Has commentary_of, so default behavior applies
            "translation_of": None,
            "translations": ["trans-1", "trans-2"],
            "commentaries": ["comm-1"]
        }
        mock_fetch_text.return_value = text_data
        mock_fetch_translations.return_value = [MOCK_TRANSLATION_DATA]

        result = await get_text_versions_from_openpecha(
            text_id="text-123",
            skip=0,
            limit=10
        )

        assert isinstance(result, TextVersionResponse)
        assert result.text is not None
        assert result.text.id == "text-123"
        assert len(result.versions) == 1
        mock_fetch_text.assert_called_once_with("text-123")

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_text_versions_text_not_found(self, mock_fetch_text):
        mock_fetch_text.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_text_versions_from_openpecha(
                text_id="nonexistent",
                skip=0,
                limit=10
            )

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_text_versions_upstream_error(self, mock_fetch_text):
        mock_fetch_text.side_effect = Exception("Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await get_text_versions_from_openpecha(
                text_id="text-123",
                skip=0,
                limit=10
            )

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_text_versions_no_translations(self, mock_fetch_text):
        text_without_translations = {
            "id": "text-123",
            "title": {"en": "Test"},
            "language": "bo",
            "translations": []
        }
        mock_fetch_text.return_value = text_without_translations

        result = await get_text_versions_from_openpecha(
            text_id="text-123",
            skip=0,
            limit=10
        )

        assert result.text is not None
        assert len(result.versions) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_translation_details')
    async def test_get_text_versions_with_pagination(self, mock_fetch_translations, mock_fetch_text):
        mock_fetch_text.return_value = MOCK_EXTERNAL_TEXT_DATA
        mock_fetch_translations.return_value = [
            {"id": f"t{i}", "title": {"en": f"Trans {i}"}, "language": "en", "translation_of": "text-123"}
            for i in range(5)
        ]

        result = await get_text_versions_from_openpecha(
            text_id="text-123",
            skip=2,
            limit=2
        )

        assert len(result.versions) == 2

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_translation_details')
    async def test_get_text_versions_with_translation_of(self, mock_fetch_translations, mock_fetch_text):
        """When translation_of is not null, fetch versions from the parent text."""
        # First call: the requested text has translation_of pointing to parent
        translation_text = {
            "id": "trans-1",
            "title": {"en": "Translation"},
            "language": "en",
            "translation_of": "root-text-123",
            "commentary_of": None,
            "translations": [],
            "commentaries": []
        }
        # Second call: the parent text has translations
        parent_text = {
            "id": "root-text-123",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "translations": ["trans-1", "trans-2"],
            "commentaries": []
        }
        mock_fetch_text.side_effect = [translation_text, parent_text]
        mock_fetch_translations.return_value = [
            {"id": "trans-1", "title": {"en": "Translation 1"}, "language": "en", "translation_of": "root-text-123"},
            {"id": "trans-2", "title": {"en": "Translation 2"}, "language": "zh", "translation_of": "root-text-123"}
        ]

        result = await get_text_versions_from_openpecha(text_id="trans-1", skip=0, limit=10)

        assert result.text.id == "trans-1"
        # trans-1 is the requested text itself, so it must not be listed as
        # one of its own available versions.
        assert len(result.versions) == 1
        assert result.versions[0].id == "trans-2"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_translation_details')
    async def test_get_text_versions_own_translations_win_over_translation_of(
        self, mock_fetch_translations, mock_fetch_text
    ):
        """translation_of only says what this text is a translation OF, not what
        translations exist of it. A root text that is itself a translation of an
        earlier source (e.g. a Tibetan root translated from Sanskrit) must still
        report its own translations directly - it must not climb to that earlier
        source and report its (unrelated) translations instead."""
        root_text = {
            "id": "root-bo",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "translation_of": "grandparent-sa",
            "commentary_of": None,
            "translations": ["trans-zh", "trans-en"],
            "commentaries": [],
        }
        mock_fetch_text.return_value = root_text
        mock_fetch_translations.return_value = [
            {"id": "trans-zh", "title": {"zh": "Chinese"}, "language": "zh"},
            {"id": "trans-en", "title": {"en": "English"}, "language": "en"},
        ]

        result = await get_text_versions_from_openpecha(text_id="root-bo", skip=0, limit=10)

        mock_fetch_text.assert_called_once_with("root-bo")
        mock_fetch_translations.assert_called_once_with(["trans-zh", "trans-en"])
        assert result.text.id == "root-bo"
        assert {v.id for v in result.versions} == {"trans-zh", "trans-en"}

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_translation_details')
    async def test_get_text_versions_both_null_with_translations_list(self, mock_fetch_translations, mock_fetch_text):
        """When both commentary_of and translation_of are null, check translations list."""
        # Root text with translations list
        root_text = {
            "id": "root-123",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "translation_of": None,
            "commentary_of": None,
            "translations": ["trans-1"],
            "commentaries": []
        }
        # The translation has translation_of pointing to a parent
        translation_text = {
            "id": "trans-1",
            "title": {"en": "Translation"},
            "language": "en",
            "translation_of": "root-123",
            "translations": [],
            "commentaries": []
        }
        # Parent text (root-123) has translations
        parent_text = {
            "id": "root-123",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "translations": ["trans-1", "trans-2"],
            "commentaries": []
        }
        mock_fetch_text.side_effect = [root_text, translation_text, parent_text]
        mock_fetch_translations.return_value = [
            {"id": "trans-1", "title": {"en": "Translation 1"}, "language": "en"},
            {"id": "trans-2", "title": {"en": "Translation 2"}, "language": "zh"}
        ]

        result = await get_text_versions_from_openpecha(text_id="root-123", skip=0, limit=10)

        assert result.text.id == "root-123"
        assert len(result.versions) == 2

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_translation_details')
    async def test_get_text_versions_prefers_own_translations_over_commentary(
        self, mock_fetch_translations, mock_fetch_text
    ):
        """A text's own translations must win over the related-commentary
        fallback, even when it also has commentaries — otherwise this and
        get_text_languages_from_openpecha (which counts the same list) can
        disagree about what a text's versions are."""
        root_text = {
            "id": "root-123",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "translation_of": None,
            "commentary_of": None,
            "translations": ["trans-1"],
            "commentaries": ["comm-1"],
        }
        mock_fetch_text.return_value = root_text
        mock_fetch_translations.return_value = [
            {"id": "trans-1", "title": {"en": "Translation 1"}, "language": "en"},
        ]

        result = await get_text_versions_from_openpecha(text_id="root-123", skip=0, limit=10)

        mock_fetch_text.assert_called_once_with("root-123")
        mock_fetch_translations.assert_called_once_with(["trans-1"])
        assert result.text.id == "root-123"
        assert len(result.versions) == 1
        assert result.versions[0].id == "trans-1"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_translation_details')
    async def test_get_text_versions_falls_back_to_commentary_when_no_translations(
        self, mock_fetch_translations, mock_fetch_text
    ):
        """With no translations of its own, a root text still borrows versions
        from its first commentary's translations."""
        root_text = {
            "id": "root-123",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "translation_of": None,
            "commentary_of": None,
            "translations": [],
            "commentaries": ["comm-1"],
        }
        commentary_text = {
            "id": "comm-1",
            "title": {"bo": "Commentary"},
            "language": "bo",
            "translation_of": None,
            "translations": ["trans-1"],
        }
        mock_fetch_text.side_effect = [root_text, commentary_text]
        mock_fetch_translations.return_value = [
            {"id": "trans-1", "title": {"en": "Translation 1"}, "language": "en"},
        ]

        result = await get_text_versions_from_openpecha(text_id="root-123", skip=0, limit=10)

        assert result.text.id == "root-123"
        assert len(result.versions) == 1
        assert result.versions[0].id == "trans-1"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_text_versions_translation_of_parent_not_found(self, mock_fetch_text):
        """When translation_of parent is not found, return empty versions."""
        translation_text = {
            "id": "trans-1",
            "title": {"en": "Translation"},
            "language": "en",
            "translation_of": "missing-parent",
            "commentary_of": None
        }
        mock_fetch_text.side_effect = [translation_text, None]

        result = await get_text_versions_from_openpecha(text_id="trans-1", skip=0, limit=10)

        assert result.text.id == "trans-1"
        assert len(result.versions) == 0


# =============================================================================
# Service Function Tests - get_text_languages_from_openpecha
# =============================================================================

class TestGetTextLanguagesFromOpenpecha:
    """Tests for get_text_languages_from_openpecha service function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.get_text_versions_from_openpecha', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_get_text_languages_groups_and_counts_by_language(self, mock_fetch_edition_text_id, mock_get_versions):
        mock_fetch_edition_text_id.return_value = "text-123"
        mock_get_versions.return_value = TextVersionResponse(
            text=TextDTO(
                id="text-123",
                title="Heart Sutra",
                language="bo",
                group_id="group-123",
                type="root_text",
                is_published=True,
                created_date="2025-01-01T00:00:00",
                updated_date="2025-01-01T00:00:00",
                published_date="2025-01-01T00:00:00",
                published_by="pecha",
                categories=["cat-1"],
                views=0,
            ),
            versions=[
                TextVersion(id="v1", title="English 1", language="en", type="translation", group_id="g", is_published=True,
                            created_date="d", updated_date="d", published_date="d", published_by="p"),
                TextVersion(id="v2", title="English 2", language="en", type="translation", group_id="g", is_published=True,
                            created_date="d", updated_date="d", published_date="d", published_by="p"),
                TextVersion(id="v3", title="Chinese 1", language="zh", type="translation", group_id="g", is_published=True,
                            created_date="d", updated_date="d", published_date="d", published_by="p"),
            ]
        )

        result = await get_text_languages_from_openpecha(edition_id="edition-abc")

        mock_fetch_edition_text_id.assert_awaited_once_with(edition_id="edition-abc")
        mock_get_versions.assert_awaited_once_with(text_id="text-123", skip=0, limit=1000)
        assert result.text_id == "edition-abc"
        assert result.title == "Heart Sutra"
        counts = {lang.language: lang.version_count for lang in result.available_languages}
        assert counts == {"en": 2, "zh": 1}

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.get_text_versions_from_openpecha', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_get_text_languages_no_versions(self, mock_fetch_edition_text_id, mock_get_versions):
        mock_fetch_edition_text_id.return_value = "text-123"
        mock_get_versions.return_value = TextVersionResponse(
            text=TextDTO(
                id="text-123",
                title="Heart Sutra",
                language="bo",
                group_id="group-123",
                type="root_text",
                is_published=True,
                created_date="2025-01-01T00:00:00",
                updated_date="2025-01-01T00:00:00",
                published_date="2025-01-01T00:00:00",
                published_by="pecha",
                categories=[],
                views=0,
            ),
            versions=[]
        )

        result = await get_text_languages_from_openpecha(edition_id="edition-abc")

        assert result.available_languages == []

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_get_text_languages_edition_not_found(self, mock_fetch_edition_text_id):
        mock_fetch_edition_text_id.side_effect = HTTPException(status_code=404, detail="Edition with id 'missing' not found")

        with pytest.raises(HTTPException) as exc_info:
            await get_text_languages_from_openpecha(edition_id="missing")

        assert exc_info.value.status_code == 404


# =============================================================================
# Service Function Tests - get_text_versions_by_edition_from_openpecha
# =============================================================================

class TestGetTextVersionsByEditionFromOpenpecha:
    """Tests for get_text_versions_by_edition_from_openpecha service function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.get_text_versions_from_openpecha', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_resolves_edition_id_to_text_id(self, mock_fetch_edition_text_id, mock_get_versions):
        mock_fetch_edition_text_id.return_value = "text-123"
        mock_get_versions.return_value = TextVersionResponse(
            text=TextDTO(
                id="text-123",
                title="Heart Sutra",
                language="bo",
                group_id="group-123",
                type="root_text",
                is_published=True,
                created_date="2025-01-01T00:00:00",
                updated_date="2025-01-01T00:00:00",
                published_date="2025-01-01T00:00:00",
                published_by="pecha",
                categories=["cat-1"],
                views=0,
            ),
            versions=[]
        )

        result = await get_text_versions_by_edition_from_openpecha(edition_id="edition-abc", skip=0, limit=10)

        mock_fetch_edition_text_id.assert_awaited_once_with(edition_id="edition-abc")
        mock_get_versions.assert_awaited_once_with(text_id="text-123", skip=0, limit=10)
        assert result.text.id == "text-123"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.get_text_versions_from_openpecha', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_falls_back_to_raw_id_when_not_an_edition(self, mock_fetch_edition_text_id, mock_get_versions):
        """OpenPecha 404s /v2/editions/{id} when given a real text id, so the
        raw id is used as-is instead of the (nonexistent) resolved edition."""
        mock_fetch_edition_text_id.side_effect = HTTPException(status_code=404, detail="Edition with id 'text-123' not found")
        mock_get_versions.return_value = TextVersionResponse(
            text=TextDTO(
                id="text-123",
                title="Heart Sutra",
                language="bo",
                group_id="group-123",
                type="root_text",
                is_published=True,
                created_date="2025-01-01T00:00:00",
                updated_date="2025-01-01T00:00:00",
                published_date="2025-01-01T00:00:00",
                published_by="pecha",
                categories=[],
                views=0,
            ),
            versions=[]
        )

        result = await get_text_versions_by_edition_from_openpecha(edition_id="text-123")

        mock_get_versions.assert_awaited_once_with(text_id="text-123", skip=0, limit=10)
        assert result.text.id == "text-123"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_propagates_non_404_errors(self, mock_fetch_edition_text_id):
        mock_fetch_edition_text_id.side_effect = HTTPException(status_code=502, detail="Failed to fetch edition from OpenPecha API")

        with pytest.raises(HTTPException) as exc_info:
            await get_text_versions_by_edition_from_openpecha(edition_id="edition-abc")

        assert exc_info.value.status_code == 502


# =============================================================================
# Service Function Tests - get_text_versions_by_language_from_openpecha
# =============================================================================

class TestGetTextVersionsByLanguageFromOpenpecha:
    """Tests for get_text_versions_by_language_from_openpecha service function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.get_text_versions_from_openpecha', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_resolves_edition_id_to_text_id(self, mock_fetch_edition_text_id, mock_get_versions):
        mock_fetch_edition_text_id.return_value = "text-123"
        mock_get_versions.return_value = TextVersionResponse(
            text=TextDTO(
                id="text-123",
                title="Heart Sutra",
                language="bo",
                group_id="group-123",
                type="root_text",
                is_published=True,
                created_date="2025-01-01T00:00:00",
                updated_date="2025-01-01T00:00:00",
                published_date="2025-01-01T00:00:00",
                published_by="pecha",
                categories=[],
                views=0,
            ),
            versions=[]
        )

        result = await get_text_versions_by_language_from_openpecha(
            edition_id="edition-abc", language="bo", skip=0, limit=10
        )

        mock_fetch_edition_text_id.assert_awaited_once_with(edition_id="edition-abc")
        mock_get_versions.assert_awaited_once_with(text_id="text-123", language="bo", skip=0, limit=10)
        assert result.text_id == "edition-abc"
        assert result.language == "bo"
        assert result.available_versions == []

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_propagates_non_404_errors(self, mock_fetch_edition_text_id):
        mock_fetch_edition_text_id.side_effect = HTTPException(status_code=502, detail="Failed to fetch edition from OpenPecha API")

        with pytest.raises(HTTPException) as exc_info:
            await get_text_versions_by_language_from_openpecha(edition_id="edition-abc", language="bo")

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service._fetch_first_critical_edition_id', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.get_text_versions_from_openpecha', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_version_ids_are_resolved_to_edition_ids(
        self, mock_fetch_edition_text_id, mock_get_versions, mock_fetch_first_critical_edition_id
    ):
        mock_fetch_edition_text_id.return_value = "text-123"
        mock_get_versions.return_value = TextVersionResponse(
            text=TextDTO(
                id="text-123",
                title="Heart Sutra",
                language="bo",
                group_id="group-123",
                type="root_text",
                is_published=True,
                created_date="2025-01-01T00:00:00",
                updated_date="2025-01-01T00:00:00",
                published_date="2025-01-01T00:00:00",
                published_by="pecha",
                categories=[],
                views=0,
            ),
            versions=[
                TextVersion(
                    id="translation-text-1",
                    title="English Translation",
                    language="en",
                    type="translation",
                    is_published=True,
                    created_date="",
                    updated_date="",
                    published_date="",
                    published_by="",
                ),
                TextVersion(
                    id="translation-text-2",
                    title="Another Translation",
                    language="en",
                    type="translation",
                    is_published=True,
                    created_date="",
                    updated_date="",
                    published_date="",
                    published_by="",
                ),
            ]
        )
        mock_fetch_first_critical_edition_id.side_effect = ["edition-1", None]

        result = await get_text_versions_by_language_from_openpecha(
            edition_id="edition-abc", language="en", skip=0, limit=10
        )

        assert result.text_id == "edition-abc"
        assert len(result.available_versions) == 2
        assert result.available_versions[0].id == "edition-1"
        # Falls back to the raw text id when no critical edition is found
        assert result.available_versions[1].id == "translation-text-2"


# =============================================================================
# Service Function Tests - _fetch_versions_from_parent
# =============================================================================

class TestFetchVersionsFromParent:
    """Tests for _fetch_versions_from_parent helper function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_translation_details')
    async def test_fetch_versions_from_parent_success(self, mock_fetch_translations, mock_fetch_text):
        original_text = MagicMock(spec=TextDTO)
        original_text.id = "trans-1"
        parent_data = {
            "id": "root-123",
            "translations": ["trans-1", "trans-2"]
        }
        mock_fetch_text.return_value = parent_data
        mock_fetch_translations.return_value = [
            {"id": "trans-1", "title": {"en": "Trans 1"}, "language": "en"},
            {"id": "trans-2", "title": {"en": "Trans 2"}, "language": "zh"}
        ]

        result = await _fetch_versions_from_parent("root-123", original_text, None, 0, 10)

        assert result.text == original_text
        # trans-1 is original_text itself and must be excluded from its own
        # sibling versions.
        assert len(result.versions) == 1
        assert result.versions[0].id == "trans-2"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_fetch_versions_from_parent_not_found(self, mock_fetch_text):
        original_text = MagicMock(spec=TextDTO)
        mock_fetch_text.return_value = None

        result = await _fetch_versions_from_parent("missing", original_text, None, 0, 10)

        assert result.text == original_text
        assert len(result.versions) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_fetch_versions_from_parent_error(self, mock_fetch_text):
        original_text = MagicMock(spec=TextDTO)
        mock_fetch_text.side_effect = Exception("Connection error")

        result = await _fetch_versions_from_parent("root-123", original_text, None, 0, 10)

        assert result.text == original_text
        assert len(result.versions) == 0


# =============================================================================
# Service Function Tests - get_text_commentaries_by_edition_from_openpecha
# =============================================================================

class TestGetTextCommentariesByEditionFromOpenpecha:
    """Tests for get_text_commentaries_by_edition_from_openpecha service function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.get_text_commentaries_from_openpecha', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_resolves_edition_id_to_text_id(self, mock_fetch_edition_text_id, mock_get_commentaries):
        mock_fetch_edition_text_id.return_value = "text-123"
        mock_get_commentaries.return_value = []

        result = await get_text_commentaries_by_edition_from_openpecha(edition_id="edition-abc", skip=0, limit=10)

        mock_fetch_edition_text_id.assert_awaited_once_with(edition_id="edition-abc")
        mock_get_commentaries.assert_awaited_once_with(text_id="text-123", skip=0, limit=10)
        assert result == []

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.get_text_commentaries_from_openpecha', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_falls_back_to_raw_id_when_not_an_edition(self, mock_fetch_edition_text_id, mock_get_commentaries):
        """OpenPecha 404s /v2/editions/{id} when given a real text id, so the
        raw id is used as-is instead of the (nonexistent) resolved edition."""
        mock_fetch_edition_text_id.side_effect = HTTPException(status_code=404, detail="Edition with id 'text-123' not found")
        mock_get_commentaries.return_value = []

        result = await get_text_commentaries_by_edition_from_openpecha(edition_id="text-123")

        mock_get_commentaries.assert_awaited_once_with(text_id="text-123", skip=0, limit=10)
        assert result == []

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_edition_text_id', new_callable=AsyncMock)
    async def test_propagates_non_404_errors(self, mock_fetch_edition_text_id):
        mock_fetch_edition_text_id.side_effect = HTTPException(status_code=502, detail="Failed to fetch edition from OpenPecha API")

        with pytest.raises(HTTPException) as exc_info:
            await get_text_commentaries_by_edition_from_openpecha(edition_id="edition-abc")

        assert exc_info.value.status_code == 502


# =============================================================================
# Service Function Tests - get_text_commentaries_from_openpecha
# =============================================================================

class TestGetTextCommentariesFromOpenpecha:
    """Tests for get_text_commentaries_from_openpecha service function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_get_commentaries_success(self, mock_fetch_commentaries, mock_fetch_text):
        mock_fetch_text.return_value = {
            "id": "text-123",
            "title": {"en": "Root Text"},
            "language": "bo",
            "commentaries": ["comm-1", "comm-2"]
        }
        mock_fetch_commentaries.return_value = [
            {"id": "comm-1", "title": {"en": "Commentary 1"}, "language": "bo"},
            {"id": "comm-2", "title": {"en": "Commentary 2"}, "language": "en"}
        ]

        result = await get_text_commentaries_from_openpecha(
            text_id="text-123",
            skip=0,
            limit=10
        )

        assert len(result) == 2
        assert all(isinstance(c, TextDTO) for c in result)

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_commentaries_text_not_found(self, mock_fetch_text):
        mock_fetch_text.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_text_commentaries_from_openpecha(
                text_id="nonexistent",
                skip=0,
                limit=10
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_commentaries_upstream_failure(self, mock_fetch_text):
        mock_fetch_text.side_effect = Exception("upstream error")

        with pytest.raises(HTTPException) as exc_info:
            await get_text_commentaries_from_openpecha(
                text_id="text-123",
                skip=0,
                limit=10,
            )

        assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_commentaries_no_commentaries(self, mock_fetch_text):
        mock_fetch_text.return_value = {
            "id": "text-123",
            "title": {"en": "Root Text"},
            "language": "bo",
            "commentaries": []
        }

        result = await get_text_commentaries_from_openpecha(
            text_id="text-123",
            skip=0,
            limit=10
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_get_commentaries_with_pagination(self, mock_fetch_commentaries, mock_fetch_text):
        mock_fetch_text.return_value = {
            "id": "text-123",
            "title": {"en": "Root Text"},
            "language": "bo",
            "commentaries": ["c1", "c2", "c3", "c4", "c5"]
        }
        mock_fetch_commentaries.return_value = [
            {"id": f"c{i}", "title": {"en": f"Commentary {i}"}, "language": "bo"}
            for i in range(1, 6)
        ]

        result = await get_text_commentaries_from_openpecha(
            text_id="text-123",
            skip=2,
            limit=2
        )

        assert len(result) == 2

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_get_commentaries_skip_beyond_total(self, mock_fetch_commentaries, mock_fetch_text):
        mock_fetch_text.return_value = {
            "id": "text-123",
            "title": {"en": "Root Text"},
            "language": "bo",
            "commentaries": ["c1", "c2"]
        }
        mock_fetch_commentaries.return_value = [
            {"id": "c1", "title": {"en": "Commentary 1"}, "language": "bo"},
            {"id": "c2", "title": {"en": "Commentary 2"}, "language": "bo"}
        ]

        result = await get_text_commentaries_from_openpecha(
            text_id="text-123",
            skip=10,
            limit=5
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_get_commentaries_verifies_dto_mapping(self, mock_fetch_commentaries, mock_fetch_text):
        mock_fetch_text.return_value = {
            "id": "text-123",
            "title": {"en": "Root Text"},
            "language": "bo",
            "commentaries": ["comm-1"]
        }
        mock_fetch_commentaries.return_value = [
            {
                "id": "comm-1",
                "bdrc": "bdrc-comm-1",
                "title": {"en": "Commentary Title", "bo": "བསྟན་བཅོས།"},
                "language": "bo",
                "category_id": "cat-1",
                "date": "2025-01-01",
                "license": "CC BY"
            }
        ]

        result = await get_text_commentaries_from_openpecha(
            text_id="text-123",
            skip=0,
            limit=10
        )

        assert len(result) == 1
        commentary = result[0]
        assert commentary.id == "comm-1"
        assert commentary.pecha_text_id == "bdrc-comm-1"
        assert commentary.language == "bo"
        assert commentary.license == "CC BY"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_commentaries_missing_commentaries_key(self, mock_fetch_text):
        mock_fetch_text.return_value = {
            "id": "text-123",
            "title": {"en": "Root Text"},
            "language": "bo"
        }

        result = await get_text_commentaries_from_openpecha(
            text_id="text-123",
            skip=0,
            limit=10
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_get_commentaries_partial_fetch_failure(self, mock_fetch_commentaries, mock_fetch_text):
        mock_fetch_text.return_value = {
            "id": "text-123",
            "title": {"en": "Root Text"},
            "language": "bo",
            "commentaries": ["c1", "c2", "c3"]
        }
        mock_fetch_commentaries.return_value = [
            {"id": "c1", "title": {"en": "Commentary 1"}, "language": "bo"}
        ]

        result = await get_text_commentaries_from_openpecha(
            text_id="text-123",
            skip=0,
            limit=10
        )

        assert len(result) == 1
        assert result[0].id == "c1"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_get_commentaries_with_commentary_of(self, mock_fetch_commentaries, mock_fetch_text):
        """When commentary_of is not null, fetch commentaries from the parent text."""
        # First call: the requested text has commentary_of pointing to parent
        commentary_text = {
            "id": "comm-1",
            "title": {"en": "Commentary"},
            "language": "bo",
            "commentary_of": "root-text-123",
            "translation_of": None,
            "translations": [],
            "commentaries": []
        }
        # Second call: the parent text has commentaries
        parent_text = {
            "id": "root-text-123",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "commentaries": ["comm-1", "comm-2"]
        }
        mock_fetch_text.side_effect = [commentary_text, parent_text]
        mock_fetch_commentaries.return_value = [
            {"id": "comm-1", "title": {"en": "Commentary 1"}, "language": "bo"},
            {"id": "comm-2", "title": {"en": "Commentary 2"}, "language": "bo"}
        ]

        result = await get_text_commentaries_from_openpecha(text_id="comm-1", skip=0, limit=10)

        assert len(result) == 2
        assert result[0].id == "comm-1"
        assert result[1].id == "comm-2"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_get_commentaries_both_null_with_translations_list(self, mock_fetch_commentaries, mock_fetch_text):
        """When both commentary_of and translation_of are null, check translations/commentaries list."""
        # Root text with translations list
        root_text = {
            "id": "root-123",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "translation_of": None,
            "commentary_of": None,
            "translations": ["trans-1"],
            "commentaries": []
        }
        # The translation has commentary_of pointing to a parent
        translation_text = {
            "id": "trans-1",
            "title": {"en": "Translation"},
            "language": "en",
            "commentary_of": "root-123",
            "translations": [],
            "commentaries": []
        }
        # Parent text (root-123) has commentaries
        parent_text = {
            "id": "root-123",
            "title": {"bo": "Root Text"},
            "language": "bo",
            "commentaries": ["comm-1", "comm-2"]
        }
        mock_fetch_text.side_effect = [root_text, translation_text, parent_text]
        mock_fetch_commentaries.return_value = [
            {"id": "comm-1", "title": {"en": "Commentary 1"}, "language": "bo"},
            {"id": "comm-2", "title": {"en": "Commentary 2"}, "language": "bo"}
        ]

        result = await get_text_commentaries_from_openpecha(text_id="root-123", skip=0, limit=10)

        assert len(result) == 2

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_get_commentaries_commentary_of_parent_not_found(self, mock_fetch_text):
        """When commentary_of parent is not found, return empty commentaries."""
        commentary_text = {
            "id": "comm-1",
            "title": {"en": "Commentary"},
            "language": "bo",
            "commentary_of": "missing-parent",
            "translation_of": None
        }
        mock_fetch_text.side_effect = [commentary_text, None]

        result = await get_text_commentaries_from_openpecha(text_id="comm-1", skip=0, limit=10)

        assert len(result) == 0


# =============================================================================
# Service Function Tests - _fetch_commentaries_from_parent
# =============================================================================

class TestFetchCommentariesFromParent:
    """Tests for _fetch_commentaries_from_parent helper function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_fetch_commentaries_from_parent_success(self, mock_fetch_commentaries, mock_fetch_text):
        parent_data = {
            "id": "root-123",
            "commentaries": ["comm-1", "comm-2"]
        }
        mock_fetch_text.return_value = parent_data
        mock_fetch_commentaries.return_value = [
            {"id": "comm-1", "title": {"en": "Commentary 1"}, "language": "bo"},
            {"id": "comm-2", "title": {"en": "Commentary 2"}, "language": "bo"}
        ]

        result = await _fetch_commentaries_from_parent("root-123", 0, 10)

        assert len(result) == 2
        assert result[0].id == "comm-1"
        assert result[1].id == "comm-2"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_fetch_commentaries_from_parent_not_found(self, mock_fetch_text):
        mock_fetch_text.return_value = None

        result = await _fetch_commentaries_from_parent("missing", 0, 10)

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_fetch_commentaries_from_parent_error(self, mock_fetch_text):
        mock_fetch_text.side_effect = Exception("Connection error")

        result = await _fetch_commentaries_from_parent("root-123", 0, 10)

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_fetch_commentaries_from_parent_no_commentaries(self, mock_fetch_text):
        parent_data = {
            "id": "root-123",
            "commentaries": []
        }
        mock_fetch_text.return_value = parent_data

        result = await _fetch_commentaries_from_parent("root-123", 0, 10)

        assert len(result) == 0


# =============================================================================
# Service Function Tests - _fetch_commentaries_from_related
# =============================================================================

class TestFetchCommentariesFromRelated:
    """Tests for _fetch_commentaries_from_related helper function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_fetch_commentaries_from_related_with_commentary_of(self, mock_fetch_commentaries, mock_fetch_text):
        """When related text has commentary_of, fetch from that parent."""
        related_data = {
            "id": "trans-1",
            "commentary_of": "root-123",
            "commentaries": []
        }
        parent_data = {
            "id": "root-123",
            "commentaries": ["comm-1"]
        }
        mock_fetch_text.side_effect = [related_data, parent_data]
        mock_fetch_commentaries.return_value = [
            {"id": "comm-1", "title": {"en": "Commentary"}, "language": "bo"}
        ]

        result = await _fetch_commentaries_from_related("trans-1", 0, 10)

        assert len(result) == 1
        assert result[0].id == "comm-1"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    @patch('pecha_api.texts.texts_openpecha_service.fetch_commentary_details')
    async def test_fetch_commentaries_from_related_direct(self, mock_fetch_commentaries, mock_fetch_text):
        """When related text has no commentary_of, fetch its own commentaries."""
        related_data = {
            "id": "trans-1",
            "commentary_of": None,
            "commentaries": ["comm-1", "comm-2"]
        }
        mock_fetch_text.return_value = related_data
        mock_fetch_commentaries.return_value = [
            {"id": "comm-1", "title": {"en": "Commentary 1"}, "language": "bo"},
            {"id": "comm-2", "title": {"en": "Commentary 2"}, "language": "bo"}
        ]

        result = await _fetch_commentaries_from_related("trans-1", 0, 10)

        assert len(result) == 2

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_fetch_commentaries_from_related_not_found(self, mock_fetch_text):
        mock_fetch_text.return_value = None

        result = await _fetch_commentaries_from_related("missing", 0, 10)

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id')
    async def test_fetch_commentaries_from_related_error(self, mock_fetch_text):
        mock_fetch_text.side_effect = Exception("Connection error")

        result = await _fetch_commentaries_from_related("trans-1", 0, 10)

        assert len(result) == 0


class TestFetchCommentaryDetails:
    """Tests for fetch_commentary_details function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_source_link', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id', new_callable=AsyncMock)
    async def test_fetch_commentary_details_success(self, mock_fetch, mock_fetch_source):
        mock_fetch.return_value = {
            "id": "comm-1",
            "title": {"en": "Commentary"},
            "language": "bo",
            "license": "cc-by",
        }
        mock_fetch_source.return_value = "https://example.com/source"

        result = await fetch_commentary_details(["comm-1"])

        assert len(result) == 1
        assert result[0]["id"] == "comm-1"
        assert result[0]["license"] == "cc-by"
        assert result[0]["source_link"] == "https://example.com/source"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_source_link', new_callable=AsyncMock, return_value=None)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id', new_callable=AsyncMock)
    async def test_fetch_commentary_details_partial_failure(self, mock_fetch, mock_fetch_source):
        mock_fetch.side_effect = [
            {"id": "comm-1", "title": {"en": "Commentary 1"}, "language": "bo"},
            Exception("Not found"),
            {"id": "comm-3", "title": {"en": "Commentary 3"}, "language": "bo"}
        ]

        result = await fetch_commentary_details(["comm-1", "comm-2", "comm-3"])

        assert len(result) == 2
        assert result[0]["id"] == "comm-1"
        assert result[1]["id"] == "comm-3"

    @pytest.mark.asyncio
    async def test_fetch_commentary_details_empty_list(self):
        result = await fetch_commentary_details([])

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_source_link', new_callable=AsyncMock, return_value=None)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id', new_callable=AsyncMock)
    async def test_fetch_commentary_details_all_failures(self, mock_fetch, mock_fetch_source):
        mock_fetch.side_effect = Exception("Upstream error")

        result = await fetch_commentary_details(["comm-1", "comm-2"])

        assert len(result) == 0


class TestFetchTextDetailWithSource:
    """Tests for _fetch_text_detail_with_source helper."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_source_link', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id', new_callable=AsyncMock)
    async def test_returns_none_when_text_not_found(self, mock_fetch, mock_fetch_source):
        mock_fetch.return_value = None

        from pecha_api.texts.texts_openpecha_service import _fetch_text_detail_with_source

        result = await _fetch_text_detail_with_source("missing-id")

        assert result is None
        mock_fetch_source.assert_not_awaited()


class TestFetchTranslationDetails:
    """Tests for fetch_translation_details function."""

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_source_link', new_callable=AsyncMock)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id', new_callable=AsyncMock)
    async def test_fetch_translations_success(self, mock_fetch, mock_fetch_source):
        mock_fetch.return_value = MOCK_TRANSLATION_DATA
        mock_fetch_source.return_value = "https://example.com/source"

        result = await fetch_translation_details(["trans-1"])

        assert len(result) == 1
        assert result[0]["id"] == "trans-1"
        assert result[0]["source_link"] == "https://example.com/source"

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_source_link', new_callable=AsyncMock, return_value=None)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id', new_callable=AsyncMock)
    async def test_fetch_translations_partial_failure(self, mock_fetch, mock_fetch_source):
        mock_fetch.side_effect = [
            MOCK_TRANSLATION_DATA,
            Exception("Not found")
        ]

        result = await fetch_translation_details(["trans-1", "trans-2"])

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_fetch_translations_empty_list(self):
        result = await fetch_translation_details([])

        assert len(result) == 0

    @pytest.mark.asyncio
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_source_link', new_callable=AsyncMock, return_value=None)
    @patch('pecha_api.texts.texts_openpecha_service.fetch_text_by_id', new_callable=AsyncMock)
    async def test_fetch_translations_all_failures(self, mock_fetch, mock_fetch_source):
        mock_fetch.side_effect = Exception("Upstream error")

        result = await fetch_translation_details(["trans-1", "trans-2"])

        assert len(result) == 0
