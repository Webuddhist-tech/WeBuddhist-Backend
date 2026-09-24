from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.collections.collections_response_models import V2CollectionModel
from pecha_api.texts.texts_response_models import (
    AvailableLanguage,
    LanguageResponse,
    TextDTO,
    TextVersion,
    TextVersionResponse,
    TitleSearchResult,
    V2TextDTO,
    V2TextsCategoryResponse,
)


client = TestClient(api)

MOCK_TEXT_DTO = TextDTO(
    id="text-123",
    pecha_text_id="pecha-text-123",
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
    views=100,
    source_link="https://example.com",
    ranking=1,
    license="CC0"
)

MOCK_TEXT_VERSION_1 = TextVersion(
    id="version-1",
    title="English Translation",
    parent_id="text-123",
    priority=1,
    language="en",
    type="translation",
    group_id="group-123",
    table_of_contents=[],
    is_published=True,
    created_date="2025-01-01T00:00:00",
    updated_date="2025-01-01T00:00:00",
    published_date="2025-01-01T00:00:00",
    published_by="translator_1",
    source_link="https://translation.com",
    ranking=1,
    license="CC BY"
)

MOCK_TEXT_VERSION_2 = TextVersion(
    id="version-2",
    title="Chinese Translation",
    parent_id="text-123",
    priority=2,
    language="zh",
    type="translation",
    group_id="group-123",
    table_of_contents=[],
    is_published=True,
    created_date="2025-01-02T00:00:00",
    updated_date="2025-01-02T00:00:00",
    published_date="2025-01-02T00:00:00",
    published_by="translator_2",
    source_link=None,
    ranking=2,
    license="CC0"
)


# =============================================================================
# GET /v2/texts/collection/{collection_id} - View Layer Tests
# =============================================================================

