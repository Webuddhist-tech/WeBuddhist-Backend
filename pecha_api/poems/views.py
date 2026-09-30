from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Header, Query
from starlette import status

from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.poems.response_models import PoemDTO, PoemsResponse
from pecha_api.poems.service import get_poem_detail_service, list_poems_service

poems_router = APIRouter(
    prefix="/poems",
    tags=["Poems"],
)


@poems_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=PoemsResponse,
)
def list_poems(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    chapter_name: Annotated[
        Optional[str],
        Query(description="Filter by chapter name (exact match)"),
    ] = None,
    author_name: Annotated[
        Optional[str],
        Query(description="Filter by author name (exact match)"),
    ] = None,
    language: Annotated[
        Optional[LanguageCode],
        Query(description="Filter by language code"),
    ] = None,
    seed: Annotated[
        Optional[str],
        Query(
            max_length=64,
            description=(
                "Shuffle seed. Defaults to today's date, so the order "
                "changes once a day."
            ),
        ),
    ] = None,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone for determining today's date."),
    ] = None,
) -> PoemsResponse:
    """List published poems in shuffled order."""
    return list_poems_service(
        skip=skip,
        limit=limit,
        chapter_name=chapter_name,
        author_name=author_name,
        language=language,
        seed=seed,
        timezone=x_timezone,
    )


@poems_router.get(
    "/{poem_id}",
    status_code=status.HTTP_200_OK,
    response_model=PoemDTO,
)
def get_poem_detail(poem_id: UUID) -> PoemDTO:
    """Get a published poem by ID with presigned image URL."""
    return get_poem_detail_service(poem_id=poem_id)
