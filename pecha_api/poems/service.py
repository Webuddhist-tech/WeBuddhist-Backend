from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.config import get
from pecha_api.db.database import SessionLocal
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.poems.enums import PoemStatus
from pecha_api.poems.repository import get_poem_by_id, get_poems_list
from pecha_api.poems.response_models import PoemDTO, PoemsResponse
from pecha_api.poems.models import Poem
from pecha_api.timezone_utils import get_date_in_timezone
from pecha_api.uploads.S3_utils import generate_presigned_access_url


def _build_poem_dto(poem: Poem) -> PoemDTO:
    """Build poem DTO with presigned image URL."""
    image_url = None
    if poem.image_key:
        try:
            image_url = generate_presigned_access_url(
                bucket_name=get("AWS_BUCKET_NAME"),
                s3_key=poem.image_key,
            )
        except Exception:
            pass

    return PoemDTO(
        id=poem.id,
        title=poem.title,
        content=poem.content,
        author_name=poem.author_name,
        chapter_name=poem.chapter_name,
        language=poem.language.value,
        image_url=image_url,
        status=poem.status.value,
        published_at=poem.published_at.isoformat() if poem.published_at else None,
        created_at=poem.created_at.isoformat(),
        updated_at=poem.updated_at.isoformat(),
    )


def list_poems_service(
    skip: int = 0,
    limit: int = 20,
    chapter_name: Optional[str] = None,
    author_name: Optional[str] = None,
    language: Optional[LanguageCode] = None,
    seed: Optional[str] = None,
    timezone: Optional[str] = None,
) -> PoemsResponse:
    """List published poems for public consumption in shuffled order.

    Defaults to today's date in the given timezone (UTC if none) as the seed,
    so the order changes once a day and stays consistent across pages.
    """
    seed = seed or get_date_in_timezone(timezone).isoformat()
    with SessionLocal() as db:
        poems, total = get_poems_list(
            db=db,
            skip=skip,
            limit=limit,
            status=PoemStatus.PUBLISHED,
            chapter_name=chapter_name,
            author_name=author_name,
            language=language,
            shuffle_seed=seed,
        )

        poem_dtos = [_build_poem_dto(poem) for poem in poems]

        return PoemsResponse(
            poems=poem_dtos,
            skip=skip,
            limit=limit,
            total=total,
            seed=seed,
        )


def get_poem_detail_service(poem_id: UUID) -> PoemDTO:
    """Get a published poem by ID."""
    with SessionLocal() as db:
        poem = get_poem_by_id(db=db, poem_id=poem_id, status=PoemStatus.PUBLISHED)

        if poem is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Poem not found",
            )

        return _build_poem_dto(poem)
