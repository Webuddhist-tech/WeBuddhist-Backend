"""Parse prayer translation JSON from Gemini or the worker (no API calls here)."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from pecha_api.plans.plans_enums import LanguageCode

# Must match pecha_api.prayer_intentions.prayer_intention_service.PRAYER_REQUEST_BODY_MAX_LENGTH
PRAYER_REQUEST_BODY_MAX_LENGTH = 280

PRAYER_TRANSLATION_LANGUAGE_CODES = ("EN", "BO", "ZH")


def parse_detected_source_language(value: object) -> Optional[str]:
    """ISO 639-1 two-letter code from Gemini; any language, not limited to app locales."""
    normalized = str(value or "").strip().upper()
    if len(normalized) != 2 or not normalized.isalpha():
        return None
    return normalized


def parse_prayer_translation_payload(
    payload: object,
) -> Optional[Tuple[str, Dict[LanguageCode, str]]]:
    if not isinstance(payload, dict):
        return None
    source_language = parse_detected_source_language(payload.get("source_language"))
    if source_language is None:
        return None

    translations_raw = payload.get("translations")
    if not isinstance(translations_raw, dict):
        return None
    translations: Dict[LanguageCode, str] = {}
    for code in PRAYER_TRANSLATION_LANGUAGE_CODES:
        text = translations_raw.get(code)
        if text is None:
            continue
        cleaned = str(text).strip()
        if not cleaned:
            continue
        if len(cleaned) > PRAYER_REQUEST_BODY_MAX_LENGTH:
            cleaned = cleaned[:PRAYER_REQUEST_BODY_MAX_LENGTH]
        translations[LanguageCode[code]] = cleaned

    return source_language, translations
