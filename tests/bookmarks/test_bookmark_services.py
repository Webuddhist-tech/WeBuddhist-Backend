import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime, timezone

from pecha_api.bookmarks.bookmark_services import (
    create_bookmark_service,
    get_bookmarks_service,
    delete_bookmark_service,
    bookmark_exists_service,
)
from pecha_api.bookmarks.bookmark_response_models import CreateBookmarkRequest, BookmarkExistsQuery
from pecha_api.bookmarks.bookmark_enums import BookmarkType, BookmarkFilterType


@pytest.mark.asyncio
async def test_create_bookmark_service_success():
    user_id = uuid4()
    source_id = str(uuid4())
    bookmark_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_bookmark = MagicMock()
    mock_bookmark.id = bookmark_id
    mock_bookmark.user_id = user_id
    mock_bookmark.type = BookmarkType.PLAN
    mock_bookmark.source_id = source_id
    mock_bookmark.name = "Test Bookmark"
    mock_bookmark.created_at = now
    mock_bookmark.updated_at = now

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    request = CreateBookmarkRequest(
        type=BookmarkType.PLAN,
        source_id=source_id,
        name="Test Bookmark"
    )

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.save_bookmark") as mock_save, \
         patch("pecha_api.bookmarks.bookmark_services.Bookmark") as mock_bookmark_class:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_bookmark_class.return_value = mock_bookmark

        result = await create_bookmark_service(token="test_token", create_bookmark_request=request)

        assert result.id == bookmark_id
        assert result.type == BookmarkType.PLAN
        assert result.source_id == source_id
        assert result.name == "Test Bookmark"
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_create_bookmark_service_verse_type():
    user_id = uuid4()
    verse_locator = "segment-ref-abc-123"
    bookmark_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_bookmark = MagicMock()
    mock_bookmark.id = bookmark_id
    mock_bookmark.user_id = user_id
    mock_bookmark.type = BookmarkType.VERSE
    mock_bookmark.source_id = verse_locator
    mock_bookmark.name = None
    mock_bookmark.created_at = now
    mock_bookmark.updated_at = now

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    request = CreateBookmarkRequest(
        type=BookmarkType.VERSE,
        source_id=verse_locator,
        name=None
    )

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.save_bookmark") as mock_save, \
         patch("pecha_api.bookmarks.bookmark_services.Bookmark") as mock_bookmark_class:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_bookmark_class.return_value = mock_bookmark

        result = await create_bookmark_service(token="test_token", create_bookmark_request=request)

        assert result.type == BookmarkType.VERSE
        assert result.source_id == verse_locator
        assert result.name is None


@pytest.mark.asyncio
async def test_get_bookmarks_service_success():
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_bookmark1 = MagicMock()
    mock_bookmark1.id = uuid4()
    mock_bookmark1.type = BookmarkType.SERIES
    mock_bookmark1.source_id = str(uuid4())
    mock_bookmark1.name = "Bookmark 1"
    mock_bookmark1.created_at = now
    mock_bookmark1.updated_at = now

    mock_bookmark2 = MagicMock()
    mock_bookmark2.id = uuid4()
    mock_bookmark2.type = BookmarkType.VERSE
    mock_bookmark2.source_id = "segment-ref-002"
    mock_bookmark2.name = None
    mock_bookmark2.created_at = now
    mock_bookmark2.updated_at = now

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.get_bookmarks_by_user_id") as mock_get, \
         patch("pecha_api.bookmarks.bookmark_services.enrich_bookmark", new_callable=AsyncMock) as mock_enrich:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_get.return_value = ([mock_bookmark1, mock_bookmark2], 2)
        mock_enrich.return_value = {"series": {"id": str(uuid4())}}

        result = await get_bookmarks_service(token="test_token")

        assert len(result.bookmarks) == 2
        assert result.total == 2
        assert result.skip == 0
        assert result.limit == 20
        assert result.bookmarks[0].type == BookmarkType.SERIES
        assert result.bookmarks[1].source_id == "segment-ref-002"
        assert result.bookmarks[1].name is None
        assert mock_enrich.call_count == 2


@pytest.mark.asyncio
async def test_get_bookmarks_service_drops_bookmarks_for_deleted_source():
    """enrich_bookmark returns {} when the bookmarked item (recitation
    collection, plan, series, ...) no longer exists or isn't visible to the
    user anymore - such bookmarks must not appear in the response."""
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_user = MagicMock()
    mock_user.id = user_id

    live_bookmark = MagicMock()
    live_bookmark.id = uuid4()
    live_bookmark.type = BookmarkType.RECITATION_COLLECTION
    live_bookmark.source_id = str(uuid4())
    live_bookmark.name = None
    live_bookmark.created_at = now
    live_bookmark.updated_at = now

    stale_bookmark = MagicMock()
    stale_bookmark.id = uuid4()
    stale_bookmark.type = BookmarkType.RECITATION_COLLECTION
    stale_bookmark.source_id = str(uuid4())
    stale_bookmark.name = None
    stale_bookmark.created_at = now
    stale_bookmark.updated_at = now

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    async def fake_enrich(bookmark, db, language=None):
        if bookmark is live_bookmark:
            return {
                "recitation_collection": {
                    "id": str(uuid4()),
                    "title": "Still there",
                    "item_count": 3,
                }
            }
        return {}

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.get_bookmarks_by_user_id") as mock_get, \
         patch("pecha_api.bookmarks.bookmark_services.enrich_bookmark", side_effect=fake_enrich):

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_get.return_value = ([live_bookmark, stale_bookmark], 2)

        result = await get_bookmarks_service(token="test_token")

        assert len(result.bookmarks) == 1
        assert result.bookmarks[0].id == live_bookmark.id


