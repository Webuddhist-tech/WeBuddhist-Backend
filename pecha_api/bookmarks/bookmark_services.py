from uuid import UUID
from typing import Optional

from pecha_api.db.database import SessionLocal
from pecha_api.bookmarks.bookmark_enums import BookmarkFilterType
from pecha_api.bookmarks.bookmark_utils import enrich_bookmark
from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.bookmarks.bookmark_models import Bookmark
from pecha_api.bookmarks.bookmark_repository import (
    save_bookmark,
    get_bookmarks_by_user_id,
    get_bookmark_by_user_and_source,
    delete_bookmark
)
from pecha_api.bookmarks.bookmark_response_models import (
    CreateBookmarkRequest,
    BookmarksResponse,
    BookmarkDTO,
    BookmarkExistsResponse,
    BookmarkExistsQuery,
)

async def create_bookmark_service(token: str, create_bookmark_request: CreateBookmarkRequest) -> BookmarkDTO:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        new_bookmark = Bookmark(
            user_id=current_user.id,
            type=create_bookmark_request.type,
            source_id=create_bookmark_request.source_id,
            name=create_bookmark_request.name
        )
        save_bookmark(db=db, bookmark=new_bookmark)

        return BookmarkDTO(
            id=new_bookmark.id,
            type=new_bookmark.type,
            source_id=new_bookmark.source_id,
            name=new_bookmark.name,
            created_at=new_bookmark.created_at,
            updated_at=new_bookmark.updated_at
        )


async def get_bookmarks_service(
    token: str,
    type: Optional[BookmarkFilterType] = None,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> BookmarksResponse:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        bookmarks, total = get_bookmarks_by_user_id(
            db=db,
            user_id=current_user.id,
            type=type,
            skip=skip,
            limit=limit,
        )

        bookmarks_dto = []
        for bookmark in bookmarks:
            enrichment = await enrich_bookmark(bookmark=bookmark, db=db, language=language)
            # enrich_bookmark returns {} when the bookmarked item no longer
            # exists or isn't visible to the user anymore (e.g. its
            # recitation collection, plan, series... was deleted) - drop the
            # bookmark from the response rather than showing a dangling entry.
            if not enrichment:
                continue
            bookmark_data = {
                "id": bookmark.id,
                "type": bookmark.type,
                "source_id": bookmark.source_id,
                "name": bookmark.name,
                "created_at": bookmark.created_at,
                "updated_at": bookmark.updated_at,
            }
            bookmark_data.update(enrichment)
            bookmarks_dto.append(BookmarkDTO(**bookmark_data))

        return BookmarksResponse(
            bookmarks=bookmarks_dto,
            total=total,
            skip=skip,
            limit=limit,
        )


async def delete_bookmark_service(token: str, bookmark_id: UUID) -> None:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        delete_bookmark(db=db, user_id=current_user.id, bookmark_id=bookmark_id)


async def bookmark_exists_service(
    token: str,
    bookmark_exists_query: BookmarkExistsQuery,
) -> BookmarkExistsResponse:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        bookmark = get_bookmark_by_user_and_source(
            db=db,
            user_id=current_user.id,
            source_id=bookmark_exists_query.source_id,
            type=bookmark_exists_query.type,
        )

        if bookmark is None:
            return BookmarkExistsResponse(exists=False)

        return BookmarkExistsResponse(exists=True, id=bookmark.id)