class TestTextsV2Endpoint:
    @patch("pecha_api.texts.texts_openpecha_views.get_texts_by_collection_from_openpecha")
    def test_get_texts_without_collection_id(self, mock_service):
        mock_service.return_value = V2TextsCategoryResponse(
            collection=None,
            texts=[V2TextDTO(id="t1", title="Text 1", language="en")],
            skip=0,
            limit=10,
        )

        response = client.get("/texts")

        assert response.status_code == 200
        data = response.json()
        assert data["collection"] is None
        assert len(data["texts"]) == 1
        mock_service.assert_awaited_once_with(
            collection_id=None,
            language=None,
            title=None,
            skip=0,
            limit=10,
        )

    @patch("pecha_api.texts.texts_openpecha_views.get_texts_by_collection_from_openpecha")
    def test_get_texts_by_collection_success(self, mock_service):
        mock_service.return_value = V2TextsCategoryResponse(
            collection=V2CollectionModel(id="cat-1", title="Discourses"),
            texts=[
                V2TextDTO(id="t1", title="Text 1", language="en"),
                V2TextDTO(id="t2", title="Text 2", language="bo"),
            ],
            skip=0,
            limit=10,
        )

        response = client.get("/texts?collection_id=cat-1")

        assert response.status_code == 200
        data = response.json()
        assert data["collection"]["title"] == "Discourses"
        assert len(data["texts"]) == 2

    @patch("pecha_api.texts.texts_openpecha_views.get_texts_by_collection_from_openpecha")
    def test_get_texts_by_collection_with_title_filter(self, mock_service):
        mock_service.return_value = V2TextsCategoryResponse(
            collection=V2CollectionModel(id="cat-1", title="Discourses"),
            texts=[V2TextDTO(id="t1", title="Heart Sutra", language="en")],
            skip=0,
            limit=10,
        )

        response = client.get("/texts?collection_id=cat-1&title=heart&skip=0&limit=10")

        assert response.status_code == 200
        mock_service.assert_awaited_once_with(
            collection_id="cat-1",
            language=None,
            title="heart",
            skip=0,
            limit=10,
        )

    @patch("pecha_api.texts.texts_openpecha_views.get_text_by_id_from_openpecha")
    def test_get_text_by_id_success(self, mock_service):
        mock_service.return_value = V2TextDTO(
            id="t1",
            title="Test Text",
            language="en",
            license="CC0",
        )

        response = client.get("/texts/t1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "t1"
        assert data["title"] == "Test Text"


class TestTextsV2ValidationErrors:
    def test_invalid_skip_negative(self):
        response = client.get("/texts?collection_id=cat-1&skip=-1")
        assert response.status_code == 422

    def test_invalid_limit_zero(self):
        response = client.get("/texts?collection_id=cat-1&limit=0")
        assert response.status_code == 422


class TestTextsV2ErrorHandling:
    @patch("pecha_api.texts.texts_openpecha_views.get_texts_by_collection_from_openpecha")
    def test_get_texts_upstream_error(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=502,
            detail="Failed to fetch texts from upstream service",
        )

        response = client.get("/texts?collection_id=cat-1")

        assert response.status_code == 502
        assert "upstream" in response.json()["detail"].lower()

    @patch("pecha_api.texts.texts_openpecha_views.get_text_by_id_from_openpecha")
    def test_get_text_by_id_not_found(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=404,
            detail="Text with id 'missing' not found",
        )

        response = client.get("/texts/missing")

        assert response.status_code == 404


# =============================================================================
# GET /v2/texts/title-search - View Layer Tests
# =============================================================================

class TestTitleSearchEndpoint:
    @patch("pecha_api.texts.texts_openpecha_views.get_titles_and_ids_by_query")
    def test_search_titles_success(self, mock_service):
        mock_service.return_value = [
            TitleSearchResult(id="t-en", title="Heart Sutra"),
            TitleSearchResult(id="t-bo", title="ཤེས་རབ་སྙིང་པོ།"),
        ]

        response = client.get("/texts/title-search?title=heart&limit=20&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == "t-en"
        assert data[0]["title"] == "Heart Sutra"
        mock_service.assert_awaited_once_with(
            title="heart",
            limit=20,
            offset=0,
        )

    @patch("pecha_api.texts.texts_openpecha_views.get_titles_and_ids_by_query")
    def test_search_titles_uses_default_pagination(self, mock_service):
        mock_service.return_value = []

        response = client.get("/texts/title-search?title=heart")

        assert response.status_code == 200
        mock_service.assert_awaited_once_with(
            title="heart",
            limit=20,
            offset=0,
        )

    @patch("pecha_api.texts.texts_openpecha_views.get_titles_and_ids_by_query")
    def test_search_titles_missing_title_returns_default_listing(self, mock_service):
        mock_service.return_value = [TitleSearchResult(id="t-en", title="Heart Sutra")]

        response = client.get("/texts/title-search")

        assert response.status_code == 200
        assert response.json() == [{"id": "t-en", "title": "Heart Sutra"}]
        mock_service.assert_awaited_once_with(
            title=None,
            limit=20,
            offset=0,
        )

    @patch("pecha_api.texts.texts_openpecha_views.get_titles_and_ids_by_query")
    def test_search_titles_upstream_error(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=502,
            detail="Failed to fetch texts from upstream service",
        )

        response = client.get("/texts/title-search?title=heart")

        assert response.status_code == 502

    def test_search_titles_invalid_limit_returns_422(self):
        response = client.get("/texts/title-search?title=heart&limit=0")
        assert response.status_code == 422

    def test_search_titles_invalid_offset_returns_422(self):
        response = client.get("/texts/title-search?title=heart&offset=-1")
        assert response.status_code == 422


# =============================================================================
# GET /v2/texts/{text_id}/versions - View Layer Tests
# =============================================================================

class TestGetTextVersionsEndpoint:
    """Tests for GET /v2/texts/{text_id}/versions endpoint."""

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_get_text_versions_success(self, mock_service):
        mock_response = TextVersionResponse(
            text=MOCK_TEXT_DTO,
            versions=[MOCK_TEXT_VERSION_1, MOCK_TEXT_VERSION_2]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/text-123/versions")

        assert response.status_code == 200
        data = response.json()
        assert "text" in data
        assert "versions" in data
        assert data["text"]["id"] == "text-123"
        assert data["text"]["title"] == "Heart Sutra"
        assert len(data["versions"]) == 2
        assert data["versions"][0]["id"] == "version-1"
        assert data["versions"][1]["id"] == "version-2"
        mock_service.assert_called_once_with(
            edition_id="text-123",
            skip=0,
            limit=10
        )

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_get_text_versions_with_pagination(self, mock_service):
        mock_response = TextVersionResponse(
            text=MOCK_TEXT_DTO,
            versions=[MOCK_TEXT_VERSION_2]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/text-123/versions?skip=1&limit=5")

        assert response.status_code == 200
        data = response.json()
        assert len(data["versions"]) == 1
        mock_service.assert_called_once_with(
            edition_id="text-123",
            skip=1,
            limit=5
        )

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_get_text_versions_empty_versions(self, mock_service):
        mock_response = TextVersionResponse(
            text=MOCK_TEXT_DTO,
            versions=[]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/text-123/versions")

        assert response.status_code == 200
        data = response.json()
        assert data["text"]["id"] == "text-123"
        assert len(data["versions"]) == 0

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_get_text_versions_with_all_parameters(self, mock_service):
        mock_response = TextVersionResponse(
            text=MOCK_TEXT_DTO,
            versions=[MOCK_TEXT_VERSION_1]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/text-123/versions?skip=2&limit=20")

        assert response.status_code == 200
        mock_service.assert_called_once_with(
            edition_id="text-123",
            skip=2,
            limit=20
        )


class TestGetTextVersionsErrorHandling:
    """Tests for error handling in GET /v2/texts/{text_id}/versions endpoint."""

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_get_text_versions_not_found(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=404,
            detail="Text with id 'nonexistent' not found"
        )

        response = client.get("/texts/nonexistent/versions")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_get_text_versions_upstream_error(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=502,
            detail="Failed to fetch text from external API"
        )

        response = client.get("/texts/text-123/versions")

        assert response.status_code == 502
        assert "external" in response.json()["detail"].lower() or "failed" in response.json()["detail"].lower()

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_get_text_versions_internal_error(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=500,
            detail="Internal server error"
        )

        response = client.get("/texts/text-123/versions")

        assert response.status_code == 500


class TestGetTextVersionsResponseStructure:
    """Tests for response structure validation."""

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_response_contains_all_text_fields(self, mock_service):
        mock_response = TextVersionResponse(
            text=MOCK_TEXT_DTO,
            versions=[MOCK_TEXT_VERSION_1]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/text-123/versions")

        assert response.status_code == 200
        text_data = response.json()["text"]
        assert "id" in text_data
        assert "title" in text_data
        assert "language" in text_data
        assert "type" in text_data
        assert "is_published" in text_data
        assert "created_date" in text_data
        assert "categories" in text_data

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_response_contains_all_version_fields(self, mock_service):
        mock_response = TextVersionResponse(
            text=MOCK_TEXT_DTO,
            versions=[MOCK_TEXT_VERSION_1]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/text-123/versions")

        assert response.status_code == 200
        version_data = response.json()["versions"][0]
        assert "id" in version_data
        assert "title" in version_data
        assert "language" in version_data
        assert "type" in version_data
        assert "is_published" in version_data
        assert "parent_id" in version_data

    @patch('pecha_api.texts.texts_openpecha_views.get_text_versions_by_edition_from_openpecha')
    def test_response_with_optional_fields_none(self, mock_service):
        version_with_none = TextVersion(
            id="version-none",
            title="Version with None fields",
            parent_id=None,
            priority=None,
            language="en",
            type="translation",
            group_id="group-123",
            table_of_contents=[],
            is_published=True,
            created_date="2025-01-01T00:00:00",
            updated_date="2025-01-01T00:00:00",
            published_date="2025-01-01T00:00:00",
            published_by="translator",
            source_link=None,
            ranking=None,
            license=None
        )
        mock_response = TextVersionResponse(
            text=MOCK_TEXT_DTO,
            versions=[version_with_none]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/text-123/versions")

        assert response.status_code == 200
        version_data = response.json()["versions"][0]
        assert version_data["parent_id"] is None
        assert version_data["priority"] is None
        assert version_data["source_link"] is None
        assert version_data["ranking"] is None
        assert version_data["license"] is None


# =============================================================================
# GET /v2/texts/{edition_id}/languages - View Layer Tests
# =============================================================================

class TestGetLanguagesEndpoint:
    """Tests for GET /v2/texts/{edition_id}/languages endpoint."""

    @patch('pecha_api.texts.texts_openpecha_views.get_text_languages_from_openpecha')
    def test_get_languages_success(self, mock_service):
        mock_response = LanguageResponse(
            text_id="edition-123",
            title="Heart Sutra",
            available_languages=[
                AvailableLanguage(language="en", language_code="en", version_count=2),
                AvailableLanguage(language="bo", language_code="bo", version_count=1),
            ]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/edition-123/languages")

        assert response.status_code == 200
        data = response.json()
        assert data["text_id"] == "edition-123"
        assert data["title"] == "Heart Sutra"
        assert len(data["available_languages"]) == 2
        assert data["available_languages"][0]["version_count"] == 2
        mock_service.assert_called_once_with(edition_id="edition-123")

    @patch('pecha_api.texts.texts_openpecha_views.get_text_languages_from_openpecha')
    def test_get_languages_empty(self, mock_service):
        mock_response = LanguageResponse(
            text_id="edition-123",
            title="Heart Sutra",
            available_languages=[]
        )
        mock_service.return_value = mock_response

        response = client.get("/texts/edition-123/languages")

        assert response.status_code == 200
        assert response.json()["available_languages"] == []

    @patch('pecha_api.texts.texts_openpecha_views.get_text_languages_from_openpecha')
    def test_get_languages_edition_not_found(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=404,
            detail="Edition with id 'nonexistent' not found"
        )

        response = client.get("/texts/nonexistent/languages")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch('pecha_api.texts.texts_openpecha_views.get_text_languages_from_openpecha')
    def test_get_languages_upstream_error(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=502,
            detail="Failed to fetch text from upstream service"
        )

        response = client.get("/texts/edition-123/languages")

        assert response.status_code == 502


# =============================================================================
# GET /v2/texts/{edition_id}/commentaries - View Layer Tests
# =============================================================================

class TestGetTextCommentariesEndpoint:
    """Tests for GET /v2/texts/{edition_id}/commentaries endpoint."""

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_success(self, mock_service):
        mock_commentary = TextDTO(
            id="commentary-1",
            pecha_text_id="pecha-commentary-1",
            title="Commentary on Heart Sutra",
            language="bo",
            group_id="group-123",
            type="commentary",
            is_published=True,
            created_date="2025-01-01T00:00:00",
            updated_date="2025-01-01T00:00:00",
            published_date="2025-01-01T00:00:00",
            published_by="commentator",
            categories=["cat-1"],
            views=50,
            source_link=None,
            ranking=1,
            license="CC0"
        )
        mock_service.return_value = [mock_commentary]

        response = client.get("/texts/text-123/commentaries")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "commentary-1"
        assert data[0]["type"] == "commentary"
        mock_service.assert_called_once_with(
            edition_id="text-123",
            skip=0,
            limit=10
        )

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_multiple(self, mock_service):
        mock_commentaries = [
            TextDTO(
                id=f"commentary-{i}",
                pecha_text_id=f"pecha-commentary-{i}",
                title=f"Commentary {i}",
                language="bo" if i % 2 == 0 else "en",
                group_id="group-123",
                type="commentary",
                is_published=True,
                created_date="2025-01-01T00:00:00",
                updated_date="2025-01-01T00:00:00",
                published_date="2025-01-01T00:00:00",
                published_by=f"commentator-{i}",
                categories=["cat-1"],
                views=i * 10,
                source_link=None,
                ranking=i,
                license="CC0"
            )
            for i in range(1, 4)
        ]
        mock_service.return_value = mock_commentaries

        response = client.get("/texts/text-123/commentaries")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        assert data[0]["id"] == "commentary-1"
        assert data[1]["id"] == "commentary-2"
        assert data[2]["id"] == "commentary-3"

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_empty(self, mock_service):
        mock_service.return_value = []

        response = client.get("/texts/text-123/commentaries")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_with_pagination(self, mock_service):
        mock_service.return_value = []

        response = client.get("/texts/text-123/commentaries?skip=5&limit=20")

        assert response.status_code == 200
        mock_service.assert_called_once_with(
            edition_id="text-123",
            skip=5,
            limit=20
        )

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_with_skip_only(self, mock_service):
        mock_service.return_value = []

        response = client.get("/texts/text-123/commentaries?skip=10")

        assert response.status_code == 200
        mock_service.assert_called_once_with(
            edition_id="text-123",
            skip=10,
            limit=10
        )

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_with_limit_only(self, mock_service):
        mock_service.return_value = []

        response = client.get("/texts/text-123/commentaries?limit=50")

        assert response.status_code == 200
        mock_service.assert_called_once_with(
            edition_id="text-123",
            skip=0,
            limit=50
        )

    def test_get_text_commentaries_invalid_skip(self):
        response = client.get("/texts/text-123/commentaries?skip=-1")
        assert response.status_code == 422

    def test_get_text_commentaries_invalid_limit(self):
        response = client.get("/texts/text-123/commentaries?limit=101")
        assert response.status_code == 422


class TestGetTextCommentariesErrorHandling:
    """Tests for error handling in GET /v2/texts/{edition_id}/commentaries endpoint."""

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_not_found(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=404,
            detail="Text with id 'nonexistent' not found"
        )

        response = client.get("/texts/nonexistent/commentaries")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_upstream_error(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=502,
            detail="Failed to fetch commentaries from external API"
        )

        response = client.get("/texts/text-123/commentaries")

        assert response.status_code == 502

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_get_text_commentaries_internal_error(self, mock_service):
        mock_service.side_effect = HTTPException(
            status_code=500,
            detail="Internal server error"
        )

        response = client.get("/texts/text-123/commentaries")

        assert response.status_code == 500


class TestGetTextCommentariesResponseStructure:
    """Tests for response structure validation of commentaries endpoint."""

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_commentary_contains_all_required_fields(self, mock_service):
        mock_commentary = TextDTO(
            id="commentary-1",
            pecha_text_id="pecha-commentary-1",
            title="Commentary Title",
            language="bo",
            group_id="group-123",
            type="commentary",
            is_published=True,
            created_date="2025-01-01T00:00:00",
            updated_date="2025-01-01T00:00:00",
            published_date="2025-01-01T00:00:00",
            published_by="commentator",
            categories=["cat-1"],
            views=100,
            source_link="https://example.com",
            ranking=1,
            license="CC BY"
        )
        mock_service.return_value = [mock_commentary]

        response = client.get("/texts/text-123/commentaries")

        assert response.status_code == 200
        data = response.json()[0]
        assert "id" in data
        assert "pecha_text_id" in data
        assert "title" in data
        assert "language" in data
        assert "group_id" in data
        assert "type" in data
        assert "is_published" in data
        assert "created_date" in data
        assert "updated_date" in data
        assert "published_date" in data
        assert "published_by" in data
        assert "categories" in data
        assert "views" in data
        assert "source_link" in data
        assert "ranking" in data
        assert "license" in data

    @patch('pecha_api.texts.texts_openpecha_views.get_text_commentaries_by_edition_from_openpecha')
    def test_commentary_with_optional_fields_none(self, mock_service):
        mock_commentary = TextDTO(
            id="commentary-1",
            pecha_text_id="pecha-commentary-1",
            title="Commentary Title",
            language="bo",
            group_id="group-123",
            type="commentary",
            is_published=True,
            created_date="2025-01-01T00:00:00",
            updated_date="2025-01-01T00:00:00",
            published_date="2025-01-01T00:00:00",
            published_by="commentator",
            categories=[],
            views=0,
            source_link=None,
            ranking=None,
            license=None
        )
        mock_service.return_value = [mock_commentary]

        response = client.get("/texts/text-123/commentaries")

        assert response.status_code == 200
        data = response.json()[0]
        assert data["source_link"] is None
        assert data["ranking"] is None
        assert data["license"] is None
        assert data["categories"] == []
        assert data["views"] == 0


# =============================================================================
# POST /v2/texts/{text_id}/details - View Layer Tests
# =============================================================================

class TestGetTextDetailsEndpoint:
    """Tests for POST /v2/texts/{edition_id}/details endpoint."""

    MOCK_TEXT_DETAIL_DTO = {
        "id": "text-123",
        "pecha_text_id": "text-123",
        "title": "Heart Sutra",
        "language": "bo",
        "group_id": "cat-1",
        "type": "root_text",
        "summary": "",
        "is_published": True,
        "created_date": "",
        "updated_date": "",
        "published_date": "",
        "published_by": "",
        "categories": ["cat-1"],
        "views": 0,
        "likes": [],
    }

    @patch('pecha_api.texts.texts_openpecha_views.get_text_detail_by_id')
    def test_get_text_details_success(self, mock_service):
        from pecha_api.texts.text_openpecha_response_models import (
            TextDetailWithContentResponse,
            TextDetailDTO,
            ContentDTO,
            SectionDTO,
            SegmentDTO,
        )

        mock_service.return_value = TextDetailWithContentResponse(
            text_detail=TextDetailDTO(**self.MOCK_TEXT_DETAIL_DTO),
            content=ContentDTO(
                id="edition-123",
                text_id="text-123",
                sections=[
                    SectionDTO(
                        id="seg-1",
                        title="1",
                        section_number=1,
                        segments=[SegmentDTO(segment_id="span-1", segment_number=1, content="Hello")],
                    )
                ],
            ),
            size=20,
            pagination_direction="next",
            current_segment_position=1,
            total_segments=4,
            has_more_up=False,
            has_more_down=True,
        )

        response = client.post("/texts/edition-123/details", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["text_detail"]["id"] == "text-123"
        assert len(data["content"]["sections"][0]["segments"]) == 1
        assert data["total_segments"] == 4
        assert data["has_more_down"] is True
        mock_service.assert_called_once()
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["edition_id"] == "edition-123"
        assert call_kwargs["text_details_request"].segment_id is None
        assert call_kwargs["text_details_request"].size == 20
        assert call_kwargs["text_details_request"].direction.value == "next"

    @patch('pecha_api.texts.texts_openpecha_views.get_text_detail_by_id')
    def test_get_text_details_passes_segment_id_size_and_direction(self, mock_service):
        from pecha_api.texts.text_openpecha_response_models import (
            TextDetailWithContentResponse,
            TextDetailDTO,
            ContentDTO,
        )

        mock_service.return_value = TextDetailWithContentResponse(
            text_detail=TextDetailDTO(**self.MOCK_TEXT_DETAIL_DTO),
            content=ContentDTO(id="edition-123", text_id="text-123", sections=[]),
            size=5,
            pagination_direction="previous",
            current_segment_position=3,
            total_segments=4,
            has_more_up=True,
            has_more_down=True,
        )

        response = client.post(
            "/texts/text-123/details",
            json={"segment_id": "span-3", "size": 5, "direction": "previous"},
        )

        assert response.status_code == 200
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs["text_details_request"].segment_id == "span-3"
        assert call_kwargs["text_details_request"].size == 5
        assert call_kwargs["text_details_request"].direction.value == "previous"

    @patch('pecha_api.texts.texts_openpecha_views.get_text_detail_by_id')
    def test_get_text_details_segment_not_found_propagates_404(self, mock_service):
        mock_service.side_effect = HTTPException(status_code=404, detail="Segment with id 'missing' not found")

        response = client.post("/texts/text-123/details", json={"segment_id": "missing"})

        assert response.status_code == 404
