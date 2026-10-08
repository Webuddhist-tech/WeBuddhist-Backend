from uuid import UUID

from fastapi import APIRouter, Depends
from starlette import status

from pecha_api.chat.prayer_translation_internal_service import (
    apply_prayer_translation_result_service,
    get_prayer_translation_payload_service,
)
from pecha_api.chat.prayer_translation_response_models import (
    PrayerTranslationPayloadResponse,
    PrayerTranslationResultRequest,
)
from pecha_api.routines.routine_notifications.dependencies import verify_dispatch_token

internal_prayer_translation_router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
)


@internal_prayer_translation_router.get(
    "/prayer-translations/{message_id}",
    status_code=status.HTTP_200_OK,
    response_model=PrayerTranslationPayloadResponse,
)
def get_prayer_translation_payload(
    message_id: UUID,
    _: None = Depends(verify_dispatch_token),
) -> PrayerTranslationPayloadResponse:
    return get_prayer_translation_payload_service(message_id=message_id)


@internal_prayer_translation_router.post(
    "/prayer-translations/{message_id}/result",
    status_code=status.HTTP_204_NO_CONTENT,
)
def post_prayer_translation_result(
    message_id: UUID,
    request: PrayerTranslationResultRequest,
    _: None = Depends(verify_dispatch_token),
) -> None:
    apply_prayer_translation_result_service(message_id=message_id, request=request)