@pytest.mark.asyncio
async def test_get_bookmarks_service_with_text_filter_enriches_bookmarks():
    user_id = uuid4()
    text_id = str(uuid4())
    now = datetime.now(timezone.utc)

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_bookmark = MagicMock()
    mock_bookmark.id = uuid4()
    mock_bookmark.type = BookmarkType.TEXT
    mock_bookmark.source_id = text_id
    mock_bookmark.name = None
    mock_bookmark.created_at = now
    mock_bookmark.updated_at = now

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    enrichment = {
        "text": {
            "id": text_id,
            "title": "Heart Sutra",
            "segment": {
                "id": str(uuid4()),
                "content": "Introduction content",
            },
        }
    }

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.get_bookmarks_by_user_id") as mock_get, \
         patch("pecha_api.bookmarks.bookmark_services.enrich_bookmark", new_callable=AsyncMock) as mock_enrich:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_get.return_value = ([mock_bookmark], 1)
        mock_enrich.return_value = enrichment

        result = await get_bookmarks_service(token="test_token", type=BookmarkFilterType.TEXT)

        mock_get.assert_called_once_with(
            db=mock_db,
            user_id=user_id,
            type=BookmarkFilterType.TEXT,
            skip=0,
            limit=20,
        )
        mock_enrich.assert_called_once_with(
            bookmark=mock_bookmark,
            db=mock_db,
            language=None,
        )
        assert len(result.bookmarks) == 1
        assert result.bookmarks[0].text.title == "Heart Sutra"
        assert result.bookmarks[0].text.segment.content == "Introduction content"


@pytest.mark.asyncio
async def test_get_bookmarks_service_passes_language_to_enrichment():
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_bookmark = MagicMock()
    mock_bookmark.id = uuid4()
    mock_bookmark.type = BookmarkType.PLAN
    mock_bookmark.source_id = str(uuid4())
    mock_bookmark.name = None
    mock_bookmark.created_at = now
    mock_bookmark.updated_at = now

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.get_bookmarks_by_user_id") as mock_get, \
         patch("pecha_api.bookmarks.bookmark_services.enrich_bookmark", new_callable=AsyncMock) as mock_enrich:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_get.return_value = ([mock_bookmark], 1)
        mock_enrich.return_value = {}

        await get_bookmarks_service(token="test_token", language="bo", skip=10, limit=5)

        mock_get.assert_called_once_with(
            db=mock_db,
            user_id=user_id,
            type=None,
            skip=10,
            limit=5,
        )
        mock_enrich.assert_called_once_with(
            bookmark=mock_bookmark,
            db=mock_db,
            language="bo",
        )


@pytest.mark.asyncio
async def test_get_bookmarks_service_empty():
    user_id = uuid4()

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.get_bookmarks_by_user_id") as mock_get:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_get.return_value = ([], 0)

        result = await get_bookmarks_service(token="test_token")

        assert len(result.bookmarks) == 0
        assert result.total == 0


@pytest.mark.asyncio
async def test_delete_bookmark_service_success():
    user_id = uuid4()
    bookmark_id = uuid4()

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.delete_bookmark") as mock_delete:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db

        await delete_bookmark_service(token="test_token", bookmark_id=bookmark_id)

        mock_delete.assert_called_once_with(db=mock_db, user_id=user_id, bookmark_id=bookmark_id)


@pytest.mark.asyncio
async def test_bookmark_exists_service_true():
    user_id = uuid4()
    source_id = str(uuid4())
    bookmark_id = uuid4()

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_bookmark = MagicMock()
    mock_bookmark.id = bookmark_id

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.get_bookmark_by_user_and_source") as mock_get:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_get.return_value = mock_bookmark

        result = await bookmark_exists_service(
            token="test_token",
            bookmark_exists_query=BookmarkExistsQuery(
                type=BookmarkType.PLAN,
                source_id=source_id,
            ),
        )

        assert result.exists is True
        assert result.id == bookmark_id
        mock_get.assert_called_once_with(
            db=mock_db,
            user_id=user_id,
            source_id=source_id,
            type=BookmarkType.PLAN,
        )


@pytest.mark.asyncio
async def test_bookmark_exists_service_false():
    user_id = uuid4()
    source_id = str(uuid4())

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.get_bookmark_by_user_and_source") as mock_get:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_get.return_value = None

        result = await bookmark_exists_service(
            token="test_token",
            bookmark_exists_query=BookmarkExistsQuery(
                type=BookmarkType.TIMER,
                source_id=source_id,
            ),
        )

        assert result.exists is False
        assert result.id is None


@pytest.mark.asyncio
async def test_bookmark_exists_service_without_type():
    user_id = uuid4()
    source_id = str(uuid4())
    bookmark_id = uuid4()

    mock_user = MagicMock()
    mock_user.id = user_id

    mock_bookmark = MagicMock()
    mock_bookmark.id = bookmark_id

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("pecha_api.bookmarks.bookmark_services.validate_and_extract_user_details") as mock_validate, \
         patch("pecha_api.bookmarks.bookmark_services.SessionLocal") as mock_session, \
         patch("pecha_api.bookmarks.bookmark_services.get_bookmark_by_user_and_source") as mock_get:

        mock_validate.return_value = mock_user
        mock_session.return_value = mock_db
        mock_get.return_value = mock_bookmark

        result = await bookmark_exists_service(
            token="test_token",
            bookmark_exists_query=BookmarkExistsQuery(
                source_id=source_id,
            ),
        )

        assert result.exists is True
        assert result.id == bookmark_id
        mock_get.assert_called_once_with(
            db=mock_db,
            user_id=user_id,
            source_id=source_id,
            type=None,
        )
