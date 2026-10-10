from fastapi import APIRouter
from starlette import status
from typing import Optional

text_uploader_collections_router = APIRouter(
    prefix="/text-uploader/collections",
    tags=["CMS Text Uploader"]
)


@text_uploader_collections_router.get("/{pecha_collection_id}", status_code=status.HTTP_200_OK, deprecated=True)
async def get_collection_by_pecha_collection_id(pecha_collection_id: str) -> Optional[str]:
    """Mapped a pecha collection id to its MongoDB copy, which is gone, so no
    collection has one any more."""
    return None
