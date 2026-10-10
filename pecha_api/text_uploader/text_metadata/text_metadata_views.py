from fastapi import APIRouter
from starlette import status
from typing import Optional, List

from pecha_api.texts.texts_response_models import TextDTO
from pecha_api.texts.texts_response_models import TextsByPechaTextIdsRequest

text_metadata_router = APIRouter(
    prefix="/text-uploader",
    tags=["CMS Text Uploader"]
)


@text_metadata_router.post("/list", status_code=status.HTTP_200_OK, deprecated=True)
async def get_text_by_pecha_text_ids(texts_by_pecha_text_ids_request: TextsByPechaTextIdsRequest) -> Optional[List[TextDTO]]:
    """Mapped pecha text ids to the uploaded copies kept in MongoDB, which is
    gone, so no id has an uploaded copy any more."""
    return []
